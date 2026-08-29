package com.osmium.sound.companion.service.localplayer;

import android.content.Context;
import android.net.Uri;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;

import androidx.annotation.Nullable;
import androidx.annotation.OptIn;
import androidx.media3.common.AudioAttributes;
import androidx.media3.common.C;
import androidx.media3.common.MediaItem;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.Player;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.DataSource;
import androidx.media3.exoplayer.DefaultLoadControl;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.source.MediaSource;
import androidx.media3.exoplayer.source.ProgressiveMediaSource;
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy;
import androidx.media3.extractor.Extractor;
import androidx.media3.extractor.ExtractorsFactory;
import androidx.media3.extractor.flac.FlacExtractor;
import androidx.media3.extractor.mp3.Mp3Extractor;
import androidx.media3.extractor.mp4.Mp4Extractor;
import androidx.media3.extractor.ogg.OggExtractor;
import androidx.media3.extractor.ts.AdtsExtractor;

import java.io.IOException;
import java.net.InetAddress;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

/**
 * Turns {@code strm} commands into sound, and playback back into STAT events.
 *
 * <p>Everything runs on a dedicated "slimplayer" thread that owns the ExoPlayer
 * instance; opening a stream socket happens off it, so a slow server never
 * stalls playback of the track already running.
 *
 * <p>Gapless works the way the protocol intends: when the decoder has been given
 * the last byte of a track we report STMd, the server answers with the next
 * {@code strm s} while the current one is still playing, and that stream is
 * appended to the player's playlist rather than replacing it.
 */
@OptIn(markerClass = UnstableApi.class)
class SlimAudioEngine {

    private static final String TAG = "SlimAudioEngine";

    /** Nominal decoded buffer reported to the server: 20 s of CD audio. */
    private static final long OUTPUT_BUFFER_SIZE = 20L * 44100 * 2 * 2;
    private static final long BYTES_PER_MS = 44100L * 2 * 2 / 1000;
    private static final long POSITION_POLL_MS = 200;

    /** What the engine needs to tell the server. Called on the engine thread. */
    interface Events {
        void sendStat(String event);

        void sendResp(String responseHeaders);

        void sendDsco(int reason);

        /** Rendering started or stopped: drives the foreground notification. */
        void onRenderingChanged(boolean rendering);

        /** Playback was taken away from us (a call, another app, unplugged headphones). */
        void onPlaybackInterrupted();
    }

    private final Context context;
    private final PlaybackSnapshot snapshot;
    private final Events events;
    private final HandlerThread thread;
    private final Handler handler;
    private final Executor connector = Executors.newSingleThreadExecutor();

    private ExoPlayer player;

    /** Identifies a stream so that a slow connect cannot disturb a newer one. */
    private int streamSequence;

    @Nullable
    private SlimStreamConnection current;
    @Nullable
    private SlimStreamConnection next;

    /** The FLAC header of the track being played, kept for headerless seeks. */
    @Nullable
    private byte[] flacHeader;

    private boolean waitingForUnpause;
    private boolean thresholdReported;
    private boolean pendingTrackStart;
    private boolean rendering;
    private boolean gainMuted;
    private float gain = 1f;
    @Nullable
    private String authorization;

    SlimAudioEngine(Context context, PlaybackSnapshot snapshot, Events events) {
        this.context = context.getApplicationContext();
        this.snapshot = snapshot;
        this.events = events;
        this.thread = new HandlerThread("slimplayer");
        this.thread.start();
        this.handler = new Handler(thread.getLooper());
        handler.post(this::createPlayer);
    }

    private void createPlayer() {
        DefaultLoadControl loadControl = new DefaultLoadControl.Builder()
                // Enough to ride out a Wi-Fi dropout without holding minutes of
                // audio in memory. The player stops loading when it reaches the
                // ceiling and resumes later, which the data source handles.
                .setBufferDurationsMs(15_000, 30_000, 2_500, 5_000)
                .build();
        player = new ExoPlayer.Builder(context)
                .setLooper(thread.getLooper())
                .setLoadControl(loadControl)
                .build();
        player.setAudioAttributes(new AudioAttributes.Builder()
                .setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
                .build(), /* handleAudioFocus= */ true);
        player.setHandleAudioBecomingNoisy(true);
        player.setWakeMode(C.WAKE_MODE_NETWORK);
        player.addListener(playerListener);
        snapshot.outputBufferSize = OUTPUT_BUFFER_SIZE;
    }

    void setAuthorization(@Nullable String basicAuthorization) {
        handler.post(() -> authorization = basicAuthorization);
    }

    void release() {
        handler.post(() -> {
            closeStreams();
            if (player != null) {
                player.removeListener(playerListener);
                player.release();
                player = null;
            }
            thread.quitSafely();
        });
    }

    // --------------------------------------------------------------- commands

    /** strm 's': open the stream the server describes and get ready to play. */
    void start(SlimProtoMessages.Strm strm, InetAddress controlServer) {
        handler.post(() -> {
            events.sendStat(SlimProtoCodec.STMf);

            if (!SlimFormats.isSupportedFormat(strm.format)) {
                // Saying so is important: without STMn the server waits forever
                // on a track that is never going to play.
                Log.w(TAG, "cannot decode format " + SlimFormats.formatName(strm.format));
                events.sendStat(SlimProtoCodec.STMn);
                return;
            }

            boolean append = current != null && current.isSocketEnded() && player != null
                    && player.getMediaItemCount() > 0;
            if (!append) {
                closeStreams();
                snapshot.resetForNewTrack();
            }

            InetAddress address;
            try {
                address = strm.useControlServer()
                        ? controlServer
                        : InetAddress.getByAddress(strm.serverIp);
            } catch (IOException e) {
                Log.w(TAG, "bad stream address: " + e.getMessage());
                events.sendStat(SlimProtoCodec.STMn);
                return;
            }
            int port = strm.serverPort != 0 ? strm.serverPort : 9000;

            final int sequence = ++streamSequence;
            SlimStreamConnection connection = new SlimStreamConnection(address, port,
                    strm.httpHeader, snapshot, streamCallback);
            connection.setAuthorization(authorization);
            if (strm.format == 'f') connection.setFlacPreamble(flacHeader);
            connector.execute(() -> {
                try {
                    connection.open();
                    handler.post(() -> onStreamOpened(sequence, strm, connection, append));
                } catch (IOException e) {
                    Log.w(TAG, "stream connect failed: " + e.getMessage());
                    connection.close();
                    handler.post(() -> {
                        if (sequence != streamSequence) return;
                        events.sendDsco(SlimProtoCodec.DISCONNECT_UNREACHABLE);
                        events.sendStat(SlimProtoCodec.STMn);
                    });
                }
            });
        });
    }

    private void onStreamOpened(int sequence, SlimProtoMessages.Strm strm,
                                SlimStreamConnection connection, boolean append) {
        if (sequence != streamSequence || player == null) {
            connection.close();
            return;
        }
        events.sendStat(SlimProtoCodec.STMc);
        Log.i(TAG, "stream open: " + SlimFormats.formatName(strm.format)
                + " autostart=" + strm.autostart + (append ? " (queued)" : " (now)"));

        MediaSource source = buildSource(sequence, strm.format, connection);
        if (append) {
            next = connection;
            player.addMediaSource(source);
        } else {
            current = connection;
            player.setMediaSource(source);
            player.prepare();
        }

        // autostart 0 means the server wants to start us itself, once we say we
        // have buffered enough; anything else means start on our own.
        // autostart 0 means the server starts us itself, once we report that we
        // have buffered enough; anything else means start on our own.
        waitingForUnpause = strm.autostart == 0;
        thresholdReported = false;
        pendingTrackStart = true;
        if (!waitingForUnpause && !append) {
            player.setPlayWhenReady(true);
        }
    }

    private MediaSource buildSource(int sequence, char format, SlimStreamConnection connection) {
        DataSource.Factory dataSourceFactory = SlimStreamDataSource.factory(connection,
                () -> handler.post(() -> onEndOfInput(connection)));
        Uri uri = Uri.parse("slim://stream/" + sequence);
        return new ProgressiveMediaSource.Factory(dataSourceFactory, extractorsFor(format))
                // A consumed socket cannot be reopened, so a retry would only
                // turn an honest error into silence.
                .setLoadErrorHandlingPolicy(new DefaultLoadErrorHandlingPolicy(0))
                .createMediaSource(MediaItem.fromUri(uri));
    }

    private static ExtractorsFactory extractorsFor(char format) {
        switch (format) {
            case 'f':
                return () -> new Extractor[]{new FlacExtractor()};
            case 'a':
                // Lyrion sends either raw ADTS or the original .m4a.
                return () -> new Extractor[]{new AdtsExtractor(), new Mp4Extractor()};
            case 'o':
                return () -> new Extractor[]{new OggExtractor()};
            case 'm':
            default:
                return () -> new Extractor[]{new Mp3Extractor()};
        }
    }

    /** strm 'p': pause now, or after the given number of milliseconds. */
    void pause(long intervalMs) {
        handler.post(() -> {
            if (player == null) return;
            if (intervalMs > 0) {
                handler.postDelayed(() -> {
                    if (player != null) player.setPlayWhenReady(false);
                }, intervalMs);
            } else {
                player.setPlayWhenReady(false);
                events.sendStat(SlimProtoCodec.STMp);
            }
        });
    }

    /** strm 'u': resume. */
    void unpause() {
        handler.post(() -> {
            if (player == null) return;
            waitingForUnpause = false;
            player.setPlayWhenReady(true);
            events.sendStat(SlimProtoCodec.STMr);
        });
    }

    /** strm 'q': stop and forget everything. */
    void stop() {
        handler.post(() -> {
            if (player != null) {
                player.stop();
                player.clearMediaItems();
            }
            closeStreams();
            snapshot.resetForNewTrack();
            events.sendStat(SlimProtoCodec.STMf);
            setRendering(false);
        });
    }

    /** strm 'f': drop what is buffered but stay ready. */
    void flush() {
        handler.post(() -> {
            boolean hadStream = current != null;
            if (player != null) {
                player.stop();
                player.clearMediaItems();
            }
            closeStreams();
            snapshot.resetForNewTrack();
            if (hadStream) events.sendStat(SlimProtoCodec.STMf);
            setRendering(false);
        });
    }

    /** audg: the server's volume, already curved, as a linear gain. */
    void setGain(float linearGain) {
        handler.post(() -> {
            gain = linearGain;
            applyVolume();
        });
    }

    /** aude: the server can silence the output without stopping the stream. */
    void setOutputEnabled(boolean enabled) {
        handler.post(() -> {
            gainMuted = !enabled;
            applyVolume();
        });
    }

    private void applyVolume() {
        if (player == null) return;
        float volume = gainMuted ? 0f : gain;
        Log.i(TAG, "volume -> " + volume + (gainMuted ? " (output disabled by the server)" : ""));
        player.setVolume(volume);
    }

    boolean isRendering() {
        return rendering;
    }

    // ---------------------------------------------------------------- streams

    private final SlimStreamConnection.Callback streamCallback = new SlimStreamConnection.Callback() {
        @Override
        public void onStreamHeaders(SlimStreamConnection connection, String headers) {
            handler.post(() -> events.sendResp(headers));
        }

        @Override
        public void onFlacHeader(byte[] header) {
            handler.post(() -> flacHeader = header);
        }

        @Override
        public void onStreamSocketClosed(SlimStreamConnection connection) {
            handler.post(() -> events.sendDsco(SlimProtoCodec.DISCONNECT_OK));
        }

        @Override
        public void onStreamError(SlimStreamConnection connection, int reason) {
            handler.post(() -> events.sendDsco(reason));
        }
    };

    /**
     * The decoder has been handed the last byte of this track. This, and not the
     * end of playback, is what makes the server send the next one, so it has to
     * be reported the moment it happens.
     */
    private void onEndOfInput(SlimStreamConnection connection) {
        if (connection != current && connection != next) return;
        events.sendStat(SlimProtoCodec.STMd);
    }

    private void closeStreams() {
        if (current != null) {
            current.close();
            current = null;
        }
        if (next != null) {
            next.close();
            next = null;
        }
    }

    // --------------------------------------------------------------- listener

    private final Player.Listener playerListener = new Player.Listener() {
        @Override
        public void onPlaybackStateChanged(int state) {
            Log.i(TAG, "playback state " + state + " playWhenReady="
                    + (player != null && player.getPlayWhenReady()));
            if (state == Player.STATE_READY && waitingForUnpause && !thresholdReported) {
                // Buffered and holding: this is what the server is waiting for
                // before it sends the unpause.
                thresholdReported = true;
                events.sendStat(SlimProtoCodec.STMl);
                return;
            }
            if (state == Player.STATE_ENDED) {
                events.sendStat(SlimProtoCodec.STMu);
                setRendering(false);
            }
        }

        @Override
        public void onIsPlayingChanged(boolean isPlaying) {
            setRendering(isPlaying);
            if (isPlaying) {
                if (pendingTrackStart) {
                    // The server counts a track as started when it is audible,
                    // not when it was queued.
                    pendingTrackStart = false;
                    events.sendStat(SlimProtoCodec.STMs);
                }
                handler.post(positionPoll);
            } else {
                handler.removeCallbacks(positionPoll);
            }
        }

        @Override
        public void onMediaItemTransition(@Nullable MediaItem mediaItem, int reason) {
            if (reason == Player.MEDIA_ITEM_TRANSITION_REASON_AUTO) {
                // The queued track took over: the previous one is finished with.
                if (next != null) {
                    if (current != null) current.close();
                    current = next;
                    next = null;
                }
                snapshot.resetForNewTrack();
                if (player != null && player.getMediaItemCount() > 1) {
                    player.removeMediaItem(0);
                }
                // The queued track is audible from this moment.
                pendingTrackStart = false;
                events.sendStat(SlimProtoCodec.STMs);
            }
        }

        @Override
        public void onPlayWhenReadyChanged(boolean playWhenReady, int reason) {
            Log.i(TAG, "playWhenReady=" + playWhenReady + " reason=" + reason);
            if (!playWhenReady
                    && (reason == Player.PLAY_WHEN_READY_CHANGE_REASON_AUDIO_FOCUS_LOSS
                    || reason == Player.PLAY_WHEN_READY_CHANGE_REASON_AUDIO_BECOMING_NOISY)) {
                // Something else took the audio. Tell the server, or its clock
                // keeps running against a track nobody can hear.
                events.onPlaybackInterrupted();
            }
        }

        @Override
        public void onPlayerError(PlaybackException error) {
            Log.e(TAG, "playback failed: " + error.getErrorCodeName() + " — "
                    + (error.getCause() != null ? error.getCause() : error.getMessage()), error);
            snapshot.errorCode = error.errorCode;
            events.sendStat(SlimProtoCodec.STMn);
            setRendering(false);
        }
    };

    private final Runnable positionPoll = new Runnable() {
        @Override
        public void run() {
            if (player == null) return;
            snapshot.elapsedMilliseconds = Math.max(0, player.getCurrentPosition());
            snapshot.outputBufferFullness =
                    Math.min(OUTPUT_BUFFER_SIZE, player.getTotalBufferedDuration() * BYTES_PER_MS);
            if (player.isPlaying()) handler.postDelayed(this, POSITION_POLL_MS);
        }
    };

    private void setRendering(boolean nowRendering) {
        if (rendering == nowRendering) return;
        rendering = nowRendering;
        events.onRenderingChanged(nowRendering);
    }
}
