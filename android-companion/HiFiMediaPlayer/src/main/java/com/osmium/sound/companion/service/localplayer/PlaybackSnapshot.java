package com.osmium.sound.companion.service.localplayer;

/**
 * Everything a STAT packet needs, written by the audio thread and read by the
 * protocol thread. Fields are volatile rather than locked: a STAT is a snapshot
 * of a moving target anyway, and the server tolerates fields that are a few
 * milliseconds apart.
 */
public final class PlaybackSnapshot {

    /** Consecutive CRLFs seen while parsing the stream's response headers. */
    public volatile int crlfCount;

    /** Capacity of our input ring buffer, and how much of it holds data. */
    public volatile long streamBufferSize;
    public volatile long streamBufferFullness;

    /** Bytes read from the stream socket for the current track. */
    public volatile long bytesReceived;

    /** 0xFFFF means "wired or unknown", which is what the server expects from us. */
    public volatile int signalStrength = 0xFFFF;

    /** Nominal size of the decoded audio buffer, and its current fill, in bytes. */
    public volatile long outputBufferSize;
    public volatile long outputBufferFullness;

    /** Position within the track currently being rendered. */
    public volatile long elapsedMilliseconds;

    /** Echoed back to the server in the STMt that answers a strm 't'. */
    public volatile long serverTimestamp;

    public volatile int errorCode;

    public long elapsedSeconds() {
        return elapsedMilliseconds / 1000L;
    }

    /** Called when a new track starts: the byte counters are per track. */
    public void resetForNewTrack() {
        bytesReceived = 0;
        streamBufferFullness = 0;
        elapsedMilliseconds = 0;
        crlfCount = 0;
        errorCode = 0;
    }
}
