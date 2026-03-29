# Let's check `apps` and `radios` API.
# Did the previous attempt fail because we were disconnected, or because it expects a playerid?
# Actually, the user says "the radio and the apps do not go even if they are configured".
# The UI code is `lyrionApi.getRadios()` and `lyrionApi.getApps()`.
# Wait, let's look at `LyrionServer.jsx` and see where `lyrionApi.getRadios()` is called.
