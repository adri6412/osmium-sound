package com.osmium.sound.companion.dialog;

import java.net.URI;
import java.util.regex.Pattern;

/**
 * Reads the server address out of a scanned QR code. Kept free of Android
 * classes so it can be unit tested on the JVM.
 */
public final class PairingQr {

    /** A bare host name, IPv4 address or bracketed IPv6 address, with an optional port. */
    private static final Pattern HOST_PORT = Pattern.compile(
            "^(\\[[0-9A-Fa-f:.]+]|[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::(\\d{1,5}))?$");

    private PairingQr() {
    }

    /**
     * Extracts a "host:port" (or bare host) string from scanned QR content. The
     * appliance's own QR codes carry a full URL like
     * "http://192.168.1.50:9000/material/"; a plain "host" or "host:port" is
     * also accepted as-is.
     *
     * @return the address, or null when the content is not one: a Wi-Fi QR, a
     * sentence, a URL without a host. Such content used to be taken as the host
     * itself, leaving the wizard ready to connect to a nonsense address.
     */
    public static String hostPort(String content) {
        if (content == null) {
            return null;
        }
        content = content.trim();
        if (content.isEmpty()) {
            return null;
        }
        if (content.matches("(?i)^[a-z][a-z0-9+.-]*://.*")) {
            try {
                URI uri = URI.create(content);
                String host = uri.getHost();
                if (host == null) {
                    return null;
                }
                int port = uri.getPort();
                return port > 0 ? (host + ":" + port) : host;
            } catch (Exception e) {
                return null;
            }
        }
        var matcher = HOST_PORT.matcher(content);
        if (!matcher.matches()) {
            return null;
        }
        String port = matcher.group(2);
        if (port != null) {
            int value = Integer.parseInt(port);
            if (value < 1 || value > 65535) {
                return null;
            }
        }
        return content;
    }
}
