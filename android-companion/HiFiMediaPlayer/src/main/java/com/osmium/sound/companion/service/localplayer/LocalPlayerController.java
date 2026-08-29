package com.osmium.sound.companion.service.localplayer;

import android.content.Context;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.Log;

import androidx.annotation.Nullable;

import com.osmium.sound.companion.BuildConfig;
import com.osmium.sound.companion.HiFiMediaPlayer;
import com.osmium.sound.companion.Preferences;

import java.nio.charset.StandardCharsets;

/**
 * Makes this phone one of the players Lyrion knows about.
 *
 * <p>Owned by the service rather than by an activity: a player has to keep going
 * with the screen off and the app in the background, which is exactly what the
 * existing third-party player hooks in {@code util/DevicePlayers} cannot do.
 *
 * <p>The server remains the single source of truth. Once registered, the phone
 * is an ordinary player: the playlist, metadata, track position and play state
 * all arrive through the CometD session the app already maintains, so the
 * notification, the player list and the media buttons need no special case. What
 * lives here is only the protocol session and the audio.
 */
public class LocalPlayerController implements SlimProtoClient.Listener, SlimAudioEngine.Events {

    private static final String TAG = "LocalPlayer";

    /**
     * A model Lyrion already knows, so its transcoding rules and every other
     * controller's icons behave. This phone is told apart by its player id, not
     * by its model.
     */
    private static final String MODEL = "squeezelite";

    /** Long enough to sit out the flapping of a Wi-Fi to mobile handover. */
    private static final long NETWORK_DEBOUNCE_MS = 5000;

    /** Cached for the UI, which asks whether a player is this phone. */
    @Nullable
    private static volatile String localPlayerId;

    private final Context context;
    private final LocalPlayerHost host;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final PlaybackSnapshot snapshot = new PlaybackSnapshot();

    private LocalPlayerIdentity identity;
    private final boolean hasFlacDecoder;

    @Nullable
    private SlimProtoClient client;
    @Nullable
    private SlimAudioEngine engine;
    @Nullable
    private String serverHost;
    @Nullable
    private String authorization;

    private boolean rendering;
    private boolean qualityChangePending;
    private boolean networkCallbackRegistered;

    public LocalPlayerController(Context context, LocalPlayerHost host) {
        this.context = context.getApplicationContext();
        this.host = host;
        this.hasFlacDecoder = deviceHasFlacDecoder();
        this.identity = LocalPlayerIdentity.load(this.context, HiFiMediaPlayer.getPreferences());
        localPlayerId = identity.macString();
    }

    /** True when this Lyrion player id is this phone, whatever case it is in. */
    public static boolean isThisPhone(@Nullable String playerId) {
        if (playerId == null) return false;
        String mine = localPlayerId;
        if (mine == null) {
            Preferences preferences = HiFiMediaPlayer.getPreferences();
            mine = preferences != null ? preferences.getLocalPlayerMac() : null;
            localPlayerId = mine;
        }
        return mine != null && playerId.equalsIgnoreCase(mine);
    }

    /** The id this phone registers under, for the service and the UI. */
    public String playerId() {
        return identity.macString();
    }

    /** True while sound is actually coming out of this phone. */
    public boolean isRendering() {
        return rendering;
    }

    // -------------------------------------------------------------- lifecycle

    /**
     * Follows the app's own connection: there is no point holding a player
     * session open against a server the app cannot reach either.
     */
    public void onServerConnectionChanged(boolean connected, @Nullable String host,
                                          @Nullable String username, @Nullable String password) {
        if (!connected || host == null) {
            stopSession();
            return;
        }
        this.authorization = credentials(username, password);
        if (!HiFiMediaPlayer.getPreferences().isLocalPlayerEnabled()) {
            stopSession();
            return;
        }
        if (client != null && host.equals(serverHost)) {
            return;
        }
        startSession(host);
    }

    private void startSession(String host) {
        stopSession();
        serverHost = host;

        engine = new SlimAudioEngine(context, snapshot, this);
        engine.setAuthorization(authorization);

        client = new SlimProtoClient(host, SlimProtoClient.PORT, identity, snapshot,
                capabilities(), this);
        client.start();
        registerNetworkCallback();
        Log.i(TAG, "player session starting against " + host + " as " + identity.macString());
    }

    private void stopSession() {
        unregisterNetworkCallback();
        if (client != null) {
            client.stop();
            client = null;
        }
        if (engine != null) {
            engine.release();
            engine = null;
        }
        serverHost = null;
        setRendering(false);
    }

    /** Called from the service when it is going away. */
    public void shutdown() {
        stopSession();
    }

    /** Reacts to the settings that change what the player is or does. */
    public void onPreferenceChanged(Preferences preferences, String key) {
        switch (key) {
            case Preferences.KEY_LOCAL_PLAYER_ENABLED:
                if (preferences.isLocalPlayerEnabled()) {
                    if (client == null && serverHost != null) startSession(serverHost);
                } else {
                    stopSession();
                }
                break;
            case Preferences.KEY_LOCAL_PLAYER_NAME:
                if (client != null) {
                    client.sendSetd(SlimProtoMessages.Setd.ID_PLAYER_NAME, preferences.getLocalPlayerName());
                    host.sendLocalPlayerCommand(identity.macString(), "name",
                            preferences.getLocalPlayerName());
                }
                break;
            case Preferences.KEY_LOCAL_PLAYER_QUALITY_WIFI:
            case Preferences.KEY_LOCAL_PLAYER_QUALITY_MOBILE:
                applyQualityChange();
                break;
            default:
                break;
        }
    }

    // ------------------------------------------------------------ capabilities

    private String capabilities() {
        Preferences preferences = HiFiMediaPlayer.getPreferences();
        Preferences.LocalPlayerQuality quality = preferences.getLocalPlayerQuality(isMetered());
        return SlimFormats.capabilities(MODEL, preferences.getLocalPlayerName(),
                BuildConfig.VERSION_NAME, SlimFormats.DEFAULT_MAX_SAMPLE_RATE,
                quality.codecs(hasFlacDecoder));
    }

    /**
     * Capabilities only travel with HELO, so changing them means reconnecting.
     * Doing that mid-track makes the server restart the stream, so it waits for
     * a gap in playback.
     */
    private void applyQualityChange() {
        if (client == null) return;
        if (rendering) {
            qualityChangePending = true;
            return;
        }
        qualityChangePending = false;
        client.setCapabilities(capabilities());
        sendMaxBitrate();
    }

    /**
     * The bitrate cap is a per-player server setting rather than a capability,
     * so it goes over the control connection.
     */
    private void sendMaxBitrate() {
        Preferences preferences = HiFiMediaPlayer.getPreferences();
        int maxBitrate = preferences.getLocalPlayerQuality(isMetered()).maxBitrate();
        host.sendLocalPlayerCommand(identity.macString(), "playerpref", "maxBitrate",
                String.valueOf(maxBitrate));
    }

    private boolean isMetered() {
        ConnectivityManager connectivity = context.getSystemService(ConnectivityManager.class);
        if (connectivity == null) return false;
        Network network = connectivity.getActiveNetwork();
        if (network == null) return false;
        NetworkCapabilities capabilities = connectivity.getNetworkCapabilities(network);
        return capabilities != null
                && !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED);
    }

    /**
     * FLAC decoding is only guaranteed from API 27, and this app still supports
     * 26. Asking the platform is cheaper than shipping a decoder.
     */
    private static boolean deviceHasFlacDecoder() {
        try {
            MediaFormat format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_FLAC,
                    44100, 2);
            return new MediaCodecList(MediaCodecList.REGULAR_CODECS).findDecoderForFormat(format) != null;
        } catch (RuntimeException e) {
            return false;
        }
    }

    private final ConnectivityManager.NetworkCallback networkCallback =
            new ConnectivityManager.NetworkCallback() {
                @Override
                public void onCapabilitiesChanged(Network network, NetworkCapabilities capabilities) {
                    main.removeCallbacks(networkSettled);
                    main.postDelayed(networkSettled, NETWORK_DEBOUNCE_MS);
                }
            };

    private final Runnable networkSettled = this::applyQualityChange;

    private void registerNetworkCallback() {
        if (networkCallbackRegistered) return;
        ConnectivityManager connectivity = context.getSystemService(ConnectivityManager.class);
        if (connectivity == null) return;
        try {
            connectivity.registerDefaultNetworkCallback(networkCallback);
            networkCallbackRegistered = true;
        } catch (RuntimeException e) {
            Log.w(TAG, "cannot watch the network: " + e.getMessage());
        }
    }

    private void unregisterNetworkCallback() {
        if (!networkCallbackRegistered) return;
        networkCallbackRegistered = false;
        main.removeCallbacks(networkSettled);
        ConnectivityManager connectivity = context.getSystemService(ConnectivityManager.class);
        if (connectivity == null) return;
        try {
            connectivity.unregisterNetworkCallback(networkCallback);
        } catch (RuntimeException ignored) {
            // Already gone.
        }
    }

    private static String credentials(@Nullable String username, @Nullable String password) {
        if (username == null || username.isEmpty()) return null;
        String pair = username + ":" + (password == null ? "" : password);
        return Base64.encodeToString(pair.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
    }

    // ------------------------------------------------------- protocol listener

    @Override
    public void onRegistered() {
        sendMaxBitrate();
    }

    @Override
    public void onDisconnected(boolean willRetry) {
        Log.i(TAG, "player session dropped" + (willRetry ? ", retrying" : ""));
        setRendering(false);
    }

    @Override
    public void onStrm(SlimProtoMessages.Strm strm) {
        SlimAudioEngine audio = engine;
        SlimProtoClient session = client;
        if (audio == null || session == null) return;

        switch (strm.command) {
            case 's':
                audio.start(strm, session.serverAddress());
                break;
            case 'p':
                audio.pause(strm.replayGain);
                break;
            case 'u':
                audio.unpause();
                break;
            case 'q':
                audio.stop();
                break;
            case 'f':
                audio.flush();
                break;
            case 't':
                session.sendStatusAnswer(strm.replayGain);
                break;
            case 'a':
                // Skip-ahead exists for hardware players that buffer minutes of
                // audio; the server also handles it by restarting the stream.
                Log.d(TAG, "ignoring skip-ahead of " + strm.replayGain + "ms");
                break;
            default:
                Log.d(TAG, "unhandled strm " + strm.command);
                break;
        }
    }

    @Override
    public void onAudg(SlimProtoMessages.Audg audg) {
        float gain = audg.linearGain();
        if (gain == 0f) {
            // Worth saying out loud: everything else looks like normal playback,
            // and the server has simply set this player's volume to zero.
            Log.w(TAG, "the server set this player's volume to zero: nothing will be heard");
        }
        if (engine != null) engine.setGain(gain);
    }

    @Override
    public void onAude(SlimProtoMessages.Aude aude) {
        if (engine != null) engine.setOutputEnabled(aude.dac);
    }

    @Override
    public void onSetd(SlimProtoMessages.Setd setd) {
        if (setd.id != SlimProtoMessages.Setd.ID_PLAYER_NAME || client == null) return;
        Preferences preferences = HiFiMediaPlayer.getPreferences();
        if (setd.isQuery()) {
            // Answering during registration is what stops the player from
            // showing up under a placeholder name.
            client.sendSetd(SlimProtoMessages.Setd.ID_PLAYER_NAME, preferences.getLocalPlayerName());
        } else if (!setd.value.isEmpty()) {
            preferences.setLocalPlayerName(setd.value);
        }
    }

    @Override
    public void onServ(SlimProtoMessages.Serv serv) {
        if (!serv.isPrivateAddress()) {
            // A public address is a redirect to the online service, which this
            // player has no business following.
            Log.i(TAG, "ignoring redirect to " + serv.ipString());
            return;
        }
        Log.i(TAG, "server moved us to " + serv.ipString());
        startSession(serv.ipString());
    }

    // ---------------------------------------------------------- engine events

    @Override
    public void sendStat(String event) {
        if (client != null) client.sendStat(event);
    }

    @Override
    public void sendResp(String responseHeaders) {
        if (client != null) client.sendResp(responseHeaders);
    }

    @Override
    public void sendDsco(int reason) {
        if (client != null) client.sendDsco(reason);
    }

    @Override
    public void onRenderingChanged(boolean nowRendering) {
        main.post(() -> {
            setRendering(nowRendering);
            if (!nowRendering && qualityChangePending) applyQualityChange();
        });
    }

    @Override
    public void onPlaybackInterrupted() {
        // A call, another app or unplugged headphones stopped us. Telling the
        // server keeps its clock and its play/pause state honest.
        main.post(() -> host.sendLocalPlayerCommand(identity.macString(), "pause", "1"));
    }

    private void setRendering(boolean nowRendering) {
        if (rendering == nowRendering) return;
        rendering = nowRendering;
        if (client != null) client.setHeartbeatEnabled(nowRendering);
        host.onLocalPlaybackStateChanged(nowRendering);
    }
}
