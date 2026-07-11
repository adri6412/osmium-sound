package com.hifi.mediaplayer.homescreenwidgets;

import android.content.Context;

import com.osmium.sound.companion.model.Player;
import com.osmium.sound.companion.service.ISqueezeService;

@FunctionalInterface
interface ContextServicePlayerHandler {
    void run(Context context, ISqueezeService service, Player player) throws Exception;
}
