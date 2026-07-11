package com.osmium.sound.companion.homescreenwidgets;

import com.osmium.sound.companion.service.ISqueezeService;

@FunctionalInterface
interface ServiceHandler {
    void run(ISqueezeService service) throws Exception;
}
