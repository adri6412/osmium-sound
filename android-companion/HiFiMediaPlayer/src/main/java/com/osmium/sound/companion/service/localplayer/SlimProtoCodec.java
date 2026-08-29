package com.osmium.sound.companion.service.localplayer;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/**
 * Wire format of SlimProto, the protocol Lyrion uses to drive its players.
 *
 * <p>The framing is asymmetric, which is the first thing to get wrong:
 * <ul>
 *   <li>client to server: 4-byte opcode, then a big-endian 32-bit length of what
 *       follows, then the payload;</li>
 *   <li>server to client: a big-endian 16-bit length, then the 4-byte opcode and
 *       the payload.</li>
 * </ul>
 * Every multi-byte number is big-endian (network order).
 *
 * <p>Deliberately free of Android imports: this is the part covered by unit
 * tests, which run on the JVM because the instrumented test source set is
 * disabled in this project.
 */
public final class SlimProtoCodec {

    /** Software player device id, the same one squeezelite reports. */
    public static final int DEVICE_ID_SQUEEZEPLAY = 12;

    /** Largest frame we are willing to read; real ones are a few hundred bytes. */
    public static final int MAX_FRAME_LENGTH = 4096;

    // Client to server.
    public static final String OP_HELO = "HELO";
    public static final String OP_STAT = "STAT";
    public static final String OP_BYE = "BYE!";
    public static final String OP_RESP = "RESP";
    public static final String OP_DSCO = "DSCO";
    public static final String OP_SETD = "SETD";

    // Server to client.
    public static final String OP_STRM = "strm";
    public static final String OP_AUDG = "audg";
    public static final String OP_AUDE = "aude";
    public static final String OP_SETD_IN = "setd";
    public static final String OP_SERV = "serv";
    public static final String OP_VERS = "vers";
    public static final String OP_CONT = "cont";

    // STAT event codes.
    public static final String STMc = "STMc"; // connected to the stream
    public static final String STMd = "STMd"; // decoder drained: send me the next track
    public static final String STMf = "STMf"; // flushed
    public static final String STMl = "STMl"; // buffer threshold reached, waiting for unpause
    public static final String STMn = "STMn"; // cannot decode this
    public static final String STMo = "STMo"; // output underrun
    public static final String STMp = "STMp"; // paused
    public static final String STMr = "STMr"; // resumed
    public static final String STMs = "STMs"; // track started playing
    public static final String STMt = "STMt"; // heartbeat / answer to strm 't'
    public static final String STMu = "STMu"; // underrun, end of playback

    // DSCO disconnect reasons, as the server understands them.
    public static final int DISCONNECT_OK = 0;
    public static final int DISCONNECT_LOCAL = 1;
    public static final int DISCONNECT_REMOTE = 2;
    public static final int DISCONNECT_UNREACHABLE = 3;
    public static final int DISCONNECT_TIMEOUT = 4;

    private static final int HELO_FIXED_LENGTH = 36;
    private static final int STAT_LENGTH = 53;

    private SlimProtoCodec() {
    }

    // ---------------------------------------------------------------- outgoing

    /**
     * Registers this player with the server. Capabilities are a comma-separated
     * list of codecs and flags; the server reads them at every HELO, so changing
     * them means reconnecting.
     *
     * @param reconnect sets the flag that tells the server this is the same
     *                  player coming back rather than a fresh one
     */
    public static byte[] encodeHelo(int deviceId, int revision, byte[] mac, byte[] uuid,
                                    long bytesReceived, boolean reconnect, String capabilities) {
        if (mac == null || mac.length != 6) throw new IllegalArgumentException("mac must be 6 bytes");
        if (uuid == null || uuid.length != 16) throw new IllegalArgumentException("uuid must be 16 bytes");
        byte[] caps = capabilities.getBytes(StandardCharsets.UTF_8);
        ByteArrayOutputStream out = new ByteArrayOutputStream(8 + HELO_FIXED_LENGTH + caps.length);
        DataOutputStream data = new DataOutputStream(out);
        try {
            data.write(ascii(OP_HELO));
            data.writeInt(HELO_FIXED_LENGTH + caps.length);
            data.writeByte(deviceId);
            data.writeByte(revision);
            data.write(mac);
            data.write(uuid);
            data.writeShort(reconnect ? 0x4000 : 0x0000);
            data.writeInt((int) (bytesReceived >>> 32));
            data.writeInt((int) (bytesReceived & 0xffffffffL));
            data.write(ascii("EN"));
            data.write(caps);
        } catch (IOException impossible) {
            throw new AssertionError(impossible);
        }
        return out.toByteArray();
    }

    /**
     * Player state report. The server drives its own clock off these, so the
     * caller passes the jiffies value it wants stamped rather than having one
     * read here, which also keeps the encoding deterministic for tests.
     */
    public static byte[] encodeStat(String event, PlaybackSnapshot s, long jiffies) {
        if (event.length() != 4) throw new IllegalArgumentException("event must be 4 chars");
        ByteArrayOutputStream out = new ByteArrayOutputStream(8 + STAT_LENGTH);
        DataOutputStream data = new DataOutputStream(out);
        try {
            data.write(ascii(OP_STAT));
            data.writeInt(STAT_LENGTH);
            data.write(ascii(event));
            data.writeByte(s.crlfCount);
            data.writeByte(0); // mas initialized
            data.writeByte(0); // mas mode
            data.writeInt((int) s.streamBufferSize);
            data.writeInt((int) s.streamBufferFullness);
            data.writeInt((int) (s.bytesReceived >>> 32));
            data.writeInt((int) (s.bytesReceived & 0xffffffffL));
            data.writeShort(s.signalStrength);
            data.writeInt((int) (jiffies & 0xffffffffL));
            data.writeInt((int) s.outputBufferSize);
            data.writeInt((int) s.outputBufferFullness);
            data.writeInt((int) s.elapsedSeconds());
            data.writeShort(0); // voltage
            data.writeInt((int) s.elapsedMilliseconds);
            data.writeInt((int) s.serverTimestamp);
            data.writeShort(s.errorCode);
        } catch (IOException impossible) {
            throw new AssertionError(impossible);
        }
        return out.toByteArray();
    }

    /**
     * Hands the stream's HTTP response headers back to the server, which parses
     * them for content type, duration and metadata. Skipping this leaves tracks
     * with missing information.
     */
    public static byte[] encodeResp(String responseHeaders) {
        return simplePacket(OP_RESP, responseHeaders.getBytes(StandardCharsets.UTF_8));
    }

    /** Tells the server the stream connection went away, and why. */
    public static byte[] encodeDsco(int reason) {
        return simplePacket(OP_DSCO, new byte[]{(byte) reason});
    }

    /** Answers a {@code setd} query, or confirms a value we changed ourselves. */
    public static byte[] encodeSetd(int id, String value) {
        byte[] text = value == null ? new byte[0] : value.getBytes(StandardCharsets.UTF_8);
        byte[] payload = new byte[1 + text.length];
        payload[0] = (byte) id;
        System.arraycopy(text, 0, payload, 1, text.length);
        return simplePacket(OP_SETD, payload);
    }

    /**
     * Leaves cleanly. Without it the server keeps showing the player as
     * connected until its own timeout expires.
     */
    public static byte[] encodeBye() {
        return simplePacket(OP_BYE, new byte[]{0});
    }

    private static byte[] simplePacket(String opcode, byte[] payload) {
        ByteArrayOutputStream out = new ByteArrayOutputStream(8 + payload.length);
        DataOutputStream data = new DataOutputStream(out);
        try {
            data.write(ascii(opcode));
            data.writeInt(payload.length);
            data.write(payload);
        } catch (IOException impossible) {
            throw new AssertionError(impossible);
        }
        return out.toByteArray();
    }

    // ---------------------------------------------------------------- incoming

    /**
     * Reads one server frame: 16-bit length, 4-byte opcode, payload.
     *
     * @throws EOFException when the server closed the connection
     * @throws IOException  on a length that cannot be right, which means we have
     *                      lost framing and must reconnect
     */
    public static SlimProtoMessages.Frame readFrame(DataInputStream in) throws IOException {
        int length = in.readUnsignedShort();
        if (length < 4 || length > MAX_FRAME_LENGTH) {
            throw new IOException("bogus frame length " + length);
        }
        byte[] frame = new byte[length];
        in.readFully(frame);
        String opcode = new String(frame, 0, 4, StandardCharsets.US_ASCII);
        return new SlimProtoMessages.Frame(opcode, Arrays.copyOfRange(frame, 4, length));
    }

    /** Parses a {@code strm} payload (opcode already stripped). */
    public static SlimProtoMessages.Strm parseStrm(byte[] p) {
        if (p.length < 24) throw new IllegalArgumentException("strm payload too short: " + p.length);
        return new SlimProtoMessages.Strm(
                (char) (p[0] & 0xff),
                (p[1] & 0xff) - '0',
                (char) (p[2] & 0xff),
                (char) (p[3] & 0xff),
                (char) (p[4] & 0xff),
                (char) (p[5] & 0xff),
                (char) (p[6] & 0xff),
                p[7] & 0xff,
                p[9] & 0xff,
                (p[10] & 0xff) - '0',
                p[11] & 0xff,
                p[12] & 0xff,
                readUInt32(p, 14),
                ((p[18] & 0xff) << 8) | (p[19] & 0xff),
                Arrays.copyOfRange(p, 20, 24),
                Arrays.copyOfRange(p, 24, p.length));
    }

    /** Parses an {@code audg} payload. The trailing sequence field is optional. */
    public static SlimProtoMessages.Audg parseAudg(byte[] p) {
        if (p.length < 18) throw new IllegalArgumentException("audg payload too short: " + p.length);
        return new SlimProtoMessages.Audg(
                readUInt32(p, 10),
                readUInt32(p, 14),
                p[8] != 0,
                p[9] & 0xff);
    }

    /** Parses an {@code aude} payload. */
    public static SlimProtoMessages.Aude parseAude(byte[] p) {
        if (p.length < 2) throw new IllegalArgumentException("aude payload too short: " + p.length);
        return new SlimProtoMessages.Aude(p[0] != 0, p[1] != 0);
    }

    /**
     * Parses a {@code setd} payload. A payload of just the id is the server
     * asking for the value; anything longer is the server setting it.
     */
    public static SlimProtoMessages.Setd parseSetd(byte[] p) {
        if (p.length < 1) throw new IllegalArgumentException("setd payload too short");
        int id = p[0] & 0xff;
        if (p.length == 1) return new SlimProtoMessages.Setd(id, null);
        return new SlimProtoMessages.Setd(id, new String(p, 1, p.length - 1, StandardCharsets.UTF_8).trim());
    }

    /** Parses a {@code serv} payload, whose optional tail is a sync group id. */
    public static SlimProtoMessages.Serv parseServ(byte[] p) {
        if (p.length < 4) throw new IllegalArgumentException("serv payload too short: " + p.length);
        String syncGroup = p.length > 4
                ? new String(p, 4, p.length - 4, StandardCharsets.UTF_8).trim()
                : null;
        return new SlimProtoMessages.Serv(Arrays.copyOfRange(p, 0, 4), syncGroup);
    }

    // ------------------------------------------------------------------ shared

    /** Milliseconds since boot, truncated to 32 bits, as the server expects. */
    public static long jiffies() {
        return System.nanoTime() / 1_000_000L;
    }

    static long readUInt32(byte[] b, int offset) {
        return ((long) (b[offset] & 0xff) << 24)
                | ((long) (b[offset + 1] & 0xff) << 16)
                | ((long) (b[offset + 2] & 0xff) << 8)
                | (b[offset + 3] & 0xff);
    }

    private static byte[] ascii(String s) {
        return s.getBytes(StandardCharsets.US_ASCII);
    }
}
