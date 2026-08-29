package com.osmium.sound.companion.service.localplayer;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import android.net.Uri;

import androidx.media3.common.C;
import org.mockito.Mockito;
import androidx.media3.datasource.DataSpec;

import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.Random;

/**
 * Reproduces, on the JVM, the thing that kept the local player silent.
 *
 * <p>The player does not read a track in one pass: it fills its buffer, closes
 * the source, and later reopens it — asking to resume from the extractor's read
 * position, which trails the bytes actually handed over because the extractor
 * peeks ahead while parsing. Against a socket there is nothing to rewind to, so
 * the first version refused the reopen; with retries set to zero that error was
 * fatal and the track died before a sample ever reached the speaker.
 *
 * <p>These tests drive that exact sequence and check the decoder would have
 * received the stream byte for byte.
 */
public class SlimStreamDataSourceTest {

    // Uri is a stub off-device, so it is mocked rather than parsed.
    private static final Uri URI = Mockito.mock(Uri.class);

    /** Stands in for the socket: hands out a known stream, a chunk at a time. */
    private static final class FakeStream implements SlimStream {
        private final byte[] data;
        private int offset;

        FakeStream(byte[] data) {
            this.data = data;
        }

        @Override
        public int read(byte[] buffer, int at, int length) {
            if (offset == data.length) return -1;
            int n = Math.min(length, data.length - offset);
            System.arraycopy(data, offset, buffer, at, n);
            offset += n;
            return n;
        }
    }

    @Test(timeout = 30_000)
    public void resumingWhereThePlayerLeftOffKeepsTheStreamIntact() throws IOException {
        byte[] audio = stream(400_000);
        SlimStreamDataSource source = new SlimStreamDataSource(new FakeStream(audio), () -> {});
        ByteArrayOutputStream delivered = new ByteArrayOutputStream();

        // First pass: the player buffers a while and then stops loading.
        source.open(new DataSpec(URI));
        long read = copy(source, delivered, 120_000);
        source.close();

        // It comes back a little behind, where its extractor had got to.
        long resumeFrom = read - 40_000;
        source.open(new DataSpec.Builder().setUri(URI).setPosition(resumeFrom).build());
        ByteArrayOutputStream rest = new ByteArrayOutputStream();
        copy(source, rest, Long.MAX_VALUE);

        byte[] combined = concat(
                java.util.Arrays.copyOf(delivered.toByteArray(), (int) resumeFrom),
                rest.toByteArray());
        assertArrayEquals("the decoder must see the original stream", audio, combined);
    }

    @Test(timeout = 30_000)
    public void severalStopsAndResumesStillDeliverEveryByte() throws IOException {
        byte[] audio = stream(900_000);
        SlimStreamDataSource source = new SlimStreamDataSource(new FakeStream(audio), () -> {});
        byte[] rebuilt = new byte[audio.length];
        long position = 0;

        // Stop and resume the way the player does all through a track, each time
        // coming back a little behind where the bytes actually got to. Stepping
        // back after the last read would mean reading the same tail forever, so
        // the loop ends where the stream does.
        boolean ended = false;
        while (!ended) {
            source.open(new DataSpec.Builder().setUri(URI).setPosition(position).build());
            ByteArrayOutputStream chunk = new ByteArrayOutputStream();
            ended = copy(source, chunk, 150_000) == END_OF_STREAM;
            source.close();

            byte[] bytes = chunk.toByteArray();
            if (bytes.length == 0) break;
            System.arraycopy(bytes, 0, rebuilt, (int) position, bytes.length);
            position += bytes.length;
            if (!ended) position -= Math.min(20_000, position);
        }

        assertArrayEquals("every byte of the track reaches the decoder, in order", audio, rebuilt);
    }

    @Test(timeout = 30_000)
    public void endOfInputIsReportedOnceAndOnlyAtTheEnd() throws IOException {
        byte[] audio = stream(50_000);
        int[] endings = {0};
        SlimStreamDataSource source =
                new SlimStreamDataSource(new FakeStream(audio), () -> endings[0]++);

        source.open(new DataSpec(URI));
        copy(source, new ByteArrayOutputStream(), Long.MAX_VALUE);

        assertEquals("the server is told exactly once that the track is drained", 1, endings[0]);
    }

    @Test(timeout = 30_000)
    public void aResumeBeyondTheRewindWindowIsRefusedRatherThanFaked() throws IOException {
        byte[] audio = stream(2_000_000);
        SlimStreamDataSource source = new SlimStreamDataSource(new FakeStream(audio), () -> {});

        source.open(new DataSpec(URI));
        copy(source, new ByteArrayOutputStream(), 1_500_000);
        source.close();

        try {
            source.open(new DataSpec.Builder().setUri(URI).setPosition(1_000).build());
            fail("a rewind past the window should not pretend to succeed");
        } catch (IOException expected) {
            assertTrue(expected.getMessage(), expected.getMessage().contains("cannot resume"));
        }
    }

    /** Returned by {@link #copy} when the source ran out rather than hit the limit. */
    private static final long END_OF_STREAM = -1;

    /**
     * Reads up to {@code limit} bytes. Returns {@link #END_OF_STREAM} if the
     * source ended, so a caller can tell "there is more, I stopped" from "there
     * is nothing left" — the difference between a loop that ends and one that
     * reads the same tail forever.
     */
    private static long copy(SlimStreamDataSource source, ByteArrayOutputStream out, long limit)
            throws IOException {
        byte[] buffer = new byte[16 * 1024];
        long total = 0;
        while (total < limit) {
            int want = (int) Math.min(buffer.length, limit - total);
            int read = source.read(buffer, 0, want);
            if (read == C.RESULT_END_OF_INPUT) return END_OF_STREAM;
            out.write(buffer, 0, read);
            total += read;
        }
        return total;
    }

    private static byte[] stream(int length) {
        byte[] data = new byte[length];
        new Random(42).nextBytes(data);
        return data;
    }

    private static byte[] concat(byte[] a, byte[] b) {
        byte[] out = java.util.Arrays.copyOf(a, a.length + b.length);
        System.arraycopy(b, 0, out, a.length, b.length);
        return out;
    }
}
