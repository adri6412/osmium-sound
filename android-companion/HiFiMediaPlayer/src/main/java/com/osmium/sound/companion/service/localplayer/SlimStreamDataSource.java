package com.osmium.sound.companion.service.localplayer;

import android.net.Uri;

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
 * <p>Deliberately single use: the socket behind it has already been consumed, so
 * a retry would produce silence rather than a second chance. The player is
 * configured with no retries to match, and a failure is reported to the server
 * instead of being papered over.
 */
@OptIn(markerClass = UnstableApi.class)
final class SlimStreamDataSource extends BaseDataSource {

    /** Called once, when the decoder has been handed every byte of the track. */
    interface EndOfInputListener {
        void onEndOfInput();
    }

    private final SlimStreamConnection connection;
    private final EndOfInputListener endOfInputListener;
    private final AtomicBoolean endOfInputReported = new AtomicBoolean();

    private Uri uri;
    private boolean opened;

    private SlimStreamDataSource(SlimStreamConnection connection, EndOfInputListener listener) {
        super(/* isNetwork= */ true);
        this.connection = connection;
        this.endOfInputListener = listener;
    }

    /** A factory that hands out this one source, and refuses to do it twice. */
    static DataSource.Factory factory(SlimStreamConnection connection, EndOfInputListener listener) {
        SlimStreamDataSource source = new SlimStreamDataSource(connection, listener);
        AtomicBoolean handedOut = new AtomicBoolean();
        return () -> {
            if (!handedOut.compareAndSet(false, true)) {
                throw new IllegalStateException("this stream has already been consumed");
            }
            return source;
        };
    }

    @Override
    public long open(DataSpec dataSpec) throws IOException {
        if (opened) throw new IOException("this stream has already been opened");
        opened = true;
        uri = dataSpec.uri;
        transferInitializing(dataSpec);
        transferStarted(dataSpec);
        // The server streams; there is no length and no seeking within it. Seeks
        // travel the other way, as a new strm from Lyrion.
        return C.LENGTH_UNSET;
    }

    @Override
    public int read(byte[] buffer, int offset, int length) throws IOException {
        if (length == 0) return 0;
        int read = connection.read(buffer, offset, length);
        if (read == -1) {
            if (endOfInputReported.compareAndSet(false, true)) {
                endOfInputListener.onEndOfInput();
            }
            return C.RESULT_END_OF_INPUT;
        }
        bytesTransferred(read);
        return read;
    }

    @Override
    public Uri getUri() {
        return uri;
    }

    @Override
    public void close() {
        if (!opened) return;
        opened = false;
        transferEnded();
    }
}
