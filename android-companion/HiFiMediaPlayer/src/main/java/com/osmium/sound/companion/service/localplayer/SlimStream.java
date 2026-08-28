package com.osmium.sound.companion.service.localplayer;

import java.io.IOException;

/**
 * The byte source behind a track: a socket the server feeds us, in production.
 * Kept as an interface so the awkward part — how the player closes and reopens
 * the stream mid-track — can be exercised in a plain JVM test, without a device.
 */
interface SlimStream {

    /**
     * Blocks until there is audio, and returns -1 once the server has sent
     * everything and the buffer is drained.
     */
    int read(byte[] buffer, int offset, int length) throws IOException;
}
