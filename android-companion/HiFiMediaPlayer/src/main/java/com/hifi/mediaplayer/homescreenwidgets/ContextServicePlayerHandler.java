package com.hifi.mediaplayer.homescreenwidgets;

import android.content.Context;

import com.hifi.mediaplayer.model.Player;
import com.hifi.mediaplayer.service.ISqueezeService;

@FunctionalInterface
interface ContextServicePlayerHandler {
    void run(Context context, ISqueezeService service, Player player) throws Exception;
}
