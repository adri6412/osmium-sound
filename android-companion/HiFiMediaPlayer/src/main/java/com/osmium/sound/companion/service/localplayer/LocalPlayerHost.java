package com.osmium.sound.companion.service.localplayer;

/**
 * The few things the local player needs from the service that owns it, kept as
 * an interface so the player does not reach into the service's internals.
 */
public interface LocalPlayerHost {

    /**
     * Sends a player-scoped command to Lyrion over the CometD session that is
     * already open — used to keep the server's idea of this player in step with
     * what actually happened on the phone.
     */
    void sendLocalPlayerCommand(String playerId, String... command);

    /**
     * Audio started or stopped coming out of this phone. The service uses it to
     * stay in the foreground while playing and to route the volume keys.
     */
    void onLocalPlaybackStateChanged(boolean rendering);
}
