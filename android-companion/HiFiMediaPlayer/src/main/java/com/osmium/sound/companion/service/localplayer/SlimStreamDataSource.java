package com.osmium.sound.companion.service.localplayer;

import android.net.Uri;
import android.util.Log;

import androidx.annotation.OptIn;
import androidx.media3.common.C;
import androidx.media3.common.util.UnstableApi;
import androidx.media3.datasource.BaseDataSource;
import androidx.media3.datasource.DataSource;
import androidx.media3.datasource.DataSpec;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Feeds one {@link SlimStreamConnection} to the player.
 *
 * <p>The player does not read a track in one go. Once it has buffered enough it
 * stops loading, closes this source, and later reopens it to carry on — and the
 * position it asks to resume from is the extractor's read position, which can be
 * a little behind what was actually handed over, because the extractor peeks
 * ahead while parsing. The bytes come off a socket the server is feeding us, so
 * there is nothing to rewind to unless we keep some.
 *
 * <p>Hence the rewind window: the last stretch of delivered audio is kept so a
 * resume slightly behind can be served from memory before falling back to the
 * socket. Anything further back is refused loudly rather than answered with the
 * wrong audio — Lyrion seeks by opening a new stream, not by asking us to.
 */
@OptIn(markerClass = UnstableApi.class)
final class SlimStreamDataSource extends BaseDataSource {

    private static final String TAG = "SlimStream";

    /**
     * How far back a resume may reach. The extractor's peek buffer is measured
     * in tens of kilobytes; this is roomy enough to never think about it again.
     */
    private static final int REWIND_BYTES = 512 * 1024;

    /** Called once, when the decoder has been handed every byte of the track. */
    interface EndOfInputListener {
        void onEndOfInput();
    }

    private final SlimStream connection;
    private final EndOfInputListener endOfInputListener;
    private final AtomicBoolean endOfInputReported = new AtomicBoolean();

    private final byte[] rewind = new byte[REWIND_BYTES];
    /** Bytes read from the socket and handed on: the head of the rewind window. */
    private long streamPosition;
    /** Where the player is reading, which may sit inside the rewind window. */
    private long readPosition;

    private Uri uri;
    private boolean opened;

    /** Visible for tests, which drive it without a socket. */
    SlimStreamDataSource(SlimStream connection, EndOfInputListener listener) {
        super(/* isNetwork= */ true);
        this.connection = connection;
        this.endOfInputListener = listener;
    }

    /** A factory that always hands out this one source, backed by one socket. */
    static DataSource.Factory factory(SlimStream connection, EndOfInputListener listener) {
        SlimStreamDataSource source = new SlimStreamDataSource(connection, listener);
        return () -> source;
    }

    @Override
    public long open(DataSpec dataSpec) throws IOException {
        long requested = dataSpec.position;
        if (requested > streamPosition || requested < streamPosition - REWIND_BYTES) {
            throw new IOException("cannot resume a live stream at " + requested
                    + ": have " + (streamPosition - Math.min(streamPosition, REWIND_BYTES))
                    + ".." + streamPosition);
        }
        if (requested != readPosition) {
            Log.d(TAG, "resuming " + (streamPosition - requested) + " bytes back");
        }
        readPosition = requested;
        uri = dataSpec.uri;
        if (!opened) {
            opened = true;
            transferInitializing(dataSpec);
        }
        transferStarted(dataSpec);
        // The server streams; there is no length. Real seeks travel the other
        // way, as a new strm command from Lyrion.
        return C.LENGTH_UNSET;
    }

    @Override
    public int read(byte[] buffer, int offset, int length) throws IOException {
        if (length == 0) return 0;

        // Still catching up inside the rewind window: serve from memory.
        if (readPosition < streamPosition) {
            int available = (int) Math.min(length, streamPosition - readPosition);
            int start = (int) (readPosition % REWIND_BYTES);
            int firstChunk = Math.min(available, REWIND_BYTES - start);
            System.arraycopy(rewind, start, buffer, offset, firstChunk);
            if (firstChunk < available) {
                System.arraycopy(rewind, 0, buffer, offset + firstChunk, available - firstChunk);
            }
            readPosition += available;
            bytesTransferred(available);
            return available;
        }

        int read = connection.read(buffer, offset, length);
        if (read == -1) {
            if (endOfInputReported.compareAndSet(false, true)) {
                Log.i(TAG, "end of track after " + streamPosition + " bytes");
                endOfInputListener.onEndOfInput();
            }
            return C.RESULT_END_OF_INPUT;
        }
        remember(buffer, offset, read);
        streamPosition += read;
        readPosition = streamPosition;
        bytesTransferred(read);
        return read;
    }

    /** Keeps the tail of the stream so a resume can be served without the socket. */
    private void remember(byte[] buffer, int offset, int length) {
        // A read bigger than the whole window can only keep its tail, and that
        // tail still has to land where its absolute position says it does.
        int skip = Math.max(0, length - REWIND_BYTES);
        int keep = length - skip;
        int start = (int) ((streamPosition + skip) % REWIND_BYTES);
        int firstChunk = Math.min(keep, REWIND_BYTES - start);
        System.arraycopy(buffer, offset + skip, rewind, start, firstChunk);
        if (firstChunk < keep) {
            System.arraycopy(buffer, offset + skip + firstChunk, rewind, 0, keep - firstChunk);
        }
    }

    @Override
    public Uri getUri() {
        return uri;
    }

    @Override
    public void close() {
        // Deliberately does not touch the connection: the player closes and
        // reopens this source while the track is still playing, and tearing the
        // socket down here would end it early.
        transferEnded();
    }
}
