package com.hifi.mediaplayer.homescreenwidgets;

import com.osmium.sound.companion.model.Player;
import com.osmium.sound.companion.service.ISqueezeService;

@FunctionalInterface
interface ServicePlayerHandler {
    void run(ISqueezeService service, Player player) throws Exception;
}
