package com.osmium.sound.companion.service.event;

/**
 * Event sent when the timestamp of the last scan finished for the currently connected server
 * has changed
 */
public class LastscanChanged {
    public long lastScan;

    public LastscanChanged(long lastScan) {
        this.lastScan = lastScan;
    }
}
