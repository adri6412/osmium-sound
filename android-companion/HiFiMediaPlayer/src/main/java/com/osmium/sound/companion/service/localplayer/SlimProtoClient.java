package com.osmium.sound.companion.service.localplayer;

import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;

import androidx.annotation.Nullable;

import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;

/**
 * Keeps a SlimProto session with Lyrion: connects, says HELO, then serves the
 * server's commands and reports back with STAT.
 *
 * <p>Two threads are involved. A reader thread does nothing but block on the
 * socket and hand frames over; everything else — the handshake, command
 * dispatch, outgoing packets, the heartbeat and reconnection — runs on the
 * "slimproto" handler thread, so protocol state needs no locking. Listener
 * callbacks arrive on that same thread.
 */
public class SlimProtoClient {

    private static final String TAG = "SlimProtoClient";

    /** The port Lyrion listens on for players. */
    public static final int PORT = 3483;

    private static final int CONNECT_TIMEOUT_MS = 5000;
    /** Long enough to notice a silent server, short enough to reconnect early. */
    private static final int READ_TIMEOUT_MS = 60000;
    private static final long HEARTBEAT_MS = 1000;
    private static final long[] BACKOFF_MS = {1000, 2000, 4000, 8000, 15000, 30000};

    /** Server commands, delivered on the protocol thread. */
    public interface Listener {
        /** The socket is up and HELO has gone out. */
        void onRegistered();

        /** The session ended; a reconnection may already be scheduled. */
        void onDisconnected(boolean willRetry);

        void onStrm(SlimProtoMessages.Strm strm);

        void onAudg(SlimProtoMessages.Audg audg);

        void onAude(SlimProtoMessages.Aude aude);

        void onSetd(SlimProtoMessages.Setd setd);

        void onServ(SlimProtoMessages.Serv serv);
    }

    private final String host;
    private final int port;
    private final LocalPlayerIdentity identity;
    private final PlaybackSnapshot snapshot;
    private final Listener listener;

    private final HandlerThread protocolThread;
    private final Handler protocol;

    private volatile String capabilities;
    private volatile boolean running;
    private volatile boolean registered;
    private volatile boolean heartbeatEnabled;

    @Nullable
    private Socket socket;
    @Nullable
    private DataOutputStream out;
    @Nullable
    private Thread reader;
    @Nullable
    private InetAddress serverAddress;

    private int backoff;
    private boolean everRegistered;
    private long streamBytesTotal;

    public SlimProtoClient(String host, int port, LocalPlayerIdentity identity,
                           PlaybackSnapshot snapshot, String capabilities, Listener listener) {
        this.host = host;
        this.port = port;
        this.identity = identity;
        this.snapshot = snapshot;
        this.capabilities = capabilities;
        this.listener = listener;
        this.protocolThread = new HandlerThread("slimproto");
        this.protocolThread.start();
        this.protocol = new Handler(protocolThread.getLooper());
    }

    // ------------------------------------------------------------- lifecycle

    public void start() {
        running = true;
        protocol.post(this::connect);
    }

    /** Says goodbye and tears the session down. Safe to call more than once. */
    public void stop() {
        running = false;
        protocol.post(() -> {
            if (registered) {
                writePacket(SlimProtoCodec.encodeBye());
            }
            closeSocket();
            protocolThread.quitSafely();
        });
    }

    public boolean isRegistered() {
        return registered;
    }

    /** Address of the server we are talking to; the stream defaults to it. */
    @Nullable
    public InetAddress serverAddress() {
        return serverAddress;
    }

    public String host() {
        return host;
    }

    /**
     * Replaces the capability list and reconnects, which is the only way to tell
     * the server about a different set of formats: it reads them at HELO time.
     * The same MAC comes back as the same player, so the playlist survives.
     */
    public void setCapabilities(String capabilities) {
        if (capabilities.equals(this.capabilities)) return;
        this.capabilities = capabilities;
        protocol.post(() -> {
            if (!running) return;
            Log.i(TAG, "capabilities changed, re-registering");
            closeSocket();
            protocol.post(this::connect);
        });
    }

    /** Sends an unsolicited STMt every second while audio is being rendered. */
    public void setHeartbeatEnabled(boolean enabled) {
        if (heartbeatEnabled == enabled) return;
        heartbeatEnabled = enabled;
        protocol.post(() -> {
            protocol.removeCallbacks(heartbeat);
            if (heartbeatEnabled) protocol.postDelayed(heartbeat, HEARTBEAT_MS);
        });
    }

    private final Runnable heartbeat = new Runnable() {
        @Override
        public void run() {
            if (!running || !heartbeatEnabled) return;
            if (registered) sendStat(SlimProtoCodec.STMt);
            protocol.postDelayed(this, HEARTBEAT_MS);
        }
    };

    // ------------------------------------------------------------ connection

    private void connect() {
        if (!running) return;
        closeSocket();

        Socket newSocket = new Socket();
        try {
            newSocket.connect(new InetSocketAddress(host, port), CONNECT_TIMEOUT_MS);
            newSocket.setTcpNoDelay(true);
            newSocket.setSoTimeout(READ_TIMEOUT_MS);
            socket = newSocket;
            serverAddress = newSocket.getInetAddress();
            out = new DataOutputStream(new BufferedOutputStream(newSocket.getOutputStream(), 512));

            writePacket(SlimProtoCodec.encodeHelo(SlimProtoCodec.DEVICE_ID_SQUEEZEPLAY, 0,
                    identity.mac(), identity.uuid(), streamBytesTotal, everRegistered, capabilities));

            registered = true;
            everRegistered = true;
            backoff = 0;
            Log.i(TAG, "registered with " + host + ":" + port + " as " + identity.macString());

            DataInputStream in = new DataInputStream(newSocket.getInputStream());
            reader = new Thread(() -> readLoop(newSocket, in), "slimproto-reader");
            reader.start();

            listener.onRegistered();
            if (heartbeatEnabled) protocol.postDelayed(heartbeat, HEARTBEAT_MS);
        } catch (IOException e) {
            Log.i(TAG, "connect to " + host + ":" + port + " failed: " + e.getMessage());
            closeQuietly(newSocket);
            scheduleReconnect();
        }
    }

    private void readLoop(Socket ownSocket, DataInputStream in) {
        try {
            while (running && !ownSocket.isClosed()) {
                SlimProtoMessages.Frame frame = SlimProtoCodec.readFrame(in);
                protocol.post(() -> dispatch(frame));
            }
        } catch (IOException e) {
            if (running) Log.i(TAG, "connection lost: " + e.getMessage());
        }
        protocol.post(() -> {
            // Ignore a reader that belongs to a session we have already replaced.
            if (socket != ownSocket) return;
            onConnectionLost();
        });
    }

    private void onConnectionLost() {
        boolean wasRegistered = registered;
        registered = false;
        closeSocket();
        boolean willRetry = running;
        if (wasRegistered) listener.onDisconnected(willRetry);
        if (willRetry) scheduleReconnect();
    }

    private void scheduleReconnect() {
        if (!running) return;
        long delay = BACKOFF_MS[Math.min(backoff, BACKOFF_MS.length - 1)];
        backoff++;
        Log.i(TAG, "reconnecting in " + delay + "ms");
        protocol.postDelayed(this::connect, delay);
    }

    private void closeSocket() {
        registered = false;
        protocol.removeCallbacks(heartbeat);
        Socket current = socket;
        socket = null;
        out = null;
        closeQuietly(current);
    }

    private static void closeQuietly(@Nullable Socket socket) {
        if (socket == null) return;
        try {
            socket.close();
        } catch (IOException ignored) {
            // Closing a socket that is already broken is not news.
        }
    }

    // -------------------------------------------------------------- dispatch

    private void dispatch(SlimProtoMessages.Frame frame) {
        if (!running) return;
        try {
            switch (frame.opcode) {
                case SlimProtoCodec.OP_STRM:
                    listener.onStrm(SlimProtoCodec.parseStrm(frame.payload));
                    break;
                case SlimProtoCodec.OP_AUDG:
                    listener.onAudg(SlimProtoCodec.parseAudg(frame.payload));
                    break;
                case SlimProtoCodec.OP_AUDE:
                    listener.onAude(SlimProtoCodec.parseAude(frame.payload));
                    break;
                case SlimProtoCodec.OP_SETD_IN:
                    listener.onSetd(SlimProtoCodec.parseSetd(frame.payload));
                    break;
                case SlimProtoCodec.OP_SERV:
                    listener.onServ(SlimProtoCodec.parseServ(frame.payload));
                    break;
                case SlimProtoCodec.OP_VERS:
                    Log.i(TAG, "server version " + new String(frame.payload).trim());
                    break;
                default:
                    // Display, IR and the rest of the hardware-player surface:
                    // nothing a phone needs to answer.
                    Log.d(TAG, "ignoring " + frame.opcode);
                    break;
            }
        } catch (IllegalArgumentException e) {
            Log.w(TAG, "malformed " + frame.opcode + ": " + e.getMessage());
        }
    }

    // -------------------------------------------------------------- outgoing

    /** Reports player state. The server runs its own clock off these. */
    public void sendStat(String event) {
        protocol.post(() -> {
            if (!registered) return;
            writePacket(SlimProtoCodec.encodeStat(event, snapshot, SlimProtoCodec.jiffies()));
        });
    }

    /** Answers a strm 't' by echoing the timestamp the server sent us. */
    public void sendStatusAnswer(long serverTimestamp) {
        protocol.post(() -> {
            if (!registered) return;
            snapshot.serverTimestamp = serverTimestamp;
            writePacket(SlimProtoCodec.encodeStat(SlimProtoCodec.STMt, snapshot, SlimProtoCodec.jiffies()));
            snapshot.serverTimestamp = 0;
        });
    }

    /**
     * Hands the stream's HTTP response headers to the server, which parses them
     * for content type, duration and stream metadata.
     */
    public void sendResp(String responseHeaders) {
        protocol.post(() -> {
            if (!registered) return;
            writePacket(SlimProtoCodec.encodeResp(responseHeaders));
        });
    }

    public void sendDsco(int reason) {
        protocol.post(() -> {
            if (!registered) return;
            writePacket(SlimProtoCodec.encodeDsco(reason));
        });
    }

    public void sendSetd(int id, String value) {
        protocol.post(() -> {
            if (!registered) return;
            writePacket(SlimProtoCodec.encodeSetd(id, value));
        });
    }

    /** Remembers total bytes streamed, which HELO reports on reconnection. */
    public void addStreamBytes(long bytes) {
        streamBytesTotal += bytes;
    }

    private void writePacket(byte[] packet) {
        DataOutputStream stream = out;
        if (stream == null) return;
        try {
            stream.write(packet);
            stream.flush();
        } catch (IOException e) {
            Log.i(TAG, "write failed: " + e.getMessage());
            onConnectionLost();
        }
    }
}
