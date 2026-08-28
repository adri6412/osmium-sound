package com.osmium.sound.companion.service.localplayer;

import android.util.Log;

import androidx.annotation.Nullable;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;

/**
 * One audio stream, fetched the way SlimProto expects.
 *
 * <p>The server hands us a complete HTTP request in the {@code strm} command and
 * we send it back verbatim: it is HTTP/1.0, frequently without a {@code Host}
 * header, and its query string carries server-side state. Rebuilding it with a
 * general-purpose HTTP client is how you end up with streams that work on one
 * Lyrion version and not the next.
 *
 * <p>A reader thread fills a fixed ring buffer and blocks when it is full, which
 * is what gives the server an honest {@code fullness} to look at: TCP back
 * pressure keeps the buffer genuinely full during playback instead of letting
 * the player race ahead and report zero.
 */
final class SlimStreamConnection implements SlimStream {

    private static final String TAG = "SlimStream";

    /** Same order of magnitude as the reference player's stream buffer. */
    private static final int RING_SIZE = 2 * 1024 * 1024;
    private static final int CONNECT_TIMEOUT_MS = 5000;
    private static final int READ_TIMEOUT_MS = 30000;
    private static final int MAX_HEADER_BYTES = 16 * 1024;

    interface Callback {
        /** The stream's response headers, which the server wants back as RESP. */
        void onStreamHeaders(SlimStreamConnection connection, String headers);

        /**
         * The FLAC stream header seen at the start of this track, so it can be
         * put back in front of a later stream that arrives without one.
         */
        void onFlacHeader(byte[] header);

        /** The socket delivered its last byte. */
        void onStreamSocketClosed(SlimStreamConnection connection);

        /** The stream failed; the reason is one of the DSCO codes. */
        void onStreamError(SlimStreamConnection connection, int disconnectReason);
    }

    private final InetAddress address;
    private final int port;
    private final byte[] request;
    private final PlaybackSnapshot snapshot;
    private final Callback callback;

    private final byte[] ring = new byte[RING_SIZE];
    private final Object lock = new Object();
    private int head;
    private int tail;
    private int count;

    private volatile boolean closed;
    private volatile boolean socketEnded;
    private volatile long bytesReceived;

    @Nullable
    private Socket socket;
    @Nullable
    private Thread reader;
    @Nullable
    private String authorization;
    @Nullable
    private byte[] flacPreamble;
    private boolean bodyStarted;

    SlimStreamConnection(InetAddress address, int port, byte[] request, PlaybackSnapshot snapshot,
                         Callback callback) {
        this.address = address;
        this.port = port;
        this.request = request;
        this.snapshot = snapshot;
        this.callback = callback;
    }

    /**
     * Credentials to retry with if the server answers 401. Lyrion normally lets
     * players through on their MAC, but a password-protected server may not.
     */
    void setAuthorization(@Nullable String basicAuthorization) {
        this.authorization = basicAuthorization;
    }

    /**
     * The FLAC header from earlier in this track. Lyrion answers a seek by
     * carrying on the transcode mid-stream: the body then starts on a frame,
     * with no "fLaC" marker and no stream info, and a decoder that has not seen
     * the header refuses it. Handing the header back first turns that into an
     * ordinary stream again.
     */
    void setFlacPreamble(@Nullable byte[] preamble) {
        this.flacPreamble = preamble;
    }

    /** Connects and starts filling the buffer. Returns once headers are in. */
    void open() throws IOException {
        Socket newSocket = new Socket();
        newSocket.connect(new InetSocketAddress(address, port), CONNECT_TIMEOUT_MS);
        newSocket.setSoTimeout(READ_TIMEOUT_MS);
        newSocket.setTcpNoDelay(true);
        socket = newSocket;

        OutputStream out = newSocket.getOutputStream();
        out.write(request);
        out.flush();

        InputStream in = newSocket.getInputStream();
        String headers = readHeaders(in);
        if (headers == null) throw new IOException("stream closed before headers arrived");

        if (isUnauthorised(headers) && authorization != null) {
            Log.i(TAG, "stream needs authentication, retrying with credentials");
            closeSocketQuietly();
            newSocket = new Socket();
            newSocket.connect(new InetSocketAddress(address, port), CONNECT_TIMEOUT_MS);
            newSocket.setSoTimeout(READ_TIMEOUT_MS);
            newSocket.setTcpNoDelay(true);
            socket = newSocket;
            out = newSocket.getOutputStream();
            out.write(withAuthorization(request, authorization));
            out.flush();
            in = newSocket.getInputStream();
            headers = readHeaders(in);
            if (headers == null) throw new IOException("stream closed before headers arrived");
        }

        // Whatever comes back that is not a 2xx is an error page, not audio.
        // Feeding it to the decoder produces a baffling "malformed container"
        // instead of the plain truth, which is that the server refused.
        int status = statusCode(headers);
        Log.i(TAG, "stream response " + status + " from " + address.getHostAddress() + ":" + port);
        if (status < 200 || status > 299) {
            throw new IOException("the server answered " + status + " for this stream");
        }

        callback.onStreamHeaders(this, headers);

        final InputStream body = in;
        reader = new Thread(() -> fill(body), "slimproto-stream");
        reader.start();
    }

    /**
     * Reads the response head. Only the headers are consumed here; whatever the
     * socket delivers after the blank line belongs to the audio.
     */
    @Nullable
    private String readHeaders(InputStream in) throws IOException {
        ByteArrayOutputStream head = new ByteArrayOutputStream(512);
        int crlf = 0;
        while (head.size() < MAX_HEADER_BYTES) {
            int b = in.read();
            if (b == -1) return null;
            head.write(b);
            if (b == '\n') {
                crlf++;
                if (crlf == 2) break;
            } else if (b != '\r') {
                crlf = 0;
            }
        }
        snapshot.crlfCount = crlf;
        return head.toString("UTF-8");
    }

    private static boolean isUnauthorised(String headers) {
        return statusCode(headers) == 401;
    }

    /** The status code from the response's first line, or -1 if unreadable. */
    private static int statusCode(String headers) {
        int end = headers.indexOf('\n');
        String statusLine = (end > 0 ? headers.substring(0, end) : headers).trim();
        String[] parts = statusLine.split(" ");
        if (parts.length < 2) return -1;
        try {
            return Integer.parseInt(parts[1]);
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    private static byte[] withAuthorization(byte[] request, String authorization) {
        String text = new String(request, StandardCharsets.UTF_8);
        String header = "Authorization: Basic " + authorization + "\r\n";
        int blankLine = text.indexOf("\r\n\r\n");
        String patched = blankLine >= 0
                ? text.substring(0, blankLine + 2) + header + text.substring(blankLine + 2)
                : text + header;
        return patched.getBytes(StandardCharsets.UTF_8);
    }

    private void fill(InputStream in) {
        byte[] chunk = new byte[32 * 1024];
        int reason = SlimProtoCodec.DISCONNECT_OK;
        try {
            while (!closed) {
                int free;
                synchronized (lock) {
                    while (!closed && count == ring.length) {
                        lock.wait();   // buffer full: let TCP hold the server back
                    }
                    if (closed) break;
                    free = ring.length - count;
                }
                int read = in.read(chunk, 0, Math.min(chunk.length, free));
                if (read == -1) break;
                append(chunk, read);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            reason = SlimProtoCodec.DISCONNECT_LOCAL;
        } catch (IOException e) {
            if (!closed) {
                Log.i(TAG, "stream read failed: " + e.getMessage());
                reason = SlimProtoCodec.DISCONNECT_REMOTE;
            }
        }

        synchronized (lock) {
            socketEnded = true;
            lock.notifyAll();
        }
        if (closed) return;
        if (reason == SlimProtoCodec.DISCONNECT_OK) {
            callback.onStreamSocketClosed(this);
        } else {
            callback.onStreamError(this, reason);
        }
    }

    private void append(byte[] chunk, int length) {
        if (!bodyStarted && length >= 4) {
            bodyStarted = true;
            boolean hasMarker = chunk[0] == 'f' && chunk[1] == 'L' && chunk[2] == 'a' && chunk[3] == 'C';
            if (hasMarker) {
                byte[] header = readFlacHeader(chunk, length);
                if (header != null) callback.onFlacHeader(header);
            } else if (flacPreamble != null) {
                Log.i(TAG, "stream starts mid-FLAC after a seek: putting the header back");
                appendBytes(flacPreamble, flacPreamble.length);
            }
        }
        appendBytes(chunk, length);
    }

    /**
     * Copies out the "fLaC" marker and the metadata blocks that follow it, up to
     * the first audio frame. Returns null if the chunk does not hold all of it,
     * which in practice does not happen: the header is a few hundred bytes and
     * the first read is tens of kilobytes.
     */
    @Nullable
    private static byte[] readFlacHeader(byte[] chunk, int length) {
        int pos = 4;
        while (pos + 4 <= length) {
            boolean last = (chunk[pos] & 0x80) != 0;
            int blockSize = ((chunk[pos + 1] & 0xff) << 16)
                    | ((chunk[pos + 2] & 0xff) << 8)
                    | (chunk[pos + 3] & 0xff);
            pos += 4 + blockSize;
            if (last) {
                return pos <= length ? java.util.Arrays.copyOf(chunk, pos) : null;
            }
        }
        return null;
    }

    private void appendBytes(byte[] chunk, int length) {
        synchronized (lock) {
            for (int i = 0; i < length; i++) {
                ring[tail] = chunk[i];
                tail = (tail + 1) % ring.length;
            }
            count += length;
            bytesReceived += length;
            snapshot.bytesReceived = bytesReceived;
            snapshot.streamBufferFullness = count;
            snapshot.streamBufferSize = ring.length;
            lock.notifyAll();
        }
    }

    /**
     * Blocking read for the decoder. Returns -1 once the socket has ended and
     * the buffer is drained, which is the moment the server is waiting for to
     * hand us the next track.
     */
    @Override
    public int read(byte[] buffer, int offset, int length) throws IOException {
        synchronized (lock) {
            while (count == 0) {
                if (closed) throw new IOException("stream closed");
                if (socketEnded) return -1;
                try {
                    lock.wait();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new IOException("interrupted while waiting for stream data");
                }
            }
            int toRead = Math.min(length, count);
            for (int i = 0; i < toRead; i++) {
                buffer[offset + i] = ring[head];
                head = (head + 1) % ring.length;
            }
            count -= toRead;
            snapshot.streamBufferFullness = count;
            lock.notifyAll();
            return toRead;
        }
    }

    /** Bytes pulled off the socket so far, for the STAT report. */
    long bytesReceived() {
        return bytesReceived;
    }

    /** True once the server has sent everything it was going to send. */
    boolean isSocketEnded() {
        return socketEnded;
    }

    void close() {
        closed = true;
        synchronized (lock) {
            count = 0;
            snapshot.streamBufferFullness = 0;
            lock.notifyAll();
        }
        closeSocketQuietly();
    }

    private void closeSocketQuietly() {
        Socket current = socket;
        socket = null;
        if (current == null) return;
        try {
            current.close();
        } catch (IOException ignored) {
            // Already broken; nothing useful to do.
        }
    }
}
