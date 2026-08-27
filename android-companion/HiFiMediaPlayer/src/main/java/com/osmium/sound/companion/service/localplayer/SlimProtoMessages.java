package com.osmium.sound.companion.service.localplayer;

import java.util.Arrays;

/**
 * Value objects for the server-to-client SlimProto commands we act on.
 *
 * <p>Field names and layouts follow the reference player (squeezelite's
 * {@code slimproto.h}); see {@link SlimProtoCodec} for the wire format.
 */
public final class SlimProtoMessages {

    private SlimProtoMessages() {
    }

    /** Stream control: the one command that actually matters. */
    public static final class Strm {
        /** 's' start, 'p' pause, 'u' unpause, 'q' stop, 't' status, 'f' flush, 'a' skip. */
        public final char command;
        /** 0 = wait for unpause, 1 = start on threshold, 2/3 = direct streaming. */
        public final int autostart;
        /** 'm' mp3, 'f' flac, 'a' aac, 'o' ogg, 'p' pcm, 'l' alac, '?' unknown (direct). */
        public final char format;
        public final char pcmSampleSize;
        public final char pcmSampleRate;
        public final char pcmChannels;
        public final char pcmEndianness;
        /** Input buffer to accumulate before starting, in KB. */
        public final int thresholdKb;
        public final int transitionPeriod;
        public final int transitionType;
        public final int flags;
        /** Output buffer trigger, in tenths of a second. */
        public final int outputThreshold;
        /**
         * Raw 32-bit field, reused per command: replay gain for 's', pause/skip
         * interval in ms for 'p'/'a', target jiffies for 'u', and the server
         * timestamp to echo back for 't'.
         */
        public final long replayGain;
        public final int serverPort;
        /** Four bytes in network order; all zero means "the server we are talking to". */
        public final byte[] serverIp;
        /** The HTTP request to send, verbatim. Never rebuild it. */
        public final byte[] httpHeader;

        Strm(char command, int autostart, char format, char pcmSampleSize, char pcmSampleRate,
             char pcmChannels, char pcmEndianness, int thresholdKb, int transitionPeriod,
             int transitionType, int flags, int outputThreshold, long replayGain, int serverPort,
             byte[] serverIp, byte[] httpHeader) {
            this.command = command;
            this.autostart = autostart;
            this.format = format;
            this.pcmSampleSize = pcmSampleSize;
            this.pcmSampleRate = pcmSampleRate;
            this.pcmChannels = pcmChannels;
            this.pcmEndianness = pcmEndianness;
            this.thresholdKb = thresholdKb;
            this.transitionPeriod = transitionPeriod;
            this.transitionType = transitionType;
            this.flags = flags;
            this.outputThreshold = outputThreshold;
            this.replayGain = replayGain;
            this.serverPort = serverPort;
            this.serverIp = serverIp;
            this.httpHeader = httpHeader;
        }

        /** True when the server left the address at zero, meaning "stream from me". */
        public boolean useControlServer() {
            for (byte b : serverIp) {
                if (b != 0) return false;
            }
            return true;
        }

        public String serverIpString() {
            return (serverIp[0] & 0xff) + "." + (serverIp[1] & 0xff) + "."
                    + (serverIp[2] & 0xff) + "." + (serverIp[3] & 0xff);
        }

        @Override
        public String toString() {
            return "strm " + command + " autostart=" + autostart + " format=" + format
                    + " threshold=" + thresholdKb + "KB port=" + serverPort
                    + " ip=" + serverIpString() + " headerLen=" + httpHeader.length;
        }
    }

    /** Volume. Gains are 16.16 fixed point, with the server's curve already applied. */
    public static final class Audg {
        public final long gainLeft;
        public final long gainRight;
        /** Digital volume control: when false the player must not attenuate. */
        public final boolean adjust;
        public final int preamp;

        Audg(long gainLeft, long gainRight, boolean adjust, int preamp) {
            this.gainLeft = gainLeft;
            this.gainRight = gainRight;
            this.adjust = adjust;
            this.preamp = preamp;
        }

        /** Averaged linear amplitude for a single-volume output, clamped to 1.0. */
        public float linearGain() {
            if (!adjust) return 1f;
            double gain = ((double) gainLeft + (double) gainRight) / 2d / 65536d;
            return (float) Math.max(0d, Math.min(1d, gain));
        }

        @Override
        public String toString() {
            return "audg L=" + gainLeft + " R=" + gainRight + " dvc=" + adjust + " -> " + linearGain();
        }
    }

    /** Output enable. Only {@link #dac} is meaningful for a software player. */
    public static final class Aude {
        public final boolean spdif;
        public final boolean dac;

        Aude(boolean spdif, boolean dac) {
            this.spdif = spdif;
            this.dac = dac;
        }

        @Override
        public String toString() {
            return "aude spdif=" + spdif + " dac=" + dac;
        }
    }

    /**
     * Player setting. Id 0 is the player name: the server queries it during
     * registration (empty payload) and sets it on rename (payload present).
     */
    public static final class Setd {
        public static final int ID_PLAYER_NAME = 0;

        public final int id;
        /** Null when the server is asking rather than telling. */
        public final String value;

        Setd(int id, String value) {
            this.id = id;
            this.value = value;
        }

        public boolean isQuery() {
            return value == null;
        }

        @Override
        public String toString() {
            return "setd id=" + id + (isQuery() ? " (query)" : " value=" + value);
        }
    }

    /** "Go talk to this server instead". */
    public static final class Serv {
        public final byte[] ip;
        public final String syncGroupId;

        Serv(byte[] ip, String syncGroupId) {
            this.ip = ip;
            this.syncGroupId = syncGroupId;
        }

        public String ipString() {
            return (ip[0] & 0xff) + "." + (ip[1] & 0xff) + "." + (ip[2] & 0xff) + "." + (ip[3] & 0xff);
        }

        /**
         * Only a private address is a real server switch; a public one is a redirect
         * to the online service, which this player does not follow.
         */
        public boolean isPrivateAddress() {
            int a = ip[0] & 0xff;
            int b = ip[1] & 0xff;
            return a == 10
                    || (a == 172 && b >= 16 && b <= 31)
                    || (a == 192 && b == 168)
                    || (a == 169 && b == 254)
                    || a == 127;
        }

        @Override
        public String toString() {
            return "serv ip=" + ipString() + " sync=" + syncGroupId;
        }
    }

    /** A raw frame as read off the wire. */
    public static final class Frame {
        public final String opcode;
        public final byte[] payload;

        public Frame(String opcode, byte[] payload) {
            this.opcode = opcode;
            this.payload = payload;
        }

        @Override
        public String toString() {
            return opcode + "[" + payload.length + "] " + Arrays.toString(Arrays.copyOf(payload, Math.min(16, payload.length)));
        }
    }
}
