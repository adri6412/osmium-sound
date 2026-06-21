package com.hifi.mediaplayer.homescreenwidgets;

import com.hifi.mediaplayer.model.Player;
import com.hifi.mediaplayer.service.ISqueezeService;

@FunctionalInterface
interface ServicePlayerHandler {
    void run(ISqueezeService service, Player player) throws Exception;
}
