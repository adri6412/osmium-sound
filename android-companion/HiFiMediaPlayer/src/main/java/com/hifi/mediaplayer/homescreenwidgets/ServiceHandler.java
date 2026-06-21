package com.hifi.mediaplayer.homescreenwidgets;

import com.hifi.mediaplayer.service.ISqueezeService;

@FunctionalInterface
interface ServiceHandler {
    void run(ISqueezeService service) throws Exception;
}
