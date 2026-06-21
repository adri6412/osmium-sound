package com.hifi.mediaplayer.volume;

import com.hifi.mediaplayer.service.ISqueezeService;

public interface VolumeUpdater {
    void update(ISqueezeService.VolumeInfo volumeInfo);
}
