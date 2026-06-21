package com.hifi.mediaplayer.volume;

import android.view.KeyEvent;

import com.hifi.mediaplayer.service.ISqueezeService;

/**
 * Intercept hardware volume control keys to control slimserver
 * volume.
 *
 * Change the volume when the key is depressed.  Suppress the keyUp
 * event, otherwise you get a notification beep as well as the volume
 * changing.
 */
public class VolumeKeysDelegate {

    public static boolean onKeyDown(int keyCode, ISqueezeService service) {
        return switch (keyCode) {
            case KeyEvent.KEYCODE_VOLUME_UP -> adjustVolume(1, service);
            case KeyEvent.KEYCODE_VOLUME_DOWN -> adjustVolume(-1, service);
            default -> false;
        };
    }

    public static boolean onKeyUp(int keyCode) {
        return switch (keyCode) {
            case KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_VOLUME_DOWN -> true;
            default -> false;
        };
    }

    private static boolean adjustVolume(int direction, ISqueezeService service) {
        if (service == null) {
            return false;
        }
        service.adjustVolume(direction);
        return true;
    }

}
