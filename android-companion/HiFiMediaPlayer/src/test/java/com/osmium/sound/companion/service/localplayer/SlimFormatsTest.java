package com.osmium.sound.companion.service.localplayer;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/**
 * The capability string is the only thing that tells Lyrion what to send us, so
 * a typo here shows up as silence or as a needlessly transcoded stream.
 */
public class SlimFormatsTest {

    @Test
    public void losslessAsksForFlacFirst() {
        String caps = SlimFormats.capabilities("squeezelite", "Osmium Companion", "1.0.7",
                48000, SlimFormats.CODECS_LOSSLESS);

        assertTrue(caps.startsWith("Model=squeezelite,ModelName=Osmium Companion,"));
        assertTrue(caps.contains(",MaxSampleRate=48000,"));
        assertTrue(caps.endsWith(",flc,aac,mp3"));
    }

    @Test
    public void syncIsNotClaimed() {
        // Claiming accurate play points makes the server treat this player as
        // tightly synchronisable, which it is not.
        String caps = SlimFormats.capabilities("squeezelite", "Phone", "1.0.7",
                48000, SlimFormats.CODECS_COMPRESSED);

        assertTrue(caps.contains("AccuratePlayPoints=0"));
        assertFalse(caps.contains("AccuratePlayPoints=1"));
    }

    @Test
    public void dataSaverOnlyAsksForMp3() {
        String caps = SlimFormats.capabilities("squeezelite", "Phone", "1.0.7",
                48000, SlimFormats.CODECS_DATA_SAVER);

        assertTrue(caps.endsWith(",mp3"));
        assertFalse(caps.contains("flc"));
        assertFalse(caps.contains("aac"));
    }

    @Test
    public void aDeviceNameCannotForgeACapability() {
        String caps = SlimFormats.capabilities("squeezelite", "Phone,Rhap=1", "1.0.7",
                48000, SlimFormats.CODECS_DATA_SAVER);

        assertTrue(caps.contains("ModelName=Phone Rhap 1,"));
        assertFalse(caps.contains("Rhap=1"));
    }

    @Test
    public void onlyDecodableFormatsAreAccepted() {
        assertTrue(SlimFormats.isSupportedFormat('m'));
        assertTrue(SlimFormats.isSupportedFormat('f'));
        assertTrue(SlimFormats.isSupportedFormat('a'));
        assertTrue(SlimFormats.isSupportedFormat('o'));
        // Never declared, so the server transcodes instead of sending these.
        assertFalse(SlimFormats.isSupportedFormat('p'));
        assertFalse(SlimFormats.isSupportedFormat('l'));
        // Direct streaming, where the codec arrives later: declined for now.
        assertFalse(SlimFormats.isSupportedFormat('?'));
    }

    @Test
    public void formatBytesMapToMimeTypes() {
        assertEquals("audio/mpeg", SlimFormats.mimeType('m'));
        assertEquals("audio/flac", SlimFormats.mimeType('f'));
        assertEquals("flac", SlimFormats.formatName('f'));
    }
}
