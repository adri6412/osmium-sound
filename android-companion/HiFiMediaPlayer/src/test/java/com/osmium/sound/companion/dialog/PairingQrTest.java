package com.osmium.sound.companion.dialog;

import junit.framework.TestCase;

public class PairingQrTest extends TestCase {

    public void testUrlKeepsHostAndPort() {
        assertEquals("192.168.1.50:9000", PairingQr.hostPort("http://192.168.1.50:9000/material/"));
        assertEquals("hifiplayer.local", PairingQr.hostPort("  http://hifiplayer.local/ "));
    }

    public void testBareHostAndPort() {
        assertEquals("192.168.0.10:9000", PairingQr.hostPort("192.168.0.10:9000"));
        assertEquals("hifiplayer.local", PairingQr.hostPort("hifiplayer.local"));
        assertEquals("osmium.tail1234.ts.net:9000", PairingQr.hostPort("osmium.tail1234.ts.net:9000"));
        assertEquals("[fd00::1]:9000", PairingQr.hostPort("[fd00::1]:9000"));
    }

    public void testRejectsContentThatIsNotAnAddress() {
        assertNull(PairingQr.hostPort(null));
        assertNull(PairingQr.hostPort(""));
        assertNull(PairingQr.hostPort("   "));
        assertNull(PairingQr.hostPort("WIFI:S:home;T:WPA;P:secret;;"));
        assertNull(PairingQr.hostPort("hello world"));
        assertNull(PairingQr.hostPort("file:///sdcard/x"));
        assertNull(PairingQr.hostPort("192.168.0.10:99999"));
        assertNull(PairingQr.hostPort("192.168.0.10:0"));
        assertNull(PairingQr.hostPort("-bad.host"));
    }
}
