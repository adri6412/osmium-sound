# Fire TV (3rd gen): key -> (x, y) on the 1030x3448 scan, evdev code, action (remote.cpp)
KEYS = [
    ("power",   224,  285, "KEY_POWER",         "standby"),
    ("alexa",   488,  474, "KEY_SEARCH",        "search"),
    ("up",      488,  725, "KEY_UP",            "up"),
    ("left",    216, 1000, "KEY_LEFT",          "left"),
    ("ok",      488, 1000, "KEY_KPENTER",       "ok"),
    ("right",   759, 1000, "KEY_RIGHT",         "right"),
    ("down",    488, 1277, "KEY_DOWN",          "down"),
    ("back",    224, 1527, "KEY_BACK",          "back"),
    ("home",    488, 1527, "KEY_HOMEPAGE",      "home"),
    ("menu",    750, 1527, "KEY_MENU",          "menu"),
    ("rew",     224, 1785, "KEY_REWIND",        "prev"),
    ("play",    488, 1785, "KEY_PLAYPAUSE",     "playPause"),
    ("ff",      750, 1785, "KEY_FASTFORWARD",   "next"),
    ("mute",    224, 2044, "KEY_MUTE",          "mute"),
    ("volup",   488, 2053, "KEY_VOLUMEUP",      "volumeUp"),
    ("tv",      750, 2036, "KEY_PROGRAM",       "nowPlaying"),
    ("voldown", 488, 2312, "KEY_VOLUMEDOWN",    "volumeDown"),
    ("prime",   293, 2544, "APP_PRIME_VIDEO",   "queue"),
    ("netflix", 681, 2544, "APP_NETFLIX",       "favorite"),
    ("disney",  293, 2760, "APP_DISNEY_PLUS",   "nextVu"),
    ("amusic",  681, 2760, "APP_AMAZON_MUSIC",  "fullScreen"),
]

# OK on the right: on the left its line crossed the ring under "left"
SIDE = {'ok': 'R'}
CROP_BOTTOM = 2900
