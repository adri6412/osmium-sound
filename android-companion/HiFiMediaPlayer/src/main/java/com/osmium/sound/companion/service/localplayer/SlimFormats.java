package com.osmium.sound.companion.service.localplayer;

/**
 * Which formats we tell Lyrion we can play, and how what it sends back maps
 * onto a decoder.
 *
 * <p>The order of the codec list matters: the server picks the first entry it
 * has a conversion rule for, so it doubles as a preference order. Anything we
 * leave out is transcoded server-side, which is exactly what we want for the
 * formats Android cannot decode without shipping our own decoder.
 *
 * <p>Android-free on purpose, so the capability strings stay unit-testable.
 */
public final class SlimFormats {

    /** Lossless first: the server only transcodes when it has to. */
    public static final String[] CODECS_LOSSLESS = {"flc", "aac", "mp3"};
    /** No FLAC decoder on this device, so lossless is not on the table. */
    public static final String[] CODECS_LOSSLESS_NO_FLAC = {"aac", "mp3"};
    public static final String[] CODECS_COMPRESSED = {"aac", "mp3"};
    public static final String[] CODECS_DATA_SAVER = {"mp3"};

    /** Phone DACs run at 48 kHz; asking for more only makes the server resample. */
    public static final int DEFAULT_MAX_SAMPLE_RATE = 48000;

    private SlimFormats() {
    }

    /**
     * Builds the capability string sent with HELO.
     *
     * <p>{@code AccuratePlayPoints} stays at 0 deliberately: claiming accurate
     * play points makes the server treat this player as tightly synchronisable,
     * and multi-room sync is not something this player can honour yet.
     */
    public static String capabilities(String model, String modelName, String firmware,
                                      int maxSampleRate, String[] codecs) {
        StringBuilder caps = new StringBuilder(160);
        caps.append("Model=").append(model)
                .append(",ModelName=").append(sanitise(modelName))
                .append(",AccuratePlayPoints=0")
                .append(",HasDigitalOut=0")
                .append(",HasPolarityInversion=0")
                .append(",Balance=0")
                .append(",Firmware=").append(sanitise(firmware))
                .append(",MaxSampleRate=").append(maxSampleRate);
        for (String codec : codecs) {
            caps.append(',').append(codec);
        }
        return caps.toString();
    }

    /**
     * Commas and equals signs separate capabilities, so a device name containing
     * one would be read as another capability.
     */
    private static String sanitise(String value) {
        if (value == null) return "";
        return value.replace(',', ' ').replace('=', ' ').trim();
    }

    /** True when the format byte names something we are prepared to decode. */
    public static boolean isSupportedFormat(char formatByte) {
        switch (formatByte) {
            case 'm': // mp3
            case 'f': // flac
            case 'a': // aac
            case 'o': // ogg
                return true;
            default:
                // 'p' pcm and 'l' alac are never declared, and '?' means the
                // server wants us to sniff a direct stream, which we decline.
                return false;
        }
    }

    /** Human-readable name for logs. */
    public static String formatName(char formatByte) {
        switch (formatByte) {
            case 'm': return "mp3";
            case 'f': return "flac";
            case 'a': return "aac";
            case 'o': return "ogg";
            case 'p': return "pcm";
            case 'l': return "alac";
            case '?': return "unknown";
            default: return "0x" + Integer.toHexString(formatByte);
        }
    }

    /** MIME type used to look up a platform decoder and to hint the extractor. */
    public static String mimeType(char formatByte) {
        switch (formatByte) {
            case 'm': return "audio/mpeg";
            case 'f': return "audio/flac";
            case 'a': return "audio/mp4a-latm";
            case 'o': return "audio/ogg";
            default: return null;
        }
    }
}
