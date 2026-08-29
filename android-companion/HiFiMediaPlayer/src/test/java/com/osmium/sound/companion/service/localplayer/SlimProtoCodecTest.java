package com.osmium.sound.companion.service.localplayer;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/**
 * Byte-level checks on the SlimProto wire format, compared against the layouts
 * in the reference player (squeezelite's slimproto.h). A field at the wrong
 * offset produces a player that registers and then behaves inexplicably rather
 * than one that fails loudly, so these are worth being pedantic about.
 */
public class SlimProtoCodecTest {

    private static final byte[] MAC = {0x02, (byte) 0xec, (byte) 0xa2, (byte) 0xcd, 0x27, 0x39};
    private static final byte[] UUID = new byte[16];

    static {
        for (int i = 0; i < UUID.length; i++) UUID[i] = (byte) i;
    }

    // ----------------------------------------------------------------- framing

    @Test
    public void clientPacketsCarryOpcodeThenLength() {
        byte[] bye = SlimProtoCodec.encodeBye();

        assertEquals("BYE!", ascii(bye, 0, 4));
        assertEquals("length counts only the payload", 1, readInt(bye, 4));
        assertEquals(9, bye.length);
        assertEquals(0, bye[8]);
    }

    @Test
    public void serverFramesCarryTwoByteLength() throws IOException {
        byte[] payload = strmPayload('t', "");
        ByteArrayOutputStream wire = new ByteArrayOutputStream();
        wire.write(0x00);
        wire.write(4 + payload.length);
        wire.write("strm".getBytes(StandardCharsets.US_ASCII), 0, 4);
        wire.write(payload, 0, payload.length);

        SlimProtoMessages.Frame frame = SlimProtoCodec.readFrame(
                new DataInputStream(new ByteArrayInputStream(wire.toByteArray())));

        assertEquals("strm", frame.opcode);
        assertArrayEquals(payload, frame.payload);
    }

    @Test
    public void impossibleFrameLengthIsRejected() {
        // Losing framing has to fail loudly: reading an absurd length would park
        // the reader thread on a socket that will never deliver that many bytes.
        byte[] wire = {(byte) 0xff, (byte) 0xff, 's', 't', 'r', 'm'};
        try {
            SlimProtoCodec.readFrame(new DataInputStream(new ByteArrayInputStream(wire)));
            fail("expected the oversized frame to be rejected");
        } catch (IOException expected) {
            assertTrue(expected.getMessage().contains("65535"));
        }
    }

    // -------------------------------------------------------------------- HELO

    @Test
    public void heloHasTheExpectedLayout() {
        String caps = "Model=squeezelite,mp3";
        byte[] helo = SlimProtoCodec.encodeHelo(SlimProtoCodec.DEVICE_ID_SQUEEZEPLAY, 0,
                MAC, UUID, 0L, false, caps);

        assertEquals("HELO", ascii(helo, 0, 4));
        assertEquals(36 + caps.length(), readInt(helo, 4));
        assertEquals(8 + 36 + caps.length(), helo.length);
        assertEquals(12, helo[8] & 0xff);   // device id: squeezeplay
        assertEquals(0, helo[9] & 0xff);    // revision
        assertArrayEquals(MAC, Arrays.copyOfRange(helo, 10, 16));
        assertArrayEquals(UUID, Arrays.copyOfRange(helo, 16, 32));
        assertEquals(0x0000, readShort(helo, 32));
        assertEquals(0L, readLong(helo, 34));
        assertEquals("EN", ascii(helo, 42, 2));
        assertEquals(caps, ascii(helo, 44, caps.length()));
    }

    @Test
    public void reconnectIsFlaggedInTheChannelList() {
        byte[] helo = SlimProtoCodec.encodeHelo(12, 0, MAC, UUID, 1234L, true, "mp3");

        assertEquals(0x4000, readShort(helo, 32));
        assertEquals(1234L, readLong(helo, 34));
    }

    @Test
    public void bytesReceivedIsSplitAcrossTwoWords() {
        long total = 0x0000000123456789L;

        byte[] helo = SlimProtoCodec.encodeHelo(12, 0, MAC, UUID, total, false, "mp3");

        assertEquals(0x00000001L, readInt(helo, 34) & 0xffffffffL);
        assertEquals(0x23456789L, readInt(helo, 38) & 0xffffffffL);
        assertEquals(total, readLong(helo, 34));
    }

    // -------------------------------------------------------------------- STAT

    @Test
    public void statHasTheExpectedLayout() {
        PlaybackSnapshot snapshot = new PlaybackSnapshot();
        snapshot.streamBufferSize = 2 * 1024 * 1024;
        snapshot.streamBufferFullness = 1024;
        snapshot.bytesReceived = 0x0000000200000003L;
        snapshot.outputBufferSize = 3528000;
        snapshot.outputBufferFullness = 176400;
        snapshot.elapsedMilliseconds = 65432;
        snapshot.serverTimestamp = 0xdeadbeefL;

        byte[] stat = SlimProtoCodec.encodeStat(SlimProtoCodec.STMt, snapshot, 999L);

        assertEquals("STAT", ascii(stat, 0, 4));
        assertEquals(53, readInt(stat, 4));
        assertEquals(61, stat.length);
        assertEquals("STMt", ascii(stat, 8, 4));
        assertEquals(0, stat[12] & 0xff);                       // crlf count
        assertEquals(2 * 1024 * 1024, readInt(stat, 15));       // stream buffer size
        assertEquals(1024, readInt(stat, 19));                  // stream buffer fullness
        assertEquals(2, readInt(stat, 23));                     // bytes received, high word
        assertEquals(3, readInt(stat, 27));                     // bytes received, low word
        assertEquals(0xFFFF, readShort(stat, 31));              // signal strength: wired
        assertEquals(999, readInt(stat, 33));                   // jiffies
        assertEquals(3528000, readInt(stat, 37));               // output buffer size
        assertEquals(176400, readInt(stat, 41));                // output buffer fullness
        assertEquals(65, readInt(stat, 45));                    // elapsed seconds
        assertEquals(0, readShort(stat, 49));                   // voltage
        assertEquals(65432, readInt(stat, 51));                 // elapsed milliseconds
        assertEquals(0xdeadbeefL, readInt(stat, 55) & 0xffffffffL);
        assertEquals(0, readShort(stat, 59));                   // error code
    }

    @Test
    public void elapsedSecondsFollowsMilliseconds() {
        PlaybackSnapshot snapshot = new PlaybackSnapshot();
        snapshot.elapsedMilliseconds = 1999;

        assertEquals(1, snapshot.elapsedSeconds());
    }

    // -------------------------------------------------------------------- strm

    @Test
    public void strmStartIsParsedFieldByField() {
        String header = "GET /stream.mp3?player=02%3Aec HTTP/1.0";
        byte[] payload = strmPayload('s', header);
        payload[1] = '1';           // autostart: start once buffered
        payload[2] = 'f';           // flac
        payload[7] = 20;            // threshold, KB
        payload[9] = 3;             // transition period, seconds
        payload[10] = '1';          // crossfade
        payload[12] = 10;           // output threshold, tenths of a second
        writeInt(payload, 14, 0x00010000);
        payload[18] = 0x23;         // port 9000
        payload[19] = 0x28;
        payload[20] = (byte) 192;
        payload[21] = (byte) 168;
        payload[22] = 0;
        payload[23] = (byte) 133;

        SlimProtoMessages.Strm strm = SlimProtoCodec.parseStrm(payload);

        assertEquals('s', strm.command);
        assertEquals(1, strm.autostart);
        assertEquals('f', strm.format);
        assertEquals(20, strm.thresholdKb);
        assertEquals(3, strm.transitionPeriod);
        assertEquals(1, strm.transitionType);
        assertEquals(10, strm.outputThreshold);
        assertEquals(0x00010000L, strm.replayGain);
        assertEquals(9000, strm.serverPort);
        assertEquals("192.168.0.133", strm.serverIpString());
        assertFalse(strm.useControlServer());
        assertEquals(header, new String(strm.httpHeader, StandardCharsets.UTF_8));
    }

    @Test
    public void allZeroServerAddressMeansTheControlServer() {
        SlimProtoMessages.Strm strm = SlimProtoCodec.parseStrm(strmPayload('s', "GET / HTTP/1.0"));

        assertTrue(strm.useControlServer());
    }

    @Test
    public void statusRequestCarriesTheTimestampToEcho() {
        byte[] payload = strmPayload('t', "");
        writeInt(payload, 14, 0x12345678);

        SlimProtoMessages.Strm strm = SlimProtoCodec.parseStrm(payload);

        assertEquals('t', strm.command);
        assertEquals(0x12345678L, strm.replayGain);
        assertEquals(0, strm.httpHeader.length);
    }

    // -------------------------------------------------------------- audg, aude

    @Test
    public void gainIsSixteenPointSixteen() {
        assertEquals(1.0f, audg(0x00010000, 0x00010000, true).linearGain(), 0.0001f);
        assertEquals(0.5f, audg(0x00008000, 0x00008000, true).linearGain(), 0.0001f);
        assertEquals(0.0f, audg(0, 0, true).linearGain(), 0.0001f);
    }

    @Test
    public void gainAboveUnityIsClamped() {
        // The server's preamp can push the gain past 1.0; handing that straight
        // to the output would clip.
        assertEquals(1.0f, audg(0x00020000, 0x00020000, true).linearGain(), 0.0001f);
    }

    @Test
    public void withoutDigitalVolumeControlThePlayerDoesNotAttenuate() {
        assertEquals(1.0f, audg(0x00008000, 0x00008000, false).linearGain(), 0.0001f);
    }

    @Test
    public void audeReportsDacState() {
        assertTrue(SlimProtoCodec.parseAude(new byte[]{0, 1}).dac);
        assertFalse(SlimProtoCodec.parseAude(new byte[]{0, 0}).dac);
    }

    // -------------------------------------------------------------- setd, serv

    @Test
    public void setdWithoutAValueIsAQuery() {
        SlimProtoMessages.Setd setd = SlimProtoCodec.parseSetd(new byte[]{0});

        assertTrue(setd.isQuery());
        assertEquals(SlimProtoMessages.Setd.ID_PLAYER_NAME, setd.id);
        assertNull(setd.value);
    }

    @Test
    public void setdWithAValueIsARename() {
        byte[] payload = concat(new byte[]{0}, "Pixel 8".getBytes(StandardCharsets.UTF_8));

        SlimProtoMessages.Setd setd = SlimProtoCodec.parseSetd(payload);

        assertFalse(setd.isQuery());
        assertEquals("Pixel 8", setd.value);
    }

    @Test
    public void setdRoundTrips() {
        byte[] packet = SlimProtoCodec.encodeSetd(SlimProtoMessages.Setd.ID_PLAYER_NAME, "Pixel 8");

        assertEquals("SETD", ascii(packet, 0, 4));
        assertEquals(8, readInt(packet, 4));
        assertEquals(0, packet[8]);
        assertEquals("Pixel 8", ascii(packet, 9, 7));
    }

    @Test
    public void onlyPrivateServerRedirectsAreFollowed() {
        assertTrue(SlimProtoCodec.parseServ(new byte[]{(byte) 192, (byte) 168, 0, (byte) 133}).isPrivateAddress());
        assertTrue(SlimProtoCodec.parseServ(new byte[]{10, 0, 0, 1}).isPrivateAddress());
        assertTrue(SlimProtoCodec.parseServ(new byte[]{(byte) 172, 20, 0, 1}).isPrivateAddress());
        // The online service and friends: not somewhere this player follows.
        assertFalse(SlimProtoCodec.parseServ(new byte[]{(byte) 204, (byte) 62, 0, 1}).isPrivateAddress());
    }

    @Test
    public void servCarriesAnOptionalSyncGroup() {
        byte[] payload = concat(new byte[]{10, 0, 0, 1}, "abc123".getBytes(StandardCharsets.UTF_8));

        assertEquals("abc123", SlimProtoCodec.parseServ(payload).syncGroupId);
        assertNull(SlimProtoCodec.parseServ(new byte[]{10, 0, 0, 1}).syncGroupId);
    }

    // -------------------------------------------------------------- RESP, DSCO

    @Test
    public void respCarriesTheStreamResponseHeaders() {
        String headers = "HTTP/1.0 200 OK";

        byte[] packet = SlimProtoCodec.encodeResp(headers);

        assertEquals("RESP", ascii(packet, 0, 4));
        assertEquals(headers.length(), readInt(packet, 4));
        assertEquals(headers, ascii(packet, 8, headers.length()));
    }

    @Test
    public void dscoCarriesTheReason() {
        byte[] packet = SlimProtoCodec.encodeDsco(SlimProtoCodec.DISCONNECT_REMOTE);

        assertEquals("DSCO", ascii(packet, 0, 4));
        assertEquals(1, readInt(packet, 4));
        assertEquals(SlimProtoCodec.DISCONNECT_REMOTE, packet[8]);
    }

    // ----------------------------------------------------------------- helpers

    private static SlimProtoMessages.Audg audg(int left, int right, boolean adjust) {
        byte[] payload = new byte[18];
        writeInt(payload, 0, left);     // old gains, unused by the server
        writeInt(payload, 4, right);
        payload[8] = (byte) (adjust ? 1 : 0);
        payload[9] = (byte) 255;        // preamp
        writeInt(payload, 10, left);
        writeInt(payload, 14, right);
        return SlimProtoCodec.parseAudg(payload);
    }

    private static byte[] strmPayload(char command, String header) {
        byte[] headerBytes = header.getBytes(StandardCharsets.UTF_8);
        byte[] payload = new byte[24 + headerBytes.length];
        payload[0] = (byte) command;
        payload[1] = '0';
        payload[2] = 'm';
        payload[3] = '?';
        payload[4] = '?';
        payload[5] = '?';
        payload[6] = '?';
        payload[10] = '0';
        System.arraycopy(headerBytes, 0, payload, 24, headerBytes.length);
        return payload;
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = Arrays.copyOf(a, a.length + b.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }

    private static String ascii(byte[] b, int offset, int length) {
        return new String(b, offset, length, StandardCharsets.US_ASCII);
    }

    private static int readShort(byte[] b, int offset) {
        return ((b[offset] & 0xff) << 8) | (b[offset + 1] & 0xff);
    }

    private static int readInt(byte[] b, int offset) {
        return (int) SlimProtoCodec.readUInt32(b, offset);
    }

    private static long readLong(byte[] b, int offset) {
        return (SlimProtoCodec.readUInt32(b, offset) << 32) | SlimProtoCodec.readUInt32(b, offset + 4);
    }

    private static void writeInt(byte[] b, int offset, int value) {
        b[offset] = (byte) (value >>> 24);
        b[offset + 1] = (byte) (value >>> 16);
        b[offset + 2] = (byte) (value >>> 8);
        b[offset + 3] = (byte) value;
    }
}
