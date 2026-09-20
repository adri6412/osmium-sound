// Le Impostazioni (src/pages/Settings.jsx, screen_settings.c): l'elenco delle
// 20 sezioni e, dentro ciascuna, un elenco dichiarativo di righe costruito da
// build() e reso da SettingsRows. I dati arrivano dal api_server (:8000) e
// da sources_server (:8080); ogni azione manda la richiesta e poi rilegge.
import QtQuick
import Hifi
import Hifi.Ui

Item {
    id: root
    property real devScale: 1
    property int active: -1
    property var rows: []
    property string msg: ""
    property bool msgErr: false
    readonly property bool atRoot: active < 0

    // ─── stato locale della sezione aperta (S.*) ───────────────────────────
    property string audioSel: ""
    property string sshUser: ""; property string sshPass: ""
    property string nameEdit: ""; property string hostEdit: ""
    property string pendAct: ""; property string pendArg: ""
    property int countdown: 0
    property int alarmH: 7; property int alarmM: 0
    // 🚨 persistente come in Electron (li' e' in localStorage): lo legge anche
    // la barra dei tab per decidere se controllare gli aggiornamenti
    property bool autoCheck: Sys.conf("ota-autocheck", "1") !== "0"
    property bool smbShowPw: false
    // Bluetooth speakers: which speaker's panel is open, and the name being
    // typed into it. The name is held here rather than written straight back
    // to cfg because a rebuild would otherwise throw away a half-typed word
    // every time the five-second refresh lands.
    property int btBand: -1
    property string btNameEdit: ""
    property bool btBusy: false
    property bool btScanning: false
    // Procedura guidata "aggiungi una cartella di rete". Sostituisce le quattro
    // caselle vuote (server/share/utente/password), che sono inutilizzabili per
    // chi non sa gia' cos'e' una condivisione SMB: prima si cercano da soli i
    // dispositivi in rete, come fa la lista Wi-Fi qui accanto, poi si tocca la
    // cartella. Scrivere tutto a mano resta, ma come ripiego.
    property int wiz: -1                 // -1 spenta; 0 cerca, 1 cartella, 2 conferma
    property bool wizManual: false
    property string wizHost: ""; property string wizName: ""; property string wizShare: ""
    property string wizUser: ""; property string wizPw: ""
    property bool wizRw: false; property bool wizBusy: false
    property string wizErr: ""; property string wizDetail: ""; property bool wizDetailOpen: false
    property var wizShares: []           // [{name, comment}]
    property bool wizNeedsAuth: false
    property bool wizCanList: true       // le condivisioni di questo server si possono leggere
    property bool wizNoClient: false     // ...perche' l'apparecchio non ha smbclient
    property string scanState: ""; property int scanPct: 0
    property var scanHosts: []           // [{ip, name}]
    property int band: -1; property int bandAdd: -1; property int bandShare: -1
    property string brId: ""; property bool brBusy: false
    property int pickOwner: 0; property string pickNew: ""; property bool pickBusy: false
    property bool fmtWatch: false
    property var timezones: []
    property var thirdParty: null
    // network check (api_server /network_check): the last result, and the
    // section it was opened from, where the back arrow returns
    property var nc: null
    property bool ncBusy: false
    property bool ncFailed: false
    property bool ncAdvanced: false      // addresses, timings and sources, for whoever helps the owner
    property string backTo: ""

    // Sections are addressed by id, never by position: a new one moves every
    // index after it (openSection() also takes the id)
    function secIndex(id) {
        for (var i = 0; i < secs.length; i++) if (secs[i].id === id) return i
        return -1
    }
    readonly property var secs: [
        { id: "language", icon: "globe", key: "settings.sections.language" },
        { id: "sources", icon: "hard-drive", key: "settings.sections.sources" },
        { id: "audio", icon: "volume-2", key: "settings.sections.audio" },
        { id: "btSpeakers", icon: "bluetooth", key: "settings.sections.btSpeakers" },
        { id: "playback", icon: "sliders", key: "settings.sections.playback" },
        { id: "vuMeters", icon: "audio-lines", key: "settings.sections.vuMeters" },
        { id: "animations", icon: "disc-3", key: "settings.sections.animations" },
        { id: "library", icon: "library", key: "settings.sections.library" },
        { id: "multiroom", icon: "speaker", key: "settings.sections.multiroom" },
        { id: "alarm", icon: "alarm-clock", key: "settings.sections.alarm" },
        { id: "network", icon: "wifi", key: "settings.sections.network" },
        { id: "webRemote", icon: "smartphone", key: "settings.sections.webRemote" },
        { id: "webRemoteIos", icon: "tablet", key: "settings.sections.webRemoteIos" },
        { id: "ssh", icon: "terminal", key: "settings.sections.ssh" },
        { id: "pointer", icon: "mouse-pointer-2", key: "settings.sections.pointer" },
        { id: "uiResolution", icon: "gauge", key: "settings.sections.uiResolution" },
        { id: "uiRefresh", icon: "refresh-cw", key: "settings.sections.uiRefresh" },
        { id: "displayMode", icon: "monitor", key: "settings.sections.displayMode" },
        { id: "timezone", icon: "clock", key: "settings.sections.timezone" },
        { id: "systemInfo", icon: "info", key: "settings.sections.systemInfo" },
        { id: "updates", icon: "download", key: "settings.sections.updates" },
        { id: "systemControls", icon: "power", key: "settings.sections.systemControls" },
        { id: "thirdPartyNotices", icon: "scroll-text", key: "settings.sections.thirdPartyNotices" },
        // reached from System info and Updates, not listed on its own
        { id: "netCheck", icon: "network", key: "settings.sections.netCheck", hidden: true }]
    readonly property var listedSecs: secs.filter(function(s) { return !s.hidden })

    Component.onCompleted: Ui.settings = root

    // ─── dati dai servizi (cfg.*) ────────────────────────────────────────────
    QtObject {
        id: cfg
        property bool loaded: false
        property bool apiOk: false
        property int pending: 0
        property int gen: 0
        property string hostname: ""; property string platform: ""; property string arch: ""; property string localIp: ""; property string version: ""; property string deviceIp: ""
        property string deviceName: ""
        property bool sshEnabled: false; property bool sshAvailable: false; property bool sshActive: false
        property bool pointerEnabled: true; property bool pointerAvailable: true
        property string shellUser: ""
        property string displayMode: "gui"; property string uiResolution: "auto"; property string uiRefresh: "native"; property bool uiRefreshSupported: false
        property string timezone: ""
        property bool vuMeter: true; property int autoexpand: 0; property bool playerEnabled: true
        // Bluetooth speakers (api_server /bt_speakers). btSpeakers are the ones
        // set up as players, btFound whatever else the last search saw.
        property bool btAvailable: false; property bool btEnabled: false; property bool btAdapter: false
        property var btSpeakers: []
        property var btFound: []
        property var vuStyles: []                                   // [{id, name:{en,it}}]; the choice is Player.vuStyle
        property string npAnimation: "none"                         // Now Playing animation with the VU meters off
        // VU meter store (api_server /vu_store): the full list only while the
        // section is open, the count of news for the dot on its row always
        property var vuStore: ({ skins: [], checking: false, busy: false, error: null, loaded: false })
        property int vuStoreNew: 0
        // the animation store (api_server /anim_store), the same way; storeAnims
        // are the animations downloaded from it, offered next to the built-in ones
        property var animStore: ({ animations: [], checking: false, busy: false, error: null, loaded: false })
        property int animStoreNew: 0
        property var storeAnims: []                                 // [{id, name:{en,it}, scene}]
        property string otaChannel: "prod"; property var otaChannels: ["prod", "dev"]
        property string audioCur: ""; property var audio: []          // [{id,name}]
        property string lmsMode: "local"; property string lmsHost: ""; property string playerName: ""; property string lyrionChannel: "release"
        property string lmsSkin: "unset"; property string skinState: ""; property string skinMsg: ""
        property string lyrInstalled: ""; property var lyrChVer: ["", "", ""]; property string lyrStatus: ""; property int lyrPct: 0; property bool lyrRunning: false
        property var disc: []                                       // [{name, ip}]
        // the server's library: totals, last scan, a scan in progress
        property var lib: ({ albums: -1, artists: -1, songs: -1, duration: 0, lastScan: 0, scanning: false, progress: "", pct: -1 })
        // album and artist information from the web (sources_server /api/meta/settings)
        property var meta: ({ available: false, online: true, prefetch: true, albums: 0, artists: 0, bytes: 0, running: false, done: 0, total: 0 })
        property var players: []                                    // [{id,name,sync}]
        property var alarms: []                                     // [{id,time,on}]
        property string netType: ""; property string netSsid: ""; property string netIp: ""; property string netDev: ""; property string netSubnet: ""; property bool netConnected: false
        property var ifaces: []                                     // [{name,addr,wifi,active}]
        property var wifi: []                                       // [{ssid,security,signal}]
        property var upd: [{cur: "", latest: "", avail: false}, {cur: "", latest: "", avail: false}, {cur: "", latest: "", avail: false}]
        property bool updChecking: false; property bool updCheckFailed: false
        property string otaState: ""; property string otaMsg: ""; property int otaPct: 0
        property string changelog: ""
        property var sources: []                                    // oggetti /api/sources
        property var usb: []                                        // chiavette da sistemare
        property var disks: []                                      // dischi interni
        property string smbHost: ""; property string smbIp: ""; property string smbUser: ""; property string smbPass: ""; property bool smbEnabled: false; property var smbShares: []
        property string pldir: ""; property string pldirDef: ""; property bool pldirDefault: false
        property string brPath: ""; property string brParent: ""; property bool brHasParent: false; property var brDirs: []
        property string pkPath: ""; property string pkParent: ""; property bool pkHasParent: false; property var pkDirs: []
        property string fmtState: ""; property string fmtMsg: ""; property int fmtPct: 0
        property string pairToken: ""

        function api(path) { return Api.apiBase + path }
        function src(path) { return Api.srcBase + path }
        function get(url, fn) {
            pending++
            var g = gen
            Api.get(url, function(ok, d) {
                if (ok && d && typeof d === "object") { try { fn(d) } catch (e) { Sys.log("settings: " + url + ": " + e) } }
                if (--pending === 0 && g === gen) { loaded = true; root.dataChanged() }
            }, 5000)
        }
        // Bluetooth, read only while its own section is open: with the adapter
        // up, answering it runs bluetoothctl once per known device, which is
        // not something load() should do on every settings change.
        function loadBt() {
            Api.get(api("/bt_speakers"), function(ok, d) {
                if (ok && d && typeof d === "object") {
                    btAvailable = !!d.available; btEnabled = !!d.enabled; btAdapter = !!d.adapter
                    btSpeakers = d.speakers || []; btFound = d.found || []
                }
                root.btBusy = false; root.btScanning = false; root.rebuild()
            }, 130000)
        }
        // the store's list, with previews: separate from load(), which runs on
        // every settings change and would carry the images each time
        function loadStore(markSeen) {
            Api.get(api("/vu_store"), function(ok, d) {
                if (!ok || !d || typeof d !== "object") { vuStore = Object.assign({}, vuStore, { loaded: true, checking: false, busy: false }); root.rebuild(); return }
                var wasBusy = vuStore.busy
                d.loaded = true
                d.skins = d.skins || []
                vuStore = d
                if (wasBusy && !d.busy) get(api("/vu_style"), function(v) { vuStyles = v.styles || [] })
                if (markSeen && d.skins.length) Api.post(api("/vu_store/seen"), {}, function() { vuStoreNew = 0 }, 5000)
                root.rebuild()
            }, 10000)
        }
        function loadAnimStore(markSeen) {
            Api.get(api("/anim_store"), function(ok, d) {
                if (!ok || !d || typeof d !== "object") { animStore = Object.assign({}, animStore, { loaded: true, checking: false, busy: false }); root.rebuild(); return }
                var wasBusy = animStore.busy
                d.loaded = true
                d.animations = d.animations || []
                animStore = d
                if (wasBusy && !d.busy) get(api("/nowplaying_animation"), function(v) { storeAnims = v.store || [] })
                if (markSeen && d.animations.length) Api.post(api("/anim_store/seen"), {}, function() { animStoreNew = 0 }, 5000)
                root.rebuild()
            }, 10000)
        }
        // The three update checks read the release manifests over the network,
        // and on an image system each one is the whole image check (manifest,
        // then the sha256 with retries): easily longer than get()'s 5 s. A
        // check that ran out of time was simply dropped, and the "Checking..."
        // put up by the button stayed on screen for good, since nothing ever
        // replaced it. So the checks run apart from load()'s pending count (a
        // slow network must not hold the whole page in "loading"), with their
        // own generous timeout, and always end in an outcome on screen:
        // up to date, update available, or could not check.
        function checkUpdates() {
            if (updChecking) return
            updChecking = true; updCheckFailed = false
            root.dataChanged()
            var paths = ["/app_update/check", "/system_update/check", "/os_update/check"]
            var left = paths.length, failed = false
            for (var i = 0; i < paths.length; i++) (function(i) {
                Api.get(api(paths[i]), function(ok, d) {
                    if (ok && d && typeof d === "object") {
                        var u = upd.slice()
                        u[i] = { cur: str(d, "current"), latest: str(d, "latest"), avail: !!d.update_available }
                        upd = u
                        if (i === 0 && d.notes) changelog = String(d.notes)
                        if (d.error) failed = true
                    } else {
                        failed = true
                    }
                    if (--left === 0) { updChecking = false; updCheckFailed = failed; root.dataChanged() }
                }, 60000)
            })(i)
        }
        function str(d, k, fb) { return d[k] !== undefined && d[k] !== null ? String(d[k]) : (fb || "") }
        // Library totals and scan state come from Lyrion itself (server
        // queries, no player needed): `serverstatus` for the scan, `info
        // total` for the counts. Apart from load()'s pending count, so a
        // server that is slow to answer never holds the page in "loading".
        function loadLibrary() {
            var out = Object.assign({}, lib), left = 5
            function done() { if (--left === 0) { lib = out; root.dataChanged() } }
            Player.queryServer(["serverstatus", "0", "0"], function(ok, r) {
                if (ok && r) {
                    out.lastScan = Number(r.lastscan || 0)
                    out.scanning = Number(r.rescan || 0) !== 0
                    out.progress = r.progressname ? String(r.progressname) : ""
                    var tot = Number(r.progresstotal || 0)
                    out.pct = out.scanning && tot > 0 ? Math.min(100, Math.round(100 * Number(r.progressdone || 0) / tot)) : -1
                }
                done()
            })
            var ents = ["albums", "artists", "songs", "duration"]
            for (var i = 0; i < ents.length; i++) (function(e) {
                Player.queryServer(["info", "total", e, "?"], function(ok, r) {
                    if (ok && r && r["_" + e] !== undefined) out[e] = Number(r["_" + e])
                    done()
                })
            })(ents[i])
        }
        function load() {
            gen++
            get(api("/system_info"), function(d) {
                hostname = str(d, "hostname"); platform = str(d, "platform"); arch = str(d, "arch"); localIp = str(d, "local_ip"); version = str(d, "version")
                var ifs = d.network_interfaces || [], out = [], dip = ""
                for (var i = 0; i < ifs.length; i++) {
                    var nm = String(ifs[i].name || ""), act = !!ifs[i].active
                    out.push({ name: nm, addr: String(ifs[i].address || ""), wifi: nm.charAt(0) === "w", active: act })
                    if (act && !dip) dip = String(ifs[i].address || "")
                }
                ifaces = out; deviceIp = dip; apiOk = true
            })
            get(api("/ssh_status"), function(d) { sshEnabled = !!d.enabled; sshAvailable = !!d.available; sshActive = !!d.active })
            get(api("/pointer_status"), function(d) { pointerEnabled = d.enabled !== false; pointerAvailable = d.available !== false })
            get(api("/vu_meter"), function(d) { vuMeter = d.enabled !== false })
            get(api("/vu_style"), function(d) { vuStyles = d.styles || [] })
            get(api("/nowplaying_animation"), function(d) { npAnimation = str(d, "animation", "none"); storeAnims = d.store || [] })
            get(api("/anim_store?summary=1"), function(d) { animStoreNew = Number(d.new || 0) + Number(d.updates || 0) })
            get(api("/vu_store?summary=1"), function(d) { vuStoreNew = Number(d.new || 0) + Number(d.updates || 0) })
            get(api("/player_enabled"), function(d) { playerEnabled = d.enabled !== false })
            get(api("/ui_refresh"), function(d) { uiRefreshSupported = !!d.supported; uiRefresh = str(d, "mode", "native") })
            get(api("/nowplaying_autoexpand"), function(d) { autoexpand = Number(d.seconds || 0) })
            get(api("/display_mode"), function(d) { displayMode = str(d, "mode", "gui") })
            get(api("/ui_resolution"), function(d) { uiResolution = str(d, "mode", "auto") })
            get(api("/timezone"), function(d) { timezone = str(d, "timezone") })
            get(api("/shell_account"), function(d) { shellUser = str(d, "username") })
            get(api("/device_name"), function(d) { deviceName = str(d, "name") })
            get(api("/ota_channel"), function(d) {
                otaChannel = str(d, "channel", "prod")
                var ch = d.channels || []
                otaChannels = ch.length ? ch.map(String) : ["prod", "dev"]
            })
            get(api("/audio_devices"), function(d) {
                audioCur = str(d, "current")
                audio = (d.devices || []).map(function(x) { return { id: String(x.id || ""), name: String(x.name || "") } })
            })
            get(api("/lms_role"), function(d) { lmsMode = str(d, "mode", "local"); lmsHost = str(d, "host") })
            get(api("/player_name"), function(d) { playerName = str(d, "name") })
            get(api("/lyrion_channel"), function(d) { lyrionChannel = str(d, "channel", "release") })
            get(api("/lyrion_update/check"), function(d) {
                lyrInstalled = str(d, "current")
                var ch = d.channels || {}
                lyrChVer = ["release", "nightly", "dev"].map(function(k) { return ch[k] && ch[k].version ? String(ch[k].version) : "" })
            })
            get(api("/lyrion_update/status"), function(d) { lyrStatus = str(d, "message"); lyrPct = Number(d.percent || 0); lyrRunning = !!d.running })
            get(api("/network_status"), function(d) { netConnected = !!d.connected; netType = str(d, "type"); netSsid = str(d, "ssid"); netIp = str(d, "ip"); netDev = str(d, "device") })
            get(api("/network_info"), function(d) { netSubnet = str(d, "netmask") })
            checkUpdates()
            get(api("/update/status"), function(d) { otaState = str(d, "state"); otaMsg = str(d, "message"); otaPct = Number(d.percent || 0) })
            get(src("/api/lms_skin"), function(d) { lmsSkin = str(d, "skin", "unset") })
            get(src("/api/lms_skin_status"), function(d) { skinState = str(d, "state"); skinMsg = str(d, "message") })
            get(src("/api/sources"), function(d) { sources = d.sources || [] })
            loadLibrary()
            get(src("/api/meta/settings"), function(d) {
                if (d.online === undefined) return
                var c = d.cache || {}, st = d.prefetch_state || {}
                meta = { available: true, online: !!d.online, prefetch: !!d.prefetch, albums: Number(c.albums || 0), artists: Number(c.artists || 0),
                         bytes: Number(c.bytes || 0), running: !!st.running, done: Number(st.done || 0), total: Number(st.total || 0) }
            })
            get(src("/api/usb"), function(d) { usb = d.disks || [] })
            get(src("/api/internal/disks"), function(d) {
                var out = []
                for (var i = 0; i < (d.disks || []).length; i++) {
                    var k = d.disks[i], path = String(k.path || "")
                    if (path.indexOf("boot0") >= 0 || path.indexOf("boot1") >= 0) continue
                    var parts = []
                    for (var j = 0; j < (k.partitions || []).length; j++) {
                        var p = k.partitions[j]
                        if (!p.fstype) continue
                        parts.push({ path: String(p.path || ""), fs: String(p.fstype), label: String(p.label || "") })
                    }
                    out.push({ path: path, model: String(k.model || ""), confirm: String(k.confirm || ""), size: Number(k.size || 0), adopted: !!k.adopted, hasData: !!k.has_data, parts: parts })
                }
                disks = out
            })
            get(src("/api/internal/smb"), function(d) {
                smbHost = str(d, "host"); smbIp = str(d, "ip"); smbUser = str(d, "username"); smbPass = str(d, "password"); smbEnabled = !!d.enabled
                smbShares = (d.shares || []).map(function(s) { return typeof s === "string" ? s : String(s.name || "") })
            })
            get(src("/api/playlistdir"), function(d) { pldir = str(d, "path"); pldirDef = str(d, "default"); pldirDefault = !!d.is_default })
            get(src("/api/internal/format/status"), function(d) { fmtState = str(d, "state"); fmtMsg = str(d, "message"); fmtPct = Number(d.progress !== undefined ? d.progress : (d.percent || 0)) })
            // Lyrion: altri player, scansione, sveglie
            Player.queryServer(["serverstatus", "0", "20"], function(ok, r) {
                if (!ok || !r) return
                var out = []
                for (var i = 0; i < (r.players_loop || []).length; i++) {
                    var p = r.players_loop[i]
                    if (String(p.playerid) === (Player.ownPlayerId || Player.playerId)) continue
                    out.push({ id: String(p.playerid), name: String(p.name || ""), sync: false })
                }
                if (out.length) Player.query(["status", "-", "1"], function(ok2, r2) {
                    var sl = ok2 && r2 && r2.sync_slaves ? String(r2.sync_slaves) : ""
                    for (var i = 0; i < out.length; i++) out[i].sync = sl.indexOf(out[i].id) >= 0
                    players = out; root.dataChanged()
                })
                else { players = out; root.dataChanged() }
            })
            Player.query(["alarms", "0", "99", "filter:all"], function(ok, r) {
                if (!ok || !r) return
                var out = []
                for (var i = 0; i < (r.alarms_loop || []).length; i++) {
                    var a = r.alarms_loop[i]
                    out.push({ id: String(a.id), time: Number(a.time || 0), on: a.enabled === true || Number(a.enabled) !== 0 && a.enabled !== undefined && a.enabled !== false })
                }
                alarms = out; root.dataChanged()
            })
        }
        function mintToken() {
            Api.post(src("/api/pair/token"), {}, function(ok, d) { pairToken = ok && d && d.token ? String(d.token) : ""; root.dataChanged() }, 6000)
        }
        function loadWifi() {
            Api.get(api("/wifi_scan"), function(ok, d) {
                wifi = ok && d && d.networks ? d.networks.map(function(n) { return { ssid: String(n.ssid || ""), security: String(n.security || ""), signal: Number(n.signal || 0) } }) : []
                if (Ui.dialogs) Ui.dialogs.updateWifi(wifi)
            }, 20000)
        }
        function loadDiscover() {
            Api.get(api("/discover_lms"), function(ok, d) {
                var out = []
                for (var i = 0; ok && d && i < (d.servers || []).length; i++) {
                    var s = d.servers[i], ip = String(s.ip || s.address || "")
                    if (!ip || ip === deviceIp) continue
                    out.push({ name: String(s.name || ip), ip: ip })
                }
                disc = out; root.dataChanged()
            }, 15000)
        }
        // /api/sources/<id>/browse (relativo al mount) oppure /api/local/browse (assoluto)
        function browse(kind, id, path) {
            var url = kind === 1 ? src("/api/sources/" + id + "/browse?path=" + encodeURIComponent(path))
                                 : src("/api/local/browse?path=" + encodeURIComponent(path))
            Api.get(url, function(ok, d) {
                var dirs = [], cur = path, par = "", hasp = false
                if (ok && d && d.success !== false) {
                    if (typeof d.parent === "string") { par = d.parent; hasp = true }
                    if (typeof d.path === "string") cur = d.path
                    dirs = (d.dirs || []).map(String)
                }
                if (kind === 1) { brPath = cur; brParent = par; brHasParent = hasp; brDirs = dirs; root.brBusy = false }
                else { pkPath = cur; pkParent = par; pkHasParent = hasp; pkDirs = dirs; root.pickBusy = false }
                root.dataChanged()
            }, 8000)
        }
    }
    // Le preferenze del player arrivano dal poll (asincrono): quando cambiano,
    // la sezione aperta va ricostruita, se no la riga resta sullo stato vecchio
    // e il tocco successivo rimanda lo stesso valore (volume fisso, transizione,
    // ReplayGain, VU).
    Connections {
        target: Player
        function onModeChanged() { if (root.active >= 0) root.rebuild() }
        function onSettingsChanged() { if (root.active >= 0) root.rebuild() }
        function onConnectedChanged() { if (root.active >= 0) root.rebuild() }
        function onPlayerChanged() { if (root.active >= 0) root.rebuild() }
    }
    signal dataChanged()
    onDataChanged: {
        if (active >= 0) rebuild()
        if (Ui.dialogs && Ui.dialogs.active) Ui.dialogs.formatStatus(cfg.fmtState, cfg.fmtMsg, cfg.fmtPct)
    }
    // dopo ogni comando si rilegge tutto (come want_load nel thread C)
    function post(url, body, cb) { Api.post(url, body || {}, function(ok, d, st) { if (cb) cb(ok, d, st); cfg.load() }, 12000) }
    function send(method, url, body) { Api.send(method, url, body || {}, function() { cfg.load() }, 12000) }
    function lms(params) { Player.cmd(params); reloadLater.restart() }

    // Switching between this device's own Lyrion and one on the network only
    // half-applies while the box is running (squeezelite reconnects, but the
    // services around it — and every address already resolved — do not), so
    // the change is confirmed as a restart and the reboot follows the POST.
    function askRoleReboot(apply) {
        Ui.dialogs.confirm(Tr.t("settings.multiroom.role.rebootWarning"),
                           Tr.t("settings.controls.reboot"), false,
                           function(ok) { if (ok) apply() })
    }
    Timer { id: reloadLater; interval: 400; onTriggered: cfg.load() }
    // while Lyrion scans, the Library rows follow it (only with that section open)
    Timer { interval: 2000; repeat: true; running: cfg.lib.scanning && root.active >= 0 && root.secs[root.active].id === "multiroom"; onTriggered: cfg.loadLibrary() }
    function fmtDuration(sec) {
        var d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60)
        if (d > 0) return d + " " + Tr.t("settings.lyrion.days") + " " + h + " h"
        if (h > 0) return h + " h " + m + " min"
        return m + " min"
    }
    function fmtWhen(ts) { return Qt.formatDateTime(new Date(ts * 1000), I18n.lang === "it" ? "dd/MM/yyyy HH:mm" : "yyyy-MM-dd HH:mm") }
    function setPref(name, value) { Player.cmd(["playerpref", name, value]) }

    function enter() { cfg.load(); goRoot() }
    function say(text, err) { msg = text; msgErr = !!err; rebuild() }
    function goRoot() { active = -1; msg = ""; pendAct = ""; backTo = ""; rows = []; page.contentY = 0; appear() }
    function goBack() { if (backTo) openSection(backTo); else goRoot() }
    function openSection(i, mark) {
        if (typeof i === "string") i = secIndex(i)
        if (i < 0 || i >= secs.length) return
        var id = secs[i].id
        active = i; msg = ""; pendAct = ""; countdown = 0; backTo = ""
        audioSel = ""; sshUser = ""; sshPass = ""; nameEdit = ""; hostEdit = ""
        band = -1; bandAdd = -1; bandShare = -1; brId = ""; pickOwner = 0; pickNew = ""
        btBand = -1; btNameEdit = ""; btBusy = false; btScanning = false
        wizReset()
        if (id === "timezone" && timezones.length === 0) Api.get(cfg.api("/timezones"), function(ok, d) { if (ok && d && d.timezones) { timezones = d.timezones.map(String); rebuild() } })
        if (id === "webRemote") cfg.mintToken()
        if (id === "multiroom" && cfg.lmsMode === "follow") cfg.loadDiscover()
        if (id === "multiroom") cfg.loadLibrary()
        if (id === "btSpeakers") { btBusy = true; cfg.loadBt() }
        if (id === "vuMeters") cfg.loadStore(true)
        if (id === "animations") cfg.loadAnimStore(true)
        if (id === "thirdPartyNotices" && !thirdParty) { try { thirdParty = JSON.parse(Sys.readFile(I18n.dir + "/third_party.json")) } catch (e) { thirdParty = null } }
        rebuild(); page.contentY = 0; appear()
        if (mark) { pendingMark = mark; markTimer.restart() }
    }
    // Scrolls to the row carrying `mark` (a row field) and flashes it once:
    // how the status plate's lights land on the setting behind them.
    property string pendingMark: ""
    Timer { id: markTimer; interval: 60; onTriggered: root.showMark(root.pendingMark) }
    function findMark(item, mark) {
        var kids = item.children
        for (var i = 0; i < kids.length; i++) {
            var k = kids[i]
            if (k.modelData && k.modelData.mark === mark) return k
            var f = findMark(k, mark)
            if (f) return f
        }
        return null
    }
    function showMark(mark) {
        pendingMark = ""
        var it = mark ? findMark(panelRows, mark) : null
        if (!it) return
        var p = it.mapToItem(body, 0, 0)
        page.contentY = Math.max(0, Math.min(p.y - 24, page.contentHeight - page.height))
        markFlash.x = p.x - 6; markFlash.y = p.y - 6
        // the slot is the row plus the gap below it: frame the row alone
        var rowH = it.children.length ? it.children[0].height : it.height
        markFlash.width = it.width + 12; markFlash.height = rowH + 12
        markFlashAnim.restart()
    }
    // ─── procedura guidata "cartella di rete" ──────────────────────────────
    function wizReset() {
        wiz = -1; wizManual = false; wizHost = ""; wizName = ""; wizShare = ""
        wizUser = ""; wizPw = ""; wizRw = false; wizBusy = false
        wizErr = ""; wizDetail = ""; wizDetailOpen = false
        wizShares = []; wizNeedsAuth = false; wizCanList = true; wizNoClient = false
        scanState = ""; scanPct = 0; scanHosts = []
        scanPoll.stop()
    }
    function wizOpen() { wizReset(); wiz = 0; wizScan() }
    function wizScan() {
        wizManual = false; wizErr = ""; wizDetail = ""
        scanState = "running"; scanPct = 0; scanHosts = []
        Api.post(cfg.src("/api/sources/smb/discover"), {}, function() { scanPoll.restart(); wizPoll() }, 10000)
        rebuild()
    }
    function wizPoll() {
        Api.get(cfg.src("/api/sources/smb/discover"), function(ok, d) {
            if (!ok || !d || typeof d !== "object") return
            scanState = String(d.state || ""); scanPct = Number(d.progress || 0)
            scanHosts = (d.hosts || []).map(function(h) {
                return { ip: String(h.ip || ""), name: String(h.name || "") } })
            // Senza smbclient (apparecchio non ancora aggiornato) le cartelle
            // non si possono elencare: si passa a scriverne il nome.
            if (d.tools && d.tools.shares === false) { wizCanList = false; wizNoClient = true }
            if (scanState !== "running") scanPoll.stop()
            if (wiz === 0) rebuild()
        }, 8000)
    }
    Timer { id: scanPoll; interval: 900; repeat: true; onTriggered: root.wizPoll() }

    function wizHostName(ip) {
        for (var i = 0; i < scanHosts.length; i++) if (scanHosts[i].ip === ip) return scanHosts[i].name
        return ""
    }
    function wizFail(d, fallbackKey) {
        wizErr = (d && d.message) ? String(d.message) : Tr.t(fallbackKey)
        wizDetail = (d && d.detail) ? String(d.detail) : ""
        wizDetailOpen = false
    }
    function wizPickHost(ip, name) {
        scanPoll.stop()
        wizHost = ip; wizName = name || ip; wizShare = ""; wizShares = []
        wizNeedsAuth = false; wizErr = ""; wizDetail = ""; wiz = 1
        if (wizCanList) wizLoadShares(); else rebuild()
    }
    // Username and password are asked in a window, only when the device (or
    // the folder) turns out to want them: there are no fields to fill in on
    // the page. `refused` = the previous attempt was turned down, and the
    // window says so. Cancel leaves the step as it is.
    function wizAskAuth(refused, retry) {
        if (wiz < 0 || !Ui.dialogs) return
        var dev = wizName || wizHost
        Ui.dialogs.login(Tr.tf("sources.wizard.signInTo", "device", dev),
                         Tr.t("sources.wizard.authHint"), wizUser,
                         refused ? Tr.t("sources.wizard.wrongPassword") : "",
                         function(u, p) {
                             if (u === null || wiz < 0) return
                             wizUser = u; wizPw = p; wizNeedsAuth = true
                             retry()
                         })
    }
    function wizLoadShares() {
        wizBusy = true; wizErr = ""; wizDetail = ""; rebuild()
        var tried = wizUser !== ""
        Api.post(cfg.src("/api/sources/smb/shares"),
                 { server: wizHost, username: wizUser, password: wizPw },
                 function(ok, d) {
                     wizBusy = false
                     if (wiz !== 1) return
                     if (!ok || !d || typeof d !== "object" || d.success === false) {
                         // Wrong password: ask again. Only a real failure
                         // falls back to typing the folder name by hand.
                         if (d && d.code === "msg.smbBadCredentials") {
                             wizNeedsAuth = true; rebuild()
                             wizAskAuth(tried, wizLoadShares)
                             return
                         }
                         wizFail(d, "sources.wizard.listFailed")
                         wizCanList = false
                         rebuild(); return
                     }
                     wizNeedsAuth = !!d.needs_auth
                     wizShares = (d.shares || []).map(function(x) {
                         return { name: String(x.name || ""), comment: String(x.comment || "") } })
                     rebuild()
                     // the list itself is behind a login
                     if (d.needs_auth && !wizShares.length) wizAskAuth(tried, wizLoadShares)
                 }, 40000)
    }
    function wizPickShare(name) {
        wizShare = name; wizErr = ""; wizDetail = ""; wizBusy = true; rebuild()
        var tried = wizUser !== ""
        Api.post(cfg.src("/api/sources/smb/test"),
                 { server: wizHost, share: name, username: wizUser, password: wizPw },
                 function(ok, d) {
                     wizBusy = false
                     if (wiz !== 1) return
                     if (ok && d && typeof d === "object" && d.success !== false) { wiz = 2; rebuild(); return }
                     // A folder that wants a login asks for it right here,
                     // not with an error and not at the end as a failed mount.
                     if (d && d.code === "msg.smbBadCredentials") {
                         wizNeedsAuth = true; rebuild()
                         wizAskAuth(tried, function() { wizPickShare(name) })
                         return
                     }
                     wizFail(d, "sources.wizard.openFailed")
                     rebuild()
                 }, 40000)
    }
    function wizAdd() {
        if (!wizHost || !wizShare) return
        var label = (wizName || wizHost) + " / " + wizShare
        wizBusy = true; wizErr = ""; wizDetail = ""; rebuild()
        Api.post(cfg.src("/api/sources/smb"),
                 { server: wizHost, share: wizShare, username: wizUser, password: wizPw, rw: wizRw },
                 function(ok, d) {
                     wizBusy = false
                     if (ok && d && typeof d === "object" && d.success !== false) {
                         wizReset(); band = 0; cfg.load()
                         say(Tr.tf("sources.wizard.added", "name", label))
                         return
                     }
                     if (wiz < 0) return
                     if (d && d.code === "msg.smbBadCredentials") {
                         wiz = 1; wizNeedsAuth = true; rebuild()
                         wizAskAuth(wizUser !== "", function() { wizPickShare(wizShare) })
                         return
                     }
                     wizFail(d, "sources.wizard.openFailed")
                     rebuild()
                 }, 60000)
    }

    function appear() { fadeAnim.restart() }
    NumberAnimation { id: fadeAnim; target: body; property: "opacity"; from: 0; to: 1; duration: 120; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
    Keys.onEscapePressed: if (active >= 0) goBack()

    // ─── costruzione delle righe ───────────────────────────────────────────
    property var _stack: []
    property var _cur: []
    function push(r) { _cur.push(r); return r }
    function begin(children) { _stack.push(_cur); _cur = children }
    function end() { _cur = _stack.pop() }
    function help(key, px) { return push({ type: "help", label: Tr.t(key), px: px || 14 }) }
    function helpText(text, px) { return push({ type: "help", label: text, px: px || 14 }) }
    function label(key, px) { return push({ type: "label", label: Tr.t(key), px: px || 16 }) }
    function labelText(text, px) { return push({ type: "label", label: text, px: px || 16 }) }
    function info(l, v) { return push({ type: "info", label: l, value: v }) }
    function toggle(l, sub, on, act, arg) { return push({ type: "toggle", label: l, value: sub || "", on: on, act: act, arg: arg || "" }) }
    function option(l, sub, arg, sel, act) { return push({ type: "option", label: l, value: sub || "", arg: arg || "", sel: sel, act: act }) }
    function action(l, act, style) { return push({ type: "action", label: l, act: act, style: style || "accent" }) }
    function note(text, tone, icon, px) { return push({ type: "note", label: text, tone: tone || "dark", icon: icon || "", px: px || 14, center: !icon }) }
    function input(ph, val, act, pw, arg) { return push({ type: "input", label: ph, value: val || "", act: act, on: !!pw, arg: arg || "" }) }
    function qr(payload, l) { return push({ type: "qr", value: payload, label: l || "" }) }
    function code(text) { return push({ type: "code", label: text }) }
    function sep() { return push({ type: "sep" }) }
    function confirmRow(prompt, ok, act) { return push({ type: "confirm", label: prompt, value: ok, act: act }) }
    function grid(cells) { return push({ type: "grid", cols: cells.length, cells: cells }) }
    function cell(l, arg, sel, act, extra) { var r = { type: "option", label: l, arg: arg || "", sel: sel, act: act, center: true, value: "" }; if (extra) for (var k in extra) r[k] = extra[k]; return r }
    function acell(l, act, style, extra) { var r = { type: "action", label: l, act: act, style: style || "accent" }; if (extra) for (var k in extra) r[k] = extra[k]; return r }
    function bandRow(icon, title, summary, open, act, arg, nested) { return push({ type: "band", icon: icon, label: title, value: summary || "", on: open, act: act, arg: arg, style: nested ? "nested" : 0, children: [] }) }
    function mini(r, l, act, style, dim, arg) { r.mini = r.mini || []; r.mini.push({ label: l, act: act, style: style || "accent", dim: !!dim, arg: arg !== undefined ? arg : r.arg }) }
    function miniIcon(r, icon, act, style, arg) { r.mini = r.mini || []; r.mini.push({ icon: icon, act: act, style: style || "accent", arg: arg !== undefined ? arg : r.arg }) }
    function srcRow(name, tag, sub, usage, id, ok) { return push({ type: "src", label: name, extra: tag || "", value: sub || "", sub2: usage || "", arg: id || "", danger: !ok, hh: usage ? 76 : 60 }) }
    function check(l, on, act) { return push({ type: "check", label: l, on: on, act: act }) }
    function dir(name, act) { return push({ type: "dir", label: name, arg: name, act: act }) }
    function miniRow() { return push({ type: "mini", mini: [] }) }
    function box(fn) { var b = push({ type: "box", children: [] }); begin(b.children); fn(); end(); return b }

    function humanSize(bytes) {
        var gb = bytes / (1024 * 1024 * 1024)
        if (!(gb > 0)) return ""
        if (gb >= 1000) return (gb / 1024).toFixed(1) + " TB"
        if (gb >= 10) return Math.round(gb) + " GB"
        return gb.toFixed(1) + " GB"
    }
    function pref(which) { return which === "transition" ? Player.prefTransitionType : which === "duration" ? Player.prefTransitionDur : Player.prefReplayGain }
    readonly property bool havePlayer: Player.connected

    // 🚨 Rebuilding the rows destroys the very field the on-screen keyboard is
    // typing into: SettingsRows' Repeater gets a brand new array, so every
    // delegate is recreated while the keyboard still points at the old one.
    // From that moment the keys only reached its own preview and confirming
    // left the box empty — and one character was enough to trigger it, since
    // fieldSet() restarts dimRefresh (150 ms). In Electron the input is the
    // same DOM node for the whole edit; the equivalent here is to hold the
    // rebuilds back until the keyboard closes.
    property bool rebuildPending: false
    Connections {
        target: Ui.vk
        function onActiveChanged() { if (Ui.vk && !Ui.vk.active && root.rebuildPending) root.rebuild() }
    }
    function rebuild() {
        if (Ui.vk && Ui.vk.active) { rebuildPending = true; return }
        rebuildPending = false
        _stack = []; _cur = []
        if (active >= 0) {
            switch (secs[active].id) {
            case "language": secLanguage(); break
            case "sources": secSources(); break
            case "audio": secAudio(); break
            case "playback": secPlayback(); break
            case "vuMeters": secVuMeters(); break
            case "animations": secAnimations(); break
            case "library": secLibrary(); break
            case "multiroom": secMultiroom(); break
            case "btSpeakers": secBtSpeakers(); break
            case "alarm": secAlarm(); break
            case "network": secNetwork(); break
            case "webRemote": secWebremote(); break
            case "webRemoteIos": secWebremoteIos(); break
            case "ssh": secSsh(); break
            case "pointer": secPointer(); break
            case "uiResolution": secUires(); break
            case "uiRefresh": secUirefresh(); break
            case "displayMode": secDisplaymode(); break
            case "timezone": secTimezone(); break
            case "systemInfo": secSysinfo(); break
            case "updates": secUpdates(); break
            case "systemControls": secSysctl(); break
            case "thirdPartyNotices": secThirdparty(); break
            case "netCheck": secNetcheck(); break
            }
            if (msg) note(msg, msgErr ? "red" : "dark")
        }
        // a rebuild hands the Repeater a new array: while the old rows are
        // gone the page is empty and the Flickable snaps to the top. Put the
        // reader back where they were (a periodic reload must not scroll).
        var cy = page.contentY
        rows = _cur
        Qt.callLater(function() { page.contentY = Math.max(0, Math.min(cy, page.contentHeight - page.height)) })
    }

    // ── sezioni ────────────────────────────────────────────────────────────
    function secLanguage() {
        help("settings.language.help")
        var cur = I18n.lang
        var r = option("English", "", "en", cur === "en", "lang"); r.hh = 52; r.icon = "check"
        r = option("Italiano", "", "it", cur === "it", "lang"); r.hh = 52; r.icon = "check"
    }
    function folderPicker(pickLabel) {
        box(function() {
            var hd = info(cfg.pkPath || "/", ""); hd.style = "seg"; hd.px = 12; hd.hh = 28
            mini(hd, Tr.t("sources.subpathUp"), "pick_up", "accent", !cfg.pkHasParent)
            if (pickBusy) helpText(Tr.t("common.loading"), 12)
            else if (!cfg.pkDirs.length) helpText(Tr.t("sources.subpathNoSubfolders"), 12)
            else for (var i = 0; i < cfg.pkDirs.length; i++) dir(cfg.pkDirs[i], "pick_into")
            var inp = { type: "input", label: Tr.t("sources.newFolderPlaceholder"), value: pickNew, act: "pick_new", span: 3 }
            var cr = acell(Tr.t("sources.newFolderCreate"), "pick_create", "accent", { px: 12, hh: 46, dim: !pickNew || !cfg.pkPath })
            var g = push({ type: "grid", cols: 4, cells: [inp, cr] })
            var use = action(pickLabel, "pick_use", "accent"); use.icon = "plus"; use.dim = !cfg.pkPath
        })
    }
    function subpathBrowser() {
        box(function() {
            var hd = info(cfg.brPath || "/", Tr.t("common.back")); hd.style = "seg"; hd.px = 12; hd.hh = 24; hd.act = "br_close"
            if (brBusy) { helpText(Tr.t("common.loading"), 12); return }
            var bt = miniRow()
            mini(bt, Tr.t("sources.subpathUp"), "br_up", "accent", !cfg.brHasParent, "")
            mini(bt, Tr.t("sources.subpathUseHere"), "br_here", "goldsoft", false, "")
            mini(bt, Tr.t("sources.subpathUseRoot"), "br_root", "accent", !cfg.brPath, "")
            if (!cfg.brDirs.length) { helpText(Tr.t("sources.subpathNoSubfolders"), 12); return }
            for (var i = 0; i < cfg.brDirs.length; i++) dir(cfg.brDirs[i], "br_into")
        })
    }
    function bandActiveSources() {
        if (!cfg.sources.length) help("sources.none")
        for (var i = 0; i < cfg.sources.length; i++) {
            var s = cfg.sources[i], type = String(s.type || ""), smb = type === "smb"
            var mountb = smb || type === "internal" || type === "usb"
            var sub = String(s.subpath || ""), mount = String(s.mountpoint || "")
            var tag = smb ? (s.rw ? "SMB · RW" : "SMB") : type === "internal" ? Tr.t("sources.internal.tag") : type === "usb" ? "USB" : Tr.t("sources.local")
            var line = smb ? "//" + s.server + "/" + s.share + " → " + mount + (sub ? "/" + sub : "") : mountb ? mount + (sub ? "/" + sub : "") : String(s.path || "")
            var usage = ""
            var tot = s.usage && s.usage.total ? Number(s.usage.total) : 0
            if (tot > 0) usage = Tr.tf("sources.freeOf", "free", humanSize(Number(s.usage.free || 0))).replace("{total}", humanSize(tot))
            var ok = mountb ? !!s.mounted : !!s.exists
            var id = String(s.id || "")
            var r = srcRow(String(s.name || ""), tag, line, usage, id, ok)
            if (smb) mini(r, Tr.t(s.rw ? "sources.smbMakeRo" : "sources.smbMakeRw"), "src_rw", s.rw ? "goldsoft" : "accent", false)
            if (mountb) mini(r, Tr.t("sources.subpathPick"), "src_browse", "accent", !s.mounted)
            miniIcon(r, "trash-2", "src_del", "darkred")
            if (brId === id) subpathBrowser()
        }
        if (cfg.usb.length) {
            sep()
            var h = labelText(Tr.t("sources.usbAttention"), 16); h.icon = "alert-triangle"
            for (var k = 0; k < cfg.usb.length; k++) {
                var u = cfg.usb[k], fs = String(u.fstype || ""), sz = String(u.size || "")
                var utag = "USB" + (fs ? " " + fs : "") + (sz ? " · " + sz : "")
                var err = u.needs_format ? Tr.t("sources.usbNeedsFormat") : Tr.t("sources.usbMountError") + ": " + String(u.error || "")
                var uid = String(u.path || u.id || "")
                var ur = srcRow(String(u.label || u.model || "USB"), utag, err, "", uid, false)
                if (!u.needs_format) mini(ur, Tr.t("sources.usbRetry"), "usb_retry", "goldsoft", !uid)
            }
        }
    }
    function bandAddSmb() {
        // Niente piu' caselle qui dentro: si entra nella procedura guidata, che
        // cerca i dispositivi da sola e chiede una cosa per volta.
        help("sources.wizard.intro", 13)
        var go = action(Tr.t("sources.wizard.searchButton"), "wiz_open", "gold")
        go.icon = "search"; go.hh = 52; go.bold = true
        var mr = miniRow()
        mini(mr, Tr.t("sources.wizard.typeItMyself"), "wiz_manual_open", "accent", false, "")
    }
    function bandAddInternal() {
        if (!cfg.disks.length) { help("sources.internal.none"); return }
        for (var i = 0; i < cfg.disks.length; i++) {
            var d = cfg.disks[i]
            var tag = humanSize(d.size) + (d.adopted ? " · " + Tr.t("sources.internal.adoptedBadge") : d.hasData ? " · " + Tr.t("sources.internal.hasData") : "")
            var r = srcRow(d.model || d.path, tag, d.path, "", d.path, true); r.smin = i; r.hh = 60
            r.extraTone = d.adopted ? "green" : d.hasData ? "dim" : ""   // badge: text-green-400 / silver/60
            if (!d.adopted) {
                if (d.parts.length === 1) mini(r, Tr.t("sources.internal.adopt"), "disk_adopt", "accent", false)
                mini(r, Tr.t("sources.internal.format"), "disk_format", "darkred", false, String(i))
            }
            if (!d.adopted && d.parts.length > 1)
                for (var k = 0; k < d.parts.length; k++) {
                    var p = d.parts[k]
                    var pr = info(p.path + " · " + p.fs + (p.label ? " · " + p.label : ""), ""); pr.style = "seg"; pr.hh = 28; pr.arg = p.path
                    mini(pr, Tr.t("sources.internal.adopt"), "disk_adopt", "goldsoft", false, p.path)
                }
        }
        if (cfg.fmtState && cfg.fmtState !== "idle") note(cfg.fmtPct > 0 ? cfg.fmtMsg + " (" + cfg.fmtPct + "%)" : cfg.fmtMsg, "dark")
    }
    function bandShared() {
        help("sources.shareHint")
        if (cfg.smbShares.length) {
            box(function() {
                help("sources.internal.smbHelp")
                for (var i = 0; i < cfg.smbShares.length; i++) {
                    var r = info(cfg.smbShares[i], ""); r.px = 14; r.hh = 36
                    r.extra = "\\\\" + (cfg.smbIp || cfg.smbHost) + "\\" + cfg.smbShares[i]
                }
                var u = info(Tr.t("sources.internal.smbUser"), cfg.smbUser); u.mono = true; u.style = "seg"; u.hh = 28
                var masked = smbShowPw ? cfg.smbPass : "•".repeat(Math.max(1, Math.min(10, cfg.smbPass.length || 10)))
                var pw = info(Tr.t("sources.internal.smbPass"), masked); pw.mono = true; pw.style = "seg"; pw.hh = 28; pw.act = "smb_show"; pw.icon = smbShowPw ? "eye-off" : "eye"
                helpText(Tr.t("sources.internal.smbRegenerateHint"), 12)
                var rg = miniRow(); mini(rg, Tr.t("sources.internal.smbRegenerate"), "smb_regen", "accent", false, "")
            })
        } else help("sources.shareNone")
        var b = bandRow("folder-plus", Tr.t("sources.shareLocal"), "", bandShare === 0, "band_share", "0", true)
        if (bandShare === 0) { begin(b.children); help("sources.localSambaHint"); folderPicker(Tr.t("sources.shareThisFolder")); end() }
    }
    // ─── la procedura guidata, un passo per schermata ──────────────────────
    function wizPage() {
        labelText(Tr.t("sources.wizard.title"), 18)
        if (wiz === 0) wizStepFind()
        else if (wiz === 1) wizStepShare()
        else wizStepConfirm()
        if (wizErr) {
            note(wizErr, "darkred", "alert-triangle", 14)
            if (wizDetail) {
                // Il testo grezzo di mount.cifs resta raggiungibile, ma non e'
                // mai l'unica cosa sullo schermo: era il vecchio comportamento.
                var dr = miniRow()
                mini(dr, Tr.t(wizDetailOpen ? "sources.wizard.hideDetail" : "sources.wizard.showDetail"), "wiz_detail", "accent", false, "")
                if (wizDetailOpen) code(wizDetail)
            }
        }
        var nav = miniRow()
        mini(nav, Tr.t("common.cancel"), "wiz_close", "accent", false, "")
        if (wiz > 0) mini(nav, Tr.t("sources.wizard.back"), "wiz_back", "accent", wizBusy, "")
    }
    function wizStepFind() {
        if (wizManual) {
            help("sources.wizard.manualHint", 13)
            input(Tr.t("sources.wizard.addressLabel"), wizHost, "wiz_field", false, "h")
            var go = action(Tr.t("sources.wizard.continue"), "wiz_host_manual", "gold")
            go.hh = 52; go.bold = true; go.dim = !wizHost
            var m0 = miniRow()
            mini(m0, Tr.t("sources.wizard.searchAgain"), "wiz_rescan", "accent", false, "")
            return
        }
        if (scanState === "running") {
            var p = info(Tr.t("sources.wizard.searching"), scanPct + "%"); p.style = "seg"; p.hh = 30
        }
        if (scanHosts.length) {
            label("sources.wizard.foundTitle", 15)
            for (var i = 0; i < scanHosts.length; i++) {
                var h = scanHosts[i]
                // Nome in evidenza e indirizzo sotto: chi cerca "SYNOLOGY" non
                // deve leggere quattro numeri per riconoscerlo.
                var r = option(h.name || h.ip, h.name ? h.ip : "", h.ip, false, "wiz_host"); r.hh = 62
            }
        } else if (scanState !== "running") {
            note(Tr.t("sources.wizard.nothingFound"), "dark")
        }
        var mr = miniRow()
        mini(mr, Tr.t("sources.wizard.searchAgain"), "wiz_rescan", "accent", scanState === "running", "")
        mini(mr, Tr.t("sources.wizard.typeItMyself"), "wiz_manual", "goldsoft", false, "")
    }
    function wizStepShare() {
        helpText(Tr.tf("sources.wizard.onDevice", "device", wizName || wizHost), 13)
        if (wizUser) {
            var who = info(Tr.t("sources.wizard.userLabel"), wizUser); who.style = "seg"; who.hh = 32; who.mono = true
            mini(who, Tr.t("sources.wizard.changeUser"), "wiz_needauth", "accent", wizBusy, "")
        }
        if (wizBusy) { help("sources.wizard.loadingShares", 13); return }
        if (!wizCanList) {
            // Perche' non c'e' un elenco da toccare: senza questa riga si
            // finiva su una casella vuota senza sapere il motivo.
            if (wizNoClient) help("sources.wizard.noClientHint", 13)
            help("sources.wizard.typeShareHint", 13)
            input(Tr.t("sources.wizard.shareLabel"), wizShare, "wiz_field", false, "s")
            var c = action(Tr.t("sources.wizard.continue"), "wiz_share_manual", "gold")
            c.hh = 52; c.bold = true; c.dim = !wizShare
            return
        }
        if (!wizShares.length) {
            if (!wizNeedsAuth) note(Tr.t("sources.wizard.noShares"), "dark")
        } else {
            label("sources.wizard.pickShare", 15)
            for (var i = 0; i < wizShares.length; i++) {
                var sh = wizShares[i]
                var rr = option(sh.name, sh.comment, sh.name, wizShare === sh.name, "wiz_share"); rr.hh = 58
            }
        }
        var mr = miniRow()
        if (!wizUser) mini(mr, Tr.t("sources.wizard.needPassword"), "wiz_needauth", "accent", wizBusy, "")
        mini(mr, Tr.t("sources.wizard.typeItMyself"), "wiz_share_type", "accent", false, "")
    }
    function wizStepConfirm() {
        var d = info(Tr.t("sources.wizard.device"), wizName || wizHost); d.hh = 44
        var f = info(Tr.t("sources.wizard.folder"), wizShare); f.hh = 44
        if (wizUser) { var u = info(Tr.t("sources.wizard.userLabel"), wizUser); u.hh = 40 }
        help("sources.wizard.writeHint", 13)
        check(Tr.t("sources.wizard.allowWrite"), wizRw, "wiz_rw")
        var add = action(Tr.t("sources.wizard.addNow"), "wiz_add", "gold")
        add.icon = "plus"; add.hh = 54; add.bold = true; add.dim = wizBusy
        if (wizBusy) help("sources.mounting", 13)
    }
    // Prima sorgente: invece di "Nessuna sorgente" si chiede dov'e' la musica,
    // in parole di tutti i giorni, e ogni risposta porta dritta al pezzo giusto.
    function sourcesWhere() {
        label("sources.where.title", 18)
        help("sources.where.hint", 13)
        var picks = [["sources.where.network", "sources.where.networkHint", "where_net"],
                     ["sources.where.disk", "sources.where.diskHint", "where_disk"],
                     ["sources.where.local", "sources.where.localHint", "where_local"]]
        for (var i = 0; i < picks.length; i++) {
            var r = option(Tr.t(picks[i][0]), Tr.t(picks[i][1]), "", false, picks[i][2])
            r.hh = 72; r.style = "border"; r.icon = "chevron-right"
        }
        sep()
    }
    function secSources() {
        if (wiz >= 0) { wizPage(); return }
        help("settings.sources.help"); help("sources.autoApplyHint", 12)
        if (!cfg.sources.length) sourcesWhere()
        var sum = cfg.sources.length ? Tr.tf("sources.countSummary", "count", String(cfg.sources.length)) : Tr.t("sources.none")
        var b0 = bandRow("library", Tr.t("sources.active"), sum, band === 0, "band", "0", false)
        if (band === 0) { begin(b0.children); bandActiveSources(); end() }
        var b1 = bandRow("plus", Tr.t("sources.addSource"), Tr.t("sources.addSourceHint"), band === 1, "band", "1", false)
        if (band === 1) {
            begin(b1.children)
            var s0 = bandRow("network", Tr.t("sources.addSmb"), "", bandAdd === 0, "band_add", "0", true)
            if (bandAdd === 0) { begin(s0.children); bandAddSmb(); end() }
            var s1 = bandRow("hard-drive", Tr.t("sources.internal.title"), "", bandAdd === 1, "band_add", "1", true)
            if (bandAdd === 1) { begin(s1.children); bandAddInternal(); end() }
            var s2 = bandRow("folder-plus", Tr.t("sources.addLocal"), "", bandAdd === 2, "band_add", "2", true)
            if (bandAdd === 2) { begin(s2.children); folderPicker(Tr.t("sources.useThisFolder")); end() }
            end()
        }
        var b2 = bandRow("list-music", Tr.t("sources.playlistdir.title"), cfg.pldir || Tr.t("sources.playlistdir.unset"), band === 2, "band", "2", false)
        if (band === 2) {
            begin(b2.children)
            help("sources.playlistdir.hint")
            var r = srcRow(cfg.pldir || Tr.t("sources.playlistdir.unset"), "", "", "", "", true); r.hh = 44; r.px = 12
            mini(r, pickOwner === 2 ? Tr.t("common.close") : Tr.t("sources.playlistdir.pick"), "pick_open", "accent", false, "")
            mini(r, Tr.t("sources.playlistdir.default"), "pldir_default", "accent", !cfg.pldirDef || cfg.pldirDefault, "")
            if (pickOwner === 2) folderPicker(Tr.t("sources.playlistdir.use"))
            end()
        }
        var sum3 = cfg.smbShares.length ? Tr.tf("sources.shareCount", "count", String(cfg.smbShares.length)) : Tr.t("sources.shareNone")
        var b3 = bandRow("share-2", Tr.t("sources.shareTitle"), sum3, band === 3, "band", "3", false)
        if (band === 3) { begin(b3.children); bandShared(); end() }
    }
    function secAudio() {
        help("settings.audio.help")
        if (!cfg.audio.length) { note(Tr.t("settings.audio.unavailable"), "dark"); return }
        var sel = audioSel || cfg.audioCur
        for (var i = 0; i < cfg.audio.length; i++) {
            var a = cfg.audio[i]
            var r = option(a.id === "default" ? Tr.t("settings.audio.defaultDevice") : a.name, a.id, a.id, sel === a.id, "audio_pick"); r.hh = 60; r.mono = true
        }
        grid([acell(Tr.t("settings.audio.refreshList"), "audio_refresh", "accent", { icon: "rotate-cw", hh: 48 }),
              acell(Tr.t("settings.audio.setOutput"), "audio_apply", "gold", { icon: "volume-2", bold: true, hh: 48 })])
    }
    // Playback prefs, alarms and the sync group are THIS device's: while
    // another player is being driven they are hidden behind a note (#99),
    // so nothing gets written to somebody's phone
    function remoteNote() {
        if (Player.isOwn) return false
        note(Tr.tf("settings.remotePlayer.note", "name", Player.playerName), "dark", "speaker")
        action(Tr.t("settings.remotePlayer.back"), "player_back", "gold")
        return true
    }
    function secPlayback() {
        help("settings.playback.help")
        // The player prefs below belong to this device's player: hidden while
        // another one is driven (#99). The auto-open is about this screen, so
        // it stays reachable either way.
        if (!remoteNote()) playerPrefs()
        label("settings.playback.autoExpand", 14); help("settings.playback.autoExpandHelp", 12)
        var AE = [0, 3, 5, 10, 15], ae = []
        for (var m = 0; m < 5; m++) ae.push(cell(AE[m] === 0 ? Tr.t("settings.playback.rgOff") : AE[m] + "s", String(AE[m]), cfg.autoexpand === AE[m], "autoexpand", { hh: 44 }))
        grid(ae)
    }
    // The VU meters have a section of their own: the switch, then the looks
    // to choose from, each with a still preview of the meters. About this
    // screen, not the player, so it never hides behind remoteNote().
    function secVuMeters() {
        help("settings.vuMeters.help")
        toggle(Tr.t("settings.playback.vuMeter"), Tr.t("settings.playback.vuMeterHelp"), cfg.vuMeter, "vumeter")
        if (!cfg.vuMeter) {                    // their place can go to an animation
            note(Tr.t("settings.vuMeters.animationsHint"), "dark", "disc-3")
            grid([acell(Tr.t("settings.vuMeters.chooseAnimation"), "open_animations", "accent", { icon: "disc-3", hh: 44 })])
        }
        var lang = I18n.lang
        if (cfg.vuMeter && cfg.vuStyles.length > 1) {
            label("settings.playback.vuStyle", 14); help("settings.playback.vuStyleHelp", 12)
            var st = []
            for (var v = 0; v < cfg.vuStyles.length; v++) {
                var nm = cfg.vuStyles[v].name || {}
                st.push({ type: "vuskin", label: String(nm[lang] || nm.en || cfg.vuStyles[v].id), arg: cfg.vuStyles[v].id,
                          sel: Player.vuStyle === cfg.vuStyles[v].id, act: "vu_style" })
                if (st.length === 2 || v === cfg.vuStyles.length - 1) {
                    if (st.length === 1) st.push({ type: "help", label: "" })
                    grid(st); st = []
                }
            }
        }
        vuStoreRows(lang)
    }
    // More looks to download: a card per skin of the store, with its preview,
    // and what can be done with it
    function vuStoreRows(lang) {
        var vs = cfg.vuStore
        label("settings.vuMeters.storeTitle", 14); help("settings.vuMeters.storeHelp", 12)
        if (vs.error) note(vs.error.message || "", vs.skins.length ? "dark" : "red")
        if (!vs.skins.length) {
            if (!vs.loaded || vs.checking) note(Tr.t("settings.vuMeters.storeLoading"), "dark")
            else if (!vs.error) note(Tr.t("settings.vuMeters.storeEmpty"), "dark")
        }
        var cards = []
        for (var i = 0; i < vs.skins.length; i++) {
            var k = vs.skins[i], nm = k.name || {}
            var mb = (Number(k.size || 0) / 1048576).toFixed(1).replace(".", lang === "it" ? "," : ".") + " MB"
            var state = k.job === "downloading" ? "downloading" : k.job === "installing" ? "installing"
                      : !k.supported ? "unsupported" : k.update ? "update" : k.installed ? "installed" : "available"
            cards.push({ type: "vustore", label: String(nm[lang] || nm.en || k.id), arg: k.id, preview: k.preview || "",
                         meta: [k.author || "", mb].filter(function(x) { return !!x }).join(" · "),
                         state: state, isNew: !!k.new, err: k.jobError ? String(k.jobError.message || "") : "",
                         act: state === "installed" ? "vu_remove" : "vu_install" })
            if (cards.length === 2 || i === vs.skins.length - 1) {
                if (cards.length === 1) cards.push({ type: "help", label: "" })
                grid(cards); cards = []
            }
        }
        if (vs.loaded && !vs.checking && !vs.busy)
            grid([acell(Tr.t("settings.vuMeters.storeCheck"), "vu_check", "accent", { icon: "rotate-cw", hh: 44 })])
    }
    // Now Playing animations: a CD, a vinyl record or a cassette in the VU
    // meters' place. Only with the VU meters off; while they are on, a note
    // and the button to turn them off. Each card is a still of the scene.
    function secAnimations() {
        help("settings.animations.help")
        var lang = I18n.lang
        if (cfg.vuMeter) {
            note(Tr.t("settings.animations.vuOn"), "dark")
            action(Tr.t("settings.animations.turnOffVu"), "anim_vu_off", "accent")
        } else {
            // the built-in scenes, then the ones downloaded from the store
            var kinds = ["none", "cd", "cdfront", "vinyl", "cassette"].map(function(k) {
                return { id: k, label: Tr.t("settings.animations." + k) }
            })
            for (var s = 0; s < cfg.storeAnims.length; s++) {
                var nm = cfg.storeAnims[s].name || {}
                kinds.push({ id: cfg.storeAnims[s].id, label: String(nm[lang] || nm.en || cfg.storeAnims[s].id) })
            }
            for (var i = 0; i < kinds.length; i += 2) {
                var cards = []
                for (var j = i; j < i + 2; j++)
                    cards.push(j < kinds.length
                               ? { type: "animcard", label: kinds[j].label, arg: kinds[j].id,
                                   sel: Player.npAnimation === kinds[j].id, act: "np_anim" }
                               : { type: "help", label: "" })
                grid(cards)
            }
        }
        animStoreRows(lang)
    }
    // More animations to download: a card per scene of the store
    function animStoreRows(lang) {
        var as = cfg.animStore
        label("settings.animations.storeTitle", 14); help("settings.animations.storeHelp", 12)
        if (as.error) note(as.error.message || "", as.animations.length ? "dark" : "red")
        if (!as.animations.length) {
            if (!as.loaded || as.checking) note(Tr.t("settings.animations.storeLoading"), "dark")
            else if (!as.error) note(Tr.t("settings.animations.storeEmpty"), "dark")
        }
        var cards = []
        for (var i = 0; i < as.animations.length; i++) {
            var k = as.animations[i], nm = k.name || {}
            var mb = (Number(k.size || 0) / 1048576).toFixed(1).replace(".", lang === "it" ? "," : ".") + " MB"
            var state = k.job === "downloading" ? "downloading" : k.job === "installing" ? "installing"
                      : !k.supported ? "unsupported" : k.update ? "update" : k.installed ? "installed" : "available"
            cards.push({ type: "vustore", label: String(nm[lang] || nm.en || k.id), arg: k.id, preview: k.preview || "", icon: "disc-3",
                         meta: [k.author || "", mb].filter(function(x) { return !!x }).join(" · "),
                         state: state, isNew: !!k.new, err: k.jobError ? String(k.jobError.message || "") : "",
                         act: state === "installed" ? "anim_remove" : "anim_install" })
            if (cards.length === 2 || i === as.animations.length - 1) {
                if (cards.length === 1) cards.push({ type: "help", label: "" })
                grid(cards); cards = []
            }
        }
        if (as.loaded && !as.checking && !as.busy)
            grid([acell(Tr.t("settings.animations.storeCheck"), "anim_check", "accent", { icon: "rotate-cw", hh: 44 })])
    }
    // The library: how the albums are shown, a grid of cards or Cover Flow
    // (the same choice as the button in the crumb bar of the album list)
    function secLibrary() {
        help("settings.library.help")
        label("settings.library.albumView", 14); help("settings.library.albumViewHelp", 12)
        var av = Ui.app ? Ui.app.albumView : "grid"
        grid([cell(Tr.t("settings.library.viewGrid"), "grid", av === "grid", "album_view", { hh: 44 }),
              cell(Tr.t("settings.library.viewCoverflow"), "coverflow", av === "coverflow", "album_view", { hh: 44 })])
    }
    function playerPrefs() {
        if (!havePlayer) note(Tr.t("settings.playback.noPlayer"), "dark")
        label("settings.playback.transition", 14)
        var TR = ["settings.playback.transNone", "settings.playback.transCrossfade", "settings.playback.transFadeIn", "settings.playback.transFadeOut", "settings.playback.transFadeInOut"]
        for (var i = 0; i < 5; i += 2) {
            var cells = []
            for (var j = i; j < Math.min(5, i + 2); j++) cells.push(cell(Tr.t(TR[j]), String(j), pref("transition") === String(j), "transition", { hh: 44, dim: !havePlayer }))
            if (cells.length === 1) cells.push({ type: "help", label: "" })
            grid(cells)
        }
        if (pref("transition") !== "0") {
            var dur = Math.max(1, parseInt(pref("duration")) || 1)
            var lab = info(Tr.t("settings.playback.transDuration"), dur + "s"); lab.style = "seg"; lab.tone = "gold"; lab.mono = true; lab.hh = 20
            push({ type: "slider", smin: 1, smax: 15, sval: dur, act: "transdur" })
        }
        label("settings.playback.replayGain", 14).mark = "replaygain"
        var RG = ["settings.playback.rgOff", "settings.playback.rgTrack", "settings.playback.rgAlbum", "settings.playback.rgSmart"]
        for (var k = 0; k < 4; k += 2)
            grid([cell(Tr.t(RG[k]), String(k), pref("rg") === String(k), "replaygain", { hh: 44, dim: !havePlayer }),
                  cell(Tr.t(RG[k + 1]), String(k + 1), pref("rg") === String(k + 1), "replaygain", { hh: 44, dim: !havePlayer })])
        var fv = toggle(Tr.t("settings.playback.fixedVolume"), Tr.t("settings.playback.fixedVolumeHelp"), Player.prefDigitalVol === "0", "fixedvol")
        fv.dim = !havePlayer; fv.mark = "bitperfect"
    }
    function secMultiroom() {
        help("settings.multiroom.help")
        label("settings.multiroom.name.title"); help("settings.multiroom.name.help", 12)
        input(cfg.deviceName || "OsmiumSound", nameEdit || cfg.deviceName, "player_name", false).hh = 50
        var ap = action(Tr.t("settings.multiroom.role.apply"), "player_name_apply", "gold"); ap.bold = true; ap.hh = 44; ap.dim = !nameEdit || nameEdit === cfg.deviceName
        sep()
        label("settings.multiroom.role.title"); help("settings.multiroom.role.help", 12)
        var local = cfg.lmsMode !== "follow"
        grid([cell(Tr.t("settings.multiroom.role.local"), "local", local, "lms_role", { style: "seg", hh: 40 }),
              cell(Tr.t("settings.multiroom.role.follow"), "follow", !local, "lms_role", { style: "seg", hh: 40 })])
        if (local) {
            info(Tr.t("settings.multiroom.server.installed"), cfg.lyrInstalled || Tr.t("settings.multiroom.server.notInstalled")).mono = true
            label("settings.multiroom.server.channel", 12)
            var CH = ["release", "nightly", "dev"]
            for (var i = 0; i < 3; i++) {
                var r = option(Tr.t("settings.multiroom.server.channel_" + CH[i]), "", CH[i], cfg.lyrionChannel === CH[i], "lyrion_channel")
                r.style = "row"; r.hh = 36; r.extra = cfg.lyrChVer[i]
            }
            if (cfg.lyrionChannel !== "release") help("settings.multiroom.server.channelWarning", 12)
            grid([acell(Tr.t(cfg.lyrInstalled ? "settings.multiroom.server.update" : "settings.multiroom.server.install"), "lyrion_install", "gold", { bold: true, hh: 44, icon: "download", span: 3 }),
                  acell("", "lyrion_check", "accent", { hh: 44, icon: "rotate-cw" })])
            _cur[_cur.length - 1].cols = 4
            if (cfg.lyrStatus) note(cfg.lyrPct > 0 ? cfg.lyrStatus + " (" + cfg.lyrPct + "%)" : cfg.lyrStatus, "dark")
            help("settings.updates.lyrionRestartNote", 12)
        } else {
            label("settings.multiroom.role.discoveredLabel", 12)
            var sc = action(Tr.t("settings.multiroom.role.scan"), "lms_discover", "ghost"); sc.icon = "rotate-cw"; sc.hh = 32; sc.px = 12
            for (var k = 0; k < cfg.disc.length; k++) {
                var d = option(cfg.disc[k].name, "", cfg.disc[k].ip, cfg.lmsHost === cfg.disc[k].ip, "lms_pick"); d.style = "row"; d.hh = 36; d.extra = cfg.disc[k].ip
            }
            if (!cfg.disc.length) help("settings.multiroom.role.noneFound", 12)
            var hv = hostEdit || cfg.lmsHost
            input(Tr.t("settings.multiroom.role.hostPlaceholder"), hv, "lms_host", false).hh = 50
            var app = action(Tr.t("settings.multiroom.role.apply"), "lms_apply", "gold"); app.bold = true; app.hh = 44; app.dim = !hv
        }
        sep()
        // Look of the server's own web player (used to be its own "Lyrion
        // Configuration" section, dropped along with the manual server URL).
        label("settings.lyrion.skinLabel"); help("settings.lyrion.skinHint", 12)
        grid([cell(Tr.t("settings.lyrion.skinOsmium"), "osmium", cfg.lmsSkin === "osmium", "lms_skin", { hh: 48 }),
              cell(Tr.t("settings.lyrion.skinMaterial"), "material", cfg.lmsSkin === "material", "lms_skin", { hh: 48 })])
        if (!cfg.lmsSkin || cfg.lmsSkin === "unset") help("settings.lyrion.skinUnset", 12)
        if (cfg.skinState && cfg.skinState !== "done" && cfg.skinState !== "idle") {
            var serr = cfg.skinState === "error"
            note(cfg.skinMsg || Tr.t(serr ? "settings.lyrion.skinFailed" : "settings.lyrion.skinInstalling"), serr ? "red" : "dark")
        }
        sep()
        // the library: what the server has indexed, and a refresh on demand
        label("settings.lyrion.libraryTitle").mark = "library"; help("settings.lyrion.libraryHelp", 12)
        var L = cfg.lib
        if (L.albums >= 0) {
            info(Tr.t("settings.lyrion.libAlbums"), String(L.albums)).mono = true
            info(Tr.t("settings.lyrion.libArtists"), String(L.artists)).mono = true
            info(Tr.t("settings.lyrion.libSongs"), String(L.songs)).mono = true
            if (L.duration > 0) info(Tr.t("settings.lyrion.libDuration"), fmtDuration(L.duration)).mono = true
        }
        info(Tr.t("settings.lyrion.lastScan"), L.lastScan > 0 ? fmtWhen(L.lastScan) : Tr.t("settings.lyrion.never")).mono = true
        if (L.scanning) {
            note(Tr.t("settings.lyrion.scanning") + (L.pct >= 0 ? " " + L.pct + "%" : "") + (L.progress ? " · " + L.progress : ""), "dark")
            var ab = action(Tr.t("settings.lyrion.abortScan"), "lib_abort", "darkred"); ab.hh = 40
        } else {
            var rs = action(Tr.t("settings.lyrion.rescan"), "lib_rescan", "gold"); rs.bold = true; rs.hh = 44; rs.icon = "refresh-cw"
        }
        sep()
        // credits, biographies and album details from MusicBrainz and Wikipedia
        if (cfg.meta.available) {
            label("settings.lyrion.metaTitle").mark = "meta"; help("settings.lyrion.metaHelp", 12)
            toggle(Tr.t("settings.lyrion.metaOnline"), "", cfg.meta.online, "meta_online")
            if (cfg.meta.online) toggle(Tr.t("settings.lyrion.metaPrefetch"), Tr.t("settings.lyrion.metaPrefetchHelp"), cfg.meta.prefetch, "meta_prefetch")
            if (cfg.meta.online && cfg.meta.prefetch && cfg.meta.total > 0)
                info(Tr.t("settings.lyrion.metaProgress"), Tr.tf("settings.lyrion.metaProgressValue", "done", String(cfg.meta.done)).replace("{total}", String(cfg.meta.total))).mono = true
            if (cfg.meta.albums > 0 || cfg.meta.artists > 0) {
                info(Tr.t("settings.lyrion.metaSaved"), Tr.tf("settings.lyrion.metaSavedValue", "albums", String(cfg.meta.albums))
                     .replace("{artists}", String(cfg.meta.artists)).replace("{size}", Meta.bytes(cfg.meta.bytes))).mono = true
                var mc = action(Tr.t("settings.lyrion.metaClear"), "meta_clear", "accent"); mc.hh = 40; mc.icon = "trash-2"
            }
            sep()
        }
        if (remoteNote()) return
        if (!havePlayer) { note(Tr.t("settings.playback.noPlayer"), "dark"); return }
        if (!cfg.players.length) { note(Tr.t("settings.multiroom.noOthers"), "dark"); return }
        for (var p = 0; p < cfg.players.length; p++) {
            var t = toggle(cfg.players[p].name, "", cfg.players[p].sync, "sync_toggle", cfg.players[p].id); t.icon = "speaker"
        }
    }
    // ── Bluetooth speakers ────────────────────────────────────────────────
    // Pair a speaker here and it becomes a Lyrion player of its own, with its
    // own name and its own queue, next to this device's built-in player — so
    // it can be grouped with it, or play something else entirely. The DAC is
    // never involved: nothing here changes what the built-in player does.
    function secBtSpeakers() {
        help("settings.btSpeakers.help")
        if (!cfg.btAvailable) { note(Tr.t("settings.btSpeakers.unavailable"), "dark", "info"); return }
        var sw = toggle(Tr.t("settings.btSpeakers.enable"), Tr.t("settings.btSpeakers.enableHint"), cfg.btEnabled, "bt_enable")
        sw.dim = btBusy
        if (!cfg.btEnabled) return
        if (btBusy && !cfg.btSpeakers.length && !cfg.btFound.length) { helpText(Tr.t("common.loading"), 13); return }
        if (!cfg.btAdapter) { note(Tr.t("settings.btSpeakers.noAdapter"), "red", "alert-triangle"); return }

        label("settings.btSpeakers.yours")
        if (!cfg.btSpeakers.length) helpText(Tr.t("settings.btSpeakers.none"), 13)
        for (var i = 0; i < cfg.btSpeakers.length; i++) {
            var sp = cfg.btSpeakers[i]
            var state = !sp.enabled ? Tr.t("settings.btSpeakers.switchedOff")
                      : sp.playing ? Tr.t("settings.btSpeakers.ready")
                      : sp.connected ? Tr.t("settings.btSpeakers.connecting")
                      : Tr.t("settings.btSpeakers.notConnected")
            var b = bandRow(sp.connected ? "bluetooth-connected" : "bluetooth",
                            String(sp.player || sp.name || sp.mac), state, btBand === i, "bt_band", String(i), false)
            if (btBand !== i) continue
            begin(b.children)
            help("settings.btSpeakers.playerNameHint", 12)
            input(Tr.t("settings.btSpeakers.playerName"), btNameEdit, "bt_name", false, sp.mac)
            var ren = action(Tr.t("settings.btSpeakers.rename"), "bt_rename", "accent"); ren.hh = 40; ren.arg = sp.mac
            toggle(Tr.t("settings.btSpeakers.autoconnect"), Tr.t("settings.btSpeakers.autoconnectHint"), !!sp.autoconnect, "bt_auto", sp.mac)
            grid([acell(sp.connected ? Tr.t("settings.btSpeakers.disconnect") : Tr.t("settings.btSpeakers.connect"),
                        sp.connected ? "bt_disconnect" : "bt_connect", "light", { hh: 40, arg: sp.mac }),
                  acell(Tr.t("settings.btSpeakers.forget"), "bt_forget", "red", { hh: 40, arg: sp.mac })])
            var addr = info(Tr.t("settings.btSpeakers.address"), sp.mac); addr.mono = true; addr.px = 12; addr.hh = 36
            end()
        }

        sep()
        label("settings.btSpeakers.found")
        help("settings.btSpeakers.searchHint", 12)
        var sc = action(btScanning ? Tr.t("settings.btSpeakers.searching") : Tr.t("settings.btSpeakers.search"),
                        "bt_scan", "accent")
        sc.icon = "bluetooth-searching"; sc.hh = 44; sc.dim = btScanning || btBusy
        if (btScanning) helpText(Tr.t("settings.btSpeakers.searchingHint"), 12)
        else if (!cfg.btFound.length) helpText(Tr.t("settings.btSpeakers.foundNone"), 13)
        for (var j = 0; j < cfg.btFound.length; j++) {
            var dev = cfg.btFound[j]
            var sub = dev.audio ? dev.mac : Tr.t("settings.btSpeakers.notAudio")
            var r = option(String(dev.name || dev.mac), sub, dev.mac, false, "bt_add")
            r.icon = dev.audio ? "speaker" : "bluetooth"; r.hh = 60; r.style = "row"; r.dim = btBusy
        }
    }
    function secAlarm() {
        help("settings.alarm.help")
        if (remoteNote()) return
        if (!havePlayer) { note(Tr.t("settings.playback.noPlayer"), "dark"); return }
        for (var i = 0; i < cfg.alarms.length; i++) {
            var a = cfg.alarms[i], mins = Math.floor(a.time / 60)
            var hh = String(Math.floor(mins / 60) % 24).padStart(2, "0"), mm = String(mins % 60).padStart(2, "0")
            push({ type: "alarm", label: hh + ":" + mm, arg: a.id, on: a.on, act: "alarm_toggle", act2: "alarm_delete", hh: 48 })
        }
        grid([cell(String(alarmH).padStart(2, "0"), "", false, "alarm_hour", { style: "border", hh: 52, mono: true, outline: true }),
              cell(String(alarmM).padStart(2, "0"), "", false, "alarm_min", { style: "border", hh: 52, mono: true, outline: true }),   // border border-hifi-accent
              acell(Tr.t("settings.alarm.add"), "alarm_add", "gold", { bold: true, hh: 52, icon: "plus" })])
    }
    function secNetwork() {
        label("settings.network.interfaceLabel")
        for (var i = 0; i < cfg.ifaces.length; i += 2) {
            var cells = []
            for (var j = i; j < Math.min(cfg.ifaces.length, i + 2); j++) {
                var f = cfg.ifaces[j]
                cells.push({ type: "option", label: f.name, value: f.addr, arg: f.name, sel: f.active, act: "net_iface", hh: 60, mono: true, icon: f.wifi ? "wifi" : "network", valueAlpha: 0.75 })
            }
            if (cells.length === 1) cells.push({ type: "help", label: "" })
            grid(cells)
        }
        var wifi = cfg.netType === "wireless" || cfg.netType === "wifi"
        var act = !cfg.netConnected ? Tr.t("settings.network.activeNone")
                : wifi ? Tr.tf("settings.network.activeWifi", "ssid", cfg.netSsid).replace("{ip}", cfg.netIp)
                : Tr.tf("settings.network.activeWired", "ip", cfg.netIp)
        var ai = info(Tr.t("settings.network.activeLabel"), act); ai.mono = true; ai.style = "row"; ai.icon = wifi ? "wifi" : "network"
        grid([acell(Tr.t("settings.network.configureWifiButton"), "wifi_panel", "light", { hh: 40, icon: "wifi" }),
              acell(Tr.t("settings.network.useWiredButton"), "wired_dhcp", "light", { hh: 40, icon: "network" })])   // bg-hifi-light
        var ip = info(Tr.tf("settings.network.currentIp", "name", cfg.netDev || "—"), cfg.netIp || "—"); ip.mono = true; ip.style = "row"
        if (cfg.netSubnet) { ip.extra = Tr.tf("settings.network.typeSubnet", "type", wifi ? "wireless" : "wired").replace("{subnet}", cfg.netSubnet); ip.hh = 64 }
        note(Tr.t("settings.network.dhcpNotice"), "dark", "info", 12)
        var rl = action(Tr.t("settings.network.reloadData"), "net_reload", "accent"); rl.icon = "rotate-cw"; rl.hh = 40
    }
    function secWebremote() {
        help("settings.webRemote.help")
        var ip = cfg.deviceIp || cfg.netIp
        var usable = ip && ip.indexOf("127.") !== 0
        if (!usable) { note(Tr.t("settings.webRemote.noIp"), "dark"); return }
        // Following another server? Then the music lives THERE, so the link
        // has to go there — bare root, because the skin choice below only
        // applies to this device's own server and /material/ may not even
        // exist on the other one (the root always serves its default skin).
        var url = cfg.lmsHost
            ? "http://" + cfg.lmsHost + ":9000"
            : "http://" + ip + ":9000/material/" + (cfg.lmsSkin === "osmium" ? "?defaultTheme=dark/Osmium" : "")
        if (!cfg.pairToken) { note(Tr.t("settings.webRemote.generatingToken"), "dark"); code(url); return }
        qr(JSON.stringify({ lms: url, api: ip + ":8080", token: cfg.pairToken }), Tr.t("settings.webRemote.scanHint"))
        code(url)
        sep().tone = "light"                                 // border-t border-hifi-light/10
        help("settings.webRemote.revokeAllHelp", 12)
        var b = action(Tr.t("settings.webRemote.revokeAll"), "revoke_pair", "darkred"); b.icon = "trash-2"
    }
    function secWebremoteIos() {
        help("settings.webRemoteIos.help")
        qr("https://apps.apple.com/app/lyrplay/id6746776736", Tr.t("settings.webRemoteIos.scanHint"))
        code("https://apps.apple.com/app/lyrplay/id6746776736")
        help("settings.webRemoteIos.disclaimer", 11).center = true
    }
    function secSsh() {
        help("settings.ssh.help")
        note(Tr.t("settings.ssh.warning"), "amber", "shield-alert", 12)
        toggle(Tr.t(cfg.sshEnabled ? "settings.ssh.enabled" : "settings.ssh.disabled"), "", cfg.sshEnabled, "ssh")
        if (!cfg.sshAvailable) help("settings.ssh.installHint", 12)
        sep()
        label("settings.ssh.loginTitle")
        if (cfg.shellUser) { help("settings.ssh.loginIs", 12); code("ssh " + cfg.shellUser + "@" + (cfg.deviceIp || cfg.localIp || "…")) }
        else help("settings.ssh.noLogin", 12)
        help("settings.ssh.sudoWarning", 12)
        var su = input(Tr.t("settings.ssh.usernamePlaceholder"), sshUser || cfg.shellUser, "ssh_user", false); su.hh = 50; su.bg = "surface"   // SSH: bg-hifi-surface
        var sp = input(Tr.t("settings.ssh.passwordPlaceholder"), sshPass, "ssh_pass", true); sp.hh = 50; sp.bg = "surface"
        var b = action(Tr.t(cfg.shellUser ? "settings.ssh.loginUpdate" : "settings.ssh.loginCreate"), "ssh_save", "gold"); b.bold = true; b.hh = 44; b.dim = sshPass.length < 8
    }
    function secPointer() {
        help("settings.pointer.help")
        toggle(Tr.t(cfg.pointerEnabled ? "settings.pointer.enabled" : "settings.pointer.disabled"), "", cfg.pointerEnabled, "pointer")
        if (!cfg.pointerAvailable) note(Tr.t("settings.pointer.unavailable"), "dark")
    }
    function secUires() {
        help("settings.uiResolution.help")
        var OPT = ["auto", "720", "1080", "native"]
        for (var i = 0; i < 4; i++) {
            var r = option(Tr.t("settings.uiResolution.option." + OPT[i]), Tr.t("settings.uiResolution.optionHelp." + OPT[i]), OPT[i], cfg.uiResolution === OPT[i], "uires")
            r.style = "border"; r.hh = 62
        }
        if (pendAct === "uires") confirmRow(Tr.t("settings.uiResolution.restartWarning"), Tr.t("settings.uiResolution.confirm"), "uires_confirm")
    }
    function secUirefresh() {
        help("settings.uiRefresh.help")
        if (!cfg.uiRefreshSupported) { note(Tr.t("settings.uiRefresh.unsupported"), "dark"); return }
        help("settings.uiRefresh.monitorDisclaimer").tone = "amber"
        var low = cfg.uiRefresh === "low"
        var st = info(Tr.t(low ? "settings.uiRefresh.currentLow" : "settings.uiRefresh.currentNative"), ""); st.icon = "refresh-cw"; st.style = "row"
        if (countdown > 0) {
            var c = confirmRow(Tr.tf("settings.uiRefresh.confirmPrompt", "seconds", String(countdown)), Tr.t("settings.uiRefresh.keep"), "refresh_keep")
            c.arg = Tr.t("settings.uiRefresh.revertNow"); c.act2 = "refresh_revert"
        } else {
            var b = action(Tr.t(low ? "settings.uiRefresh.switchToNative" : "settings.uiRefresh.switchToLow"), "refresh_switch", "dark"); b.icon = "refresh-cw"
        }
    }
    function secDisplaymode() {
        help("settings.displayMode.help")
        var headless = cfg.displayMode === "headless"
        var st = info(Tr.t(headless ? "settings.displayMode.currentHeadless" : "settings.displayMode.currentGui"), ""); st.icon = headless ? "monitor-off" : "monitor"; st.style = "row"
        if (pendAct === "display_switch") confirmRow(Tr.t("settings.displayMode.headlessWarning"), Tr.t("settings.displayMode.confirmHeadless"), "display_confirm")
        else { var b = action(Tr.t(headless ? "settings.displayMode.switchToGui" : "settings.displayMode.switchToHeadless"), "display_switch", "dark"); b.icon = headless ? "monitor" : "monitor-off" }
        sep()
        label("settings.playerEnabled.label"); help("settings.playerEnabled.help")
        var ps = info(Tr.t(cfg.playerEnabled ? "settings.playerEnabled.currentOn" : "settings.playerEnabled.currentOff"), ""); ps.style = "row"; ps.icon = "speaker"
        if (pendAct === "player_switch") confirmRow(Tr.t("settings.playerEnabled.offWarning"), Tr.t("settings.playerEnabled.confirmOff"), "player_confirm")
        else action(Tr.t(cfg.playerEnabled ? "settings.playerEnabled.switchOff" : "settings.playerEnabled.switchOn"), "player_switch", "dark")
    }
    function secTimezone() {
        help("settings.timezone.help")
        var st = info(cfg.timezone || Tr.t("common.loading"), ""); st.icon = "clock"; st.style = "row"
        var sel = option(cfg.timezone || Tr.t("common.loading"), "", "", false, "timezone"); sel.style = "border"; sel.icon = "chevron-down"; sel.hh = 44; sel.outline = true   // border border-hifi-accent
    }
    function secSysinfo() {
        info(Tr.t("settings.info.hostname"), cfg.hostname || Tr.t("settings.info.notAvailable")).style = "seg"
        info(Tr.t("settings.info.deviceIp"), cfg.deviceIp || cfg.localIp || Tr.t("settings.info.notAvailable")).style = "seg"
        info(Tr.t("settings.info.platform"), cfg.platform + " (" + cfg.arch + ")").style = "seg"
        info(Tr.t("settings.info.apiStatus"), Tr.t(cfg.apiOk ? "settings.info.connected" : "settings.info.disconnected")).style = "seg"
        netCheckEntry(false)
        sep()
        // the guided tour of the interface, again on demand
        action(Tr.t("settings.info.replayTutorial"), "tutorial", "accent")
        sep()
        helpText("Osmium Sound " + cfg.version, 12).center = true
        // ogni interfaccia dice con cosa è fatta: questa è Qt/QML, non Electron
        help("settings.about.builtWithQt", 12).center = true
    }
    function secUpdates() {
        label("settings.updates.channel", 14)
        var cells = []
        for (var i = 0; i < cfg.otaChannels.length; i++) {
            var ch = cfg.otaChannels[i]
            cells.push(cell(Tr.t(ch === "prod" ? "settings.updates.channelProd" : ch === "dev" ? "settings.updates.channelDev" : "settings.updates.channelAlpha"), ch, cfg.otaChannel === ch, "ota_channel", { hh: 44 }))
        }
        grid(cells)
        if (cfg.otaChannel !== "prod") note(Tr.t("settings.updates.channelWarning"), "amber", "shield-alert", 12)
        var UL = ["settings.updates.ui", "settings.updates.system", "settings.updates.os"], any = false
        box(function() {
            for (var k = 0; k < 3; k++) {
                var u = cfg.upd[k]
                var r = info(Tr.t(UL[k]), u.cur || "…"); r.mono = true; r.style = "seg"; r.hh = 24
                if (u.avail && u.latest && u.cur !== u.latest) { r.extra = "→ " + u.latest; any = true }
                if (k === 2) r.bold = true
            }
        })
        if (cfg.updChecking) note(Tr.t("settings.updates.checking"), "dark")
        else if (any) note(Tr.t("settings.updates.available"), "gold")
        else if (cfg.updCheckFailed) note(Tr.t("settings.updates.checkFailed"), "red")
        else note(Tr.t("settings.updates.upToDate"), "dark")
        if (cfg.changelog) { var w = action(Tr.t("settings.updates.whatsNew"), "upd_changelog", "dark"); w.hh = 40; w.px = 14 }
        var ck = action(Tr.t("settings.updates.checkButton"), "upd_check", "accent"); ck.icon = "rotate-cw"; ck.hh = 48
        if (any) { var up = action(Tr.t("settings.updates.updateNow"), "upd_apply", "gold"); up.bold = true; up.hh = 56; up.icon = "download"; help("settings.updates.orderNote", 12) }
        if (cfg.otaState && cfg.otaState !== "idle") note(cfg.otaPct > 0 ? cfg.otaMsg + " (" + cfg.otaPct + "%)" : cfg.otaMsg, "dark")
        toggle(Tr.t("settings.updates.autoCheck"), "", autoCheck, "upd_autocheck")
        // a failed check is exactly when the owner needs it: stand it out
        netCheckEntry(cfg.updCheckFailed && !cfg.updChecking)
    }
    function secSysctl() {
        var rb = action(Tr.t("settings.controls.reboot"), "reboot", "orange"); rb.icon = "rotate-cw"; rb.bold = true; rb.hh = 56
        var sd = action(Tr.t("settings.controls.shutdown"), "shutdown", "red"); sd.icon = "power"; sd.bold = true; sd.hh = 56
        var wr = action(Tr.t("settings.webuiReset.button"), "webui_reset", "dark"); wr.icon = "lock"; wr.bold = true; wr.hh = 56
        sep().tone = "red"                                   // border-t border-red-500/20
        help("settings.factory.help", 12)
        var fr = action(Tr.t("settings.factory.button"), "factory_reset", "darkred"); fr.icon = "alert-triangle"; fr.bold = true; fr.hh = 56
    }
    // ─── network check ─────────────────────────────────────────────────────
    function netCheckEntry(prominent) {
        var b = action(Tr.t("settings.netCheck.open"), "netcheck_open", prominent ? "accent" : "dark"); b.icon = "network"; b.hh = 48
        help("settings.netCheck.openHelp", 12)
    }
    function openNetCheck() {
        var from = secs[active].id
        openSection("netCheck")
        backTo = from
        runNetCheck()
    }
    function runNetCheck() {
        if (ncBusy) return
        ncBusy = true; ncFailed = false
        rebuild()
        Api.get(cfg.api("/network_check"), function(ok, d) {
            ncBusy = false
            if (ok && d && d.steps) nc = d
            else ncFailed = true
            rebuild()
        }, 45000)
    }
    function fmtSkew(sec) {
        var a = Math.abs(sec)
        if (a < 3600) return Math.round(a / 60) + " min"
        if (a < 86400) return Math.round(a / 3600) + " h"
        return Math.round(a / 86400) + " " + Tr.t("settings.lyrion.days")
    }
    // the reason a step or a source failed, in words
    function ncReason(s) {
        var e = s.error
        if (!e) return ""
        if (e === "http") return Tr.tf("settings.netCheck.err.http", "code", s.http)
        if (e === "packetLoss") return Tr.tf("settings.netCheck.err.packetLoss", "loss", s.loss)
        if (e === "clockOff") return s.skew !== undefined ? Tr.tf("settings.netCheck.err.clockOff", "time", fmtSkew(s.skew)) : Tr.t("settings.netCheck.err.clockWrong")
        if (e === "dnsPartial") return Tr.t("settings.netCheck.err.dnsPartial") + " " + (s.failed || []).join(", ")
        return Tr.t("settings.netCheck.err." + e)
    }
    function ncDetail(s) {
        var parts = []
        if (s.detail) parts.push(String(s.detail))
        if (s.kbps) parts.push(s.kbps >= 1024 ? (s.kbps / 1024).toFixed(1) + " MB/s" : s.kbps + " KB/s")
        return parts.join(" · ")
    }
    // What the owner sees: four plain steps, each the worst of the checks
    // behind it; the seven checks with their numbers are "advanced".
    readonly property var ncGroups: [
        { id: "device", steps: ["link"] }, { id: "router", steps: ["router"] },
        { id: "internet", steps: ["internet", "dns", "clock"] }, { id: "server", steps: ["ota", "download"] }]
    function ncStep(res, id) {
        if (res) for (var j = 0; j < res.steps.length; j++) if (res.steps[j].id === id) return res.steps[j]
        return { id: id, status: ncBusy ? "run" : "skip" }
    }
    function ncWorst(res, ids) {
        var rank = { run: 5, fail: 4, warn: 3, ok: 2, skip: 1 }, worst = "skip"
        for (var i = 0; i < ids.length; i++) {
            var st = ncStep(res, ids[i]).status
            if ((rank[st] || 0) > rank[worst]) worst = st
        }
        return worst
    }
    function secNetcheck() {
        help("settings.netCheck.help")
        var STEPS = ["link", "router", "internet", "dns", "clock", "ota", "download"]
        var res = ncBusy ? null : nc
        if (ncBusy) note(Tr.t("settings.netCheck.running"), "dark")
        else if (ncFailed) note(Tr.t("settings.netCheck.failed"), "red", "alert-circle")
        else if (res) {
            var v = res.verdict === "ok" && res.warn ? "warn" : res.verdict
            // a caveat has a sentence of its own for the step it comes from
            var vt = v === "warn" && ["link", "router", "internet", "dns", "clock", "ota"].indexOf(res.warn) >= 0
                   ? Tr.t("settings.netCheck.verdictWarn." + res.warn) : Tr.t("settings.netCheck.verdict." + v)
            note(vt, v === "ok" ? "gold" : v === "warn" ? "amber" : "red",
                 v === "ok" ? "check-circle-2" : v === "warn" ? "alert-triangle" : "alert-circle")
        }
        box(function() {
            for (var g = 0; g < ncGroups.length; g++) {
                var st = ncWorst(res, ncGroups[g].steps)
                push({ type: "diag", plain: true, label: Tr.t("settings.netCheck.groups." + ncGroups[g].id), status: st,
                       value: Tr.t("settings.netCheck.status." + st) })
            }
        })
        var b = action(Tr.t(nc ? "settings.netCheck.again" : "settings.netCheck.run"), "netcheck_run", "accent"); b.icon = "rotate-cw"; b.hh = 48; b.dim = ncBusy
        var a = action(Tr.t(ncAdvanced ? "settings.netCheck.advancedHide" : "settings.netCheck.advanced"), "netcheck_adv", "dark")
        a.icon = ncAdvanced ? "chevron-up" : "chevron-down"; a.hh = 40; a.px = 14
        if (!ncAdvanced) return
        box(function() {
            for (var i = 0; i < STEPS.length; i++) {
                var s = ncStep(res, STEPS[i])
                push({ type: "diag", label: Tr.t("settings.netCheck.steps." + STEPS[i]), status: s.status,
                       value: ncDetail(s), extra: s.status === "skip" && res ? Tr.t("settings.netCheck.status.skip") : ncReason(s) })
                if (STEPS[i] === "ota" && s.sources) for (var k = 0; k < s.sources.length; k++) {
                    var src = s.sources[k]
                    push({ type: "diag", sub: true, label: Tr.t("settings.netCheck.sources." + src.id), status: src.status,
                           value: src.host + (src.ms !== undefined ? " · " + src.ms + " ms" : ""),
                           extra: src.status === "ok" ? "" : ncReason(src) })
                }
            }
        })
        if (res) helpText(Tr.tf("settings.netCheck.lastRun", "time", Qt.formatDateTime(new Date(res.at * 1000), "HH:mm:ss")) + " · " + String(res.channel || ""), 12).center = true
    }
    function secThirdparty() {
        if (!thirdParty) { note(Tr.t("common.loading"), "dark"); return }
        help("settings.thirdPartyNotices.intro")
        for (var i = 0; i < thirdParty.length; i++) {
            var s = thirdParty[i]
            var h = labelText(String(s.section || ""), 12); h.dim = true
            for (var j = 0; j < (s.entries || []).length; j++) {
                var e = s.entries[j]
                var r = info(String(e.name || ""), String(e.license || "")); r.mono = true; r.hh = 64; r.tone = "tp"   // nome bianco, licenza silver/80
                var ver = String(e.version || ""), no = String(e.notes || "")
                r.extra = ver && no ? ver + " — " + no : no || ver
                if (!r.extra) r.hh = 44
            }
        }
    }

    // ─── campi di testo ────────────────────────────────────────────────────
    function fieldSet(row, text) {
        switch (row.act) {
        case "wiz_field":
            if (row.arg === "h") wizHost = text
            else if (row.arg === "s") wizShare = text
            break
        case "ssh_user": sshUser = text; break
        case "ssh_pass": sshPass = text; break
        case "player_name": nameEdit = text; break
        case "lms_host": hostEdit = text; break
        case "pick_new": pickNew = text; break
        case "bt_name": btNameEdit = text; break
        }
        // le righe dipendenti (pulsante "applica" attivo/spento) si rifanno subito
        dimRefresh.restart()
    }
    Timer { id: dimRefresh; interval: 150; onTriggered: root.rebuild() }

    // Every /bt_speakers/* reply carries the full state, so there is exactly
    // one place that unpacks it — and exactly one place that decides whether
    // the message on screen is a complaint or a confirmation.
    function btApply(ok, d) {
        btBusy = false; btScanning = false
        if (ok && d && typeof d === "object") {
            if (d.available !== undefined) {
                cfg.btAvailable = !!d.available; cfg.btEnabled = !!d.enabled; cfg.btAdapter = !!d.adapter
                cfg.btSpeakers = d.speakers || []; cfg.btFound = d.found || []
            }
            if (d.message) { say(String(d.message), d.success === false); return }
        } else {
            say(Tr.t("settings.btSpeakers.opFailed"), true); return
        }
        rebuild()
    }
    // While the section is open, follow a speaker that is switching itself on
    // (or off) without making the owner tap anything. Held back while a
    // command is in flight, and while the on-screen keyboard is up — a
    // rebuild there would throw away what is being typed.
    Timer {
        interval: 5000; repeat: true
        running: root.active >= 0 && root.secs[root.active].id === "btSpeakers"
                 && !root.btBusy && !(Ui.vk && Ui.vk.active)
        onTriggered: cfg.loadBt()
    }
    function fieldCommit(row) { rebuild() }

    // ─── azioni ────────────────────────────────────────────────────────────
    function activate(row, act, argOverride) {
        var arg = argOverride !== undefined ? argOverride : (row.arg || "")
        var A = cfg.api, S = cfg.src
        switch (act) {
        case "lang":
            I18n.lang = arg
            Sys.setConf("ui-language", arg)
            break
        case "ssh": post(A("/ssh_set"), { enable: !row.on }); cfg.sshEnabled = !row.on; break
        case "pointer": post(A("/pointer_set"), { enable: !row.on }); cfg.pointerEnabled = !row.on; Sys.pointerEnabled = cfg.pointerEnabled; break
        case "uires":
            if (cfg.uiResolution === arg) return
            pendAct = "uires"; pendArg = arg; break
        case "uires_confirm": post(A("/ui_resolution"), { mode: pendArg }); cfg.uiResolution = pendArg; pendAct = ""; break
        case "confirm_cancel": pendAct = ""; break
        case "refresh_switch": {
            var low = cfg.uiRefresh === "low"
            post(A("/ui_refresh"), { mode: low ? "native" : "low" }); cfg.uiRefresh = low ? "native" : "low"
            if (!low) { countdown = 10; countTimer.restart() }
            break
        }
        case "refresh_keep": countdown = 0; say(Tr.t("settings.uiRefresh.kept")); break
        case "refresh_revert": countdown = 0; post(A("/ui_refresh"), { mode: "native" }); cfg.uiRefresh = "native"; break
        case "display_switch":
            if (cfg.displayMode === "headless") { post(A("/display_mode"), { mode: "gui" }); cfg.displayMode = "gui" }
            else pendAct = "display_switch"
            break
        case "display_confirm": post(A("/display_mode"), { mode: "headless" }); cfg.displayMode = "headless"; pendAct = ""; break
        case "player_switch":
            if (!cfg.playerEnabled) { post(A("/player_enabled"), { enabled: true }); cfg.playerEnabled = true }
            else pendAct = "player_switch"
            break
        case "player_confirm": post(A("/player_enabled"), { enabled: false }); cfg.playerEnabled = false; pendAct = ""; break
        case "timezone":
            Ui.dialogs.pick(Tr.t("settings.sections.timezone"), timezones, timezones.indexOf(cfg.timezone), function(i) {
                if (i < 0) return
                post(A("/timezone"), { timezone: timezones[i] }); cfg.timezone = timezones[i]; rebuild()
            })
            return
        // ── Bluetooth speakers ───────────────────────────────────────
        // Every one of these answers with the whole new state (the endpoints
        // return get_bt_speakers()), so the reply is applied straight away
        // instead of waiting for the next poll — pairing takes long enough
        // that a second round trip would be felt.
        case "bt_enable":
            btBusy = true
            Api.post(A("/bt_speakers/enable"), { enable: !row.on }, function(ok, d) { btApply(ok, d) }, 40000)
            break
        case "bt_band":
            var idx = Number(arg)
            btBand = (btBand === idx) ? -1 : idx
            // the field starts on the name the speaker actually has
            btNameEdit = btBand >= 0 && cfg.btSpeakers[btBand] ? String(cfg.btSpeakers[btBand].player || "") : ""
            break
        case "bt_scan":
            btScanning = true; btBusy = true
            Api.post(A("/bt_speakers/scan"), { seconds: 12 }, function(ok, d) { btApply(ok, d) }, 60000)
            break
        case "bt_add":
            btBusy = true
            say(Tr.t("settings.btSpeakers.pairing"))
            Api.post(A("/bt_speakers/add"), { mac: arg }, function(ok, d) { btApply(ok, d) }, 120000)
            break
        case "bt_connect":
        case "bt_disconnect":
            btBusy = true
            Api.post(A("/bt_speakers/connect"), { mac: arg, connect: act === "bt_connect" },
                     function(ok, d) { btApply(ok, d) }, 90000)
            break
        case "bt_auto":
            btBusy = true
            Api.post(A("/bt_speakers/update"), { mac: arg, autoconnect: !row.on },
                     function(ok, d) { btApply(ok, d) }, 40000)
            break
        case "bt_rename":
            if (!btNameEdit.trim()) return
            btBusy = true
            Api.post(A("/bt_speakers/update"), { mac: arg, player: btNameEdit.trim() },
                     function(ok, d) { btApply(ok, d) }, 40000)
            break
        case "bt_forget":
            Ui.dialogs.confirm(Tr.t("settings.btSpeakers.forgetConfirm"),
                               Tr.t("settings.btSpeakers.forget"), true, function(ok) {
                if (!ok) return
                btBand = -1; btBusy = true
                Api.post(A("/bt_speakers/remove"), { mac: arg }, function(ok2, d) { btApply(ok2, d) }, 60000)
            })
            return
        case "vumeter": post(A("/vu_meter"), { enable: !row.on }); cfg.vuMeter = !row.on; Player.vuEnabled = cfg.vuMeter; break
        case "vu_style": post(A("/vu_style"), { style: arg }); Player.vuStyle = arg; break
        case "open_animations": openSection("animations"); return
        case "anim_vu_off": post(A("/vu_meter"), { enable: false }); cfg.vuMeter = false; Player.vuEnabled = false; break
        case "np_anim":
            post(A("/nowplaying_animation"), { animation: arg }); cfg.npAnimation = arg; Player.npAnimation = arg
            // a freshly chosen animation is what Now Playing shows next, even
            // if the lyrics were the last view picked there
            if (arg !== "none" && Ui.app && !Ui.app.viewVu) { Ui.app.viewVu = true; Sys.setConf("nowplaying-view", "vu") }
            break
        case "vu_install":
            if (row.state === "downloading" || row.state === "installing" || row.state === "unsupported") return
            Api.post(A("/vu_store/install"), { id: arg }, function(ok, d) {
                if (d && d.success === false) say(String(d.message || ""), true)
                cfg.loadStore(false)
            }, 12000)
            cfg.vuStore = Object.assign({}, cfg.vuStore, { busy: true })
            break
        case "vu_remove":
            Ui.dialogs.confirm(Tr.tf("settings.vuMeters.removeConfirm", "name", row.label), Tr.t("settings.vuMeters.remove"), true, function(ok) {
                if (!ok) return
                Api.post(A("/vu_store/remove"), { id: arg }, function(ok2, d) {
                    if (d && d.success === false) say(String(d.message || ""), true)
                    else if (Player.vuStyle === arg) Player.vuStyle = "classic"
                    cfg.load(); cfg.loadStore(false)
                }, 12000)
            })
            return
        case "vu_check":
            Api.post(A("/vu_store/check"), {}, function() { cfg.loadStore(false) }, 12000)
            cfg.vuStore = Object.assign({}, cfg.vuStore, { checking: true })
            break
        case "anim_install":
            if (row.state === "downloading" || row.state === "installing" || row.state === "unsupported") return
            Api.post(A("/anim_store/install"), { id: arg }, function(ok, d) {
                if (d && d.success === false) say(String(d.message || ""), true)
                cfg.loadAnimStore(false)
            }, 12000)
            cfg.animStore = Object.assign({}, cfg.animStore, { busy: true })
            break
        case "anim_remove":
            Ui.dialogs.confirm(Tr.tf("settings.animations.removeConfirm", "name", row.label), Tr.t("settings.vuMeters.remove"), true, function(ok) {
                if (!ok) return
                Api.post(A("/anim_store/remove"), { id: arg }, function(ok2, d) {
                    if (d && d.success === false) say(String(d.message || ""), true)
                    else if (Player.npAnimation === arg) Player.npAnimation = "none"
                    cfg.load(); cfg.loadAnimStore(false)
                }, 12000)
            })
            return
        case "anim_check":
            Api.post(A("/anim_store/check"), {}, function() { cfg.loadAnimStore(false) }, 12000)
            cfg.animStore = Object.assign({}, cfg.animStore, { checking: true })
            break
        case "album_view": if (Ui.app) Ui.app.setAlbumView(arg); break
        case "tutorial": if (Ui.app) Ui.app.startTutorial(); return
        case "autoexpand": post(A("/nowplaying_autoexpand"), { seconds: parseInt(arg) }); cfg.autoexpand = parseInt(arg); Player.refreshSettings(); break
        case "transition": setPref("transitionType", arg); Player.refreshPrefs(); say(Tr.t("settings.playback.saved")); break
        case "transdur": setPref("transitionDuration", arg); Player.refreshPrefs(); say(Tr.t("settings.playback.saved")); break
        case "replaygain": setPref("replayGainMode", arg); Player.refreshPrefs(); say(Tr.t("settings.playback.saved")); break
        case "fixedvol": setPref("digitalVolumeControl", row.on ? "1" : "0"); Player.refreshPrefs(); say(Tr.t("settings.playback.saved")); break
        case "audio_pick": audioSel = arg; break
        case "audio_apply":
            if (!audioSel) return
            post(A("/set_audio_device"), { device: audioSel }); cfg.audioCur = audioSel; say(Tr.t("settings.audio.updated")); break
        case "audio_refresh": cfg.load(); break
        case "lms_skin": post(S("/api/lms_skin"), { skin: arg }); cfg.lmsSkin = arg; say(Tr.t("settings.lyrion.skinApplying")); break
        case "wiz_field": case "pick_new": case "ssh_user": case "ssh_pass": case "player_name": case "lms_host": return
        case "lms_role":
            if (arg !== "local") { cfg.lmsMode = "follow"; cfg.loadDiscover(); break }
            // Already on this device's own server: only the toggle moves back,
            // nothing to apply and nothing to reboot for.
            if (!cfg.lmsHost) { cfg.lmsMode = "local"; break }
            askRoleReboot(function() {
                post(A("/lms_role"), { mode: "local" }, function(ok, d) {
                    // 🚨 The outcome decides: this used to fire and forget, so
                    // a refused or unanswered change still said "saved" and
                    // left the owner sure the device was on its own server
                    // when it was not. Now nothing moves — and nothing
                    // reboots — unless the server confirms it.
                    if (!ok || (d && d.success === false)) {
                        say((d && d.message) || Tr.t("settings.multiroom.role.failed"), true)
                        return
                    }
                    Api.refreshLmsHost()
                    cfg.lmsMode = "local"; cfg.lmsHost = ""
                    say(Tr.t("settings.msg.rebooting"))
                    post(A("/reboot"), {})
                })
            })
            return
        case "lms_pick": hostEdit = arg; break
        case "lms_discover": cfg.loadDiscover(); say(Tr.t("common.loading")); break
        case "lms_apply": {
            var h = hostEdit || cfg.lmsHost
            if (!h) { say(Tr.t("settings.multiroom.role.hostRequired"), true); return }
            if (h === cfg.lmsHost) { say(Tr.t("settings.multiroom.role.saved")); return }
            askRoleReboot(function() {
                post(A("/lms_role"), { mode: "follow", host: h }, function(ok, d) {
                    if (!ok || (d && d.success === false)) {
                        say((d && d.message) || Tr.t("settings.multiroom.role.failed"), true)
                        return
                    }
                    Api.refreshLmsHost()
                    cfg.lmsHost = h; cfg.lmsMode = "follow"
                    say(Tr.t("settings.msg.rebooting"))
                    post(A("/reboot"), {})
                })
            })
            return
        }
        case "player_back": Player.selectPlayer("", ""); break
        case "player_name_apply":
            if (!nameEdit) return
            post(A("/device_name"), { name: nameEdit }); cfg.deviceName = nameEdit; say(Tr.t("settings.multiroom.name.saved")); break
        case "lyrion_channel": post(A("/lyrion_channel"), { channel: arg }); cfg.lyrionChannel = arg; break
        case "lyrion_install": post(A("/lyrion_update/apply"), { channel: cfg.lyrionChannel }); say(Tr.t("settings.multiroom.server.update")); break
        case "lyrion_check": cfg.load(); break
        case "lib_rescan":
            Player.queryServer(["rescan"], function() { cfg.loadLibrary() })
            cfg.lib = Object.assign({}, cfg.lib, { scanning: true, pct: -1, progress: "" })
            say(Tr.t("settings.lyrion.rescanStarted")); break
        case "meta_online": post(S("/api/meta/settings"), { online: !row.on }); cfg.meta = Object.assign({}, cfg.meta, { online: !row.on }); break
        case "meta_prefetch": post(S("/api/meta/settings"), { prefetch: !row.on }); cfg.meta = Object.assign({}, cfg.meta, { prefetch: !row.on }); break
        case "meta_clear": post(S("/api/meta/cache/clear"), {}); say(Tr.t("settings.lyrion.metaCleared")); break
        case "lib_abort":
            Player.queryServer(["abortscan"], function() { cfg.loadLibrary() })
            say(Tr.t("settings.lyrion.scanAborted")); break
        case "ota_channel": {
            if (cfg.otaChannel === arg) return
            var apply = function() { post(A("/ota_channel"), { channel: arg }); cfg.otaChannel = arg; rebuild() }
            if (cfg.otaChannel === "prod") { Ui.dialogs.confirm(Tr.t("settings.updates.confirmProdToDev"), Tr.t("common.confirm"), false, function(ok) { if (ok) apply() }); return }
            apply(); return
        }
        case "upd_check": msg = ""; cfg.load(); break
        case "netcheck_open": openNetCheck(); return
        case "netcheck_run": runNetCheck(); return
        case "netcheck_adv": ncAdvanced = !ncAdvanced; rebuild(); return
        case "upd_apply": post(A("/update/apply_all"), {}); say(Tr.t("settings.updates.updating")); break
        case "upd_changelog":
            // il titolo porta la versione, come in Settings.jsx
            Ui.dialogs.text(Tr.tf("settings.updates.changelogTitle", "version", cfg.upd[0].latest || cfg.upd[0].cur), cfg.changelog)
            return
        case "upd_autocheck": autoCheck = !autoCheck; Sys.setConf("ota-autocheck", autoCheck ? "1" : "0"); if (Ui.app && Ui.app.main) Ui.app.main.browser.checkUpdates(); break
        case "wifi_panel":
            cfg.loadWifi()
            Ui.dialogs.wifi(cfg.wifi, function(ssid, pw) {
                if (!ssid) return
                post(A("/wifi_connect"), { ssid: ssid, password: pw || "" })
                say(Tr.tf("settings.network.switchedToWifi", "ssid", ssid))
            })
            return
        case "wired_dhcp": post(A("/wired_dhcp"), {}); say(Tr.t("settings.network.switchedToWired")); break
        case "net_reload": cfg.load(); say(Tr.t("settings.network.loading")); break
        case "net_iface": return
        case "src_rw": {
            var wantRw = true
            for (var i = 0; i < cfg.sources.length; i++) if (String(cfg.sources[i].id) === arg) wantRw = !cfg.sources[i].rw
            post(S("/api/sources/" + arg + "/rw"), { rw: wantRw }); break
        }
        case "src_del": send("DELETE", S("/api/sources/" + arg), {}); break
        case "usb_retry": post(S("/api/usb/adopt"), { device: arg }); say(Tr.t("sources.internal.adopting")); break
        // ── procedura guidata "cartella di rete" ────────────────────────
        case "where_net": band = 1; bandAdd = 0; wizOpen(); return
        case "where_disk": band = 1; bandAdd = 1; break
        case "where_local": band = 1; bandAdd = 2; pickOwner = 1; pickBrowse(""); break
        case "wiz_open": wizOpen(); return
        case "wiz_manual_open": wizReset(); wiz = 0; wizManual = true; break
        case "wiz_close": wizReset(); break
        case "wiz_back":
            wizErr = ""; wizDetail = ""
            if (wiz === 2) wiz = 1
            else if (wiz === 1) { wiz = 0; if (!wizManual && scanState !== "done") wizScan() }
            break
        case "wiz_rescan": wizScan(); return
        case "wiz_manual": wizManual = true; wizErr = ""; wizDetail = ""; break
        case "wiz_host": if (!arg) return; wizPickHost(arg, wizHostName(arg)); return
        case "wiz_host_manual": if (!wizHost) return; wizPickHost(wizHost, wizHost); return
        case "wiz_needauth":
            // with no list yet the new login is for reading it; otherwise the
            // next tap on a folder uses it
            wizAskAuth(false, function() { if (wizCanList && !wizShares.length) wizLoadShares(); else rebuild() })
            return
        case "wiz_share": if (!arg) return; wizPickShare(arg); return
        // Il nome scritto a mano non passa dalla prova: la conferma finale e'
        // il mount stesso, che e' comunque il controllo di ultima istanza.
        case "wiz_share_manual": if (!wizShare) return; wiz = 2; break
        case "wiz_share_type": wizCanList = false; wizErr = ""; wizDetail = ""; break
        case "wiz_rw": wizRw = !wizRw; break
        case "wiz_add": wizAdd(); return
        case "wiz_detail": wizDetailOpen = !wizDetailOpen; break
        case "disk_adopt": {
            var dev = arg
            for (var d = 0; d < cfg.disks.length; d++) if (cfg.disks[d].path === arg && cfg.disks[d].parts.length === 1) dev = cfg.disks[d].parts[0].path
            post(S("/api/internal/adopt"), { device: dev }); say(Tr.t("sources.internal.adopting")); break
        }
        case "disk_format": {
            var di = parseInt(arg)
            if (isNaN(di) || di < 0 || di >= cfg.disks.length) return
            var dk = cfg.disks[di]
            Ui.dialogs.format(dk.path, dk.model, dk.size, dk.confirm, function(device, fs, lbl) {
                post(S("/api/internal/format"), { device: device, fs: fs, label: lbl, confirm: dk.confirm })
                fmtWatch = true
            })
            return
        }
        case "pldir_default":
            if (!cfg.pldirDef) return
            post(S("/api/playlistdir"), { path: cfg.pldirDef }); say(Tr.t("sources.playlistdir.saved")); break
        case "band": {
            var b = parseInt(arg)
            band = band === b ? -1 : b; brId = ""; pickOwner = 0
            if (band === 1 && bandAdd === 2) { pickOwner = 1; pickBrowse("") }
            if (band === 3 && bandShare === 0) { pickOwner = 3; pickBrowse("") }
            break
        }
        case "band_add": {
            var ba = parseInt(arg)
            bandAdd = bandAdd === ba ? -1 : ba; pickOwner = 0
            if (bandAdd === 2) { pickOwner = 1; pickBrowse("") }
            break
        }
        case "band_share":
            bandShare = bandShare === 0 ? -1 : 0; pickOwner = 0
            if (bandShare === 0) { pickOwner = 3; pickBrowse("") }
            break
        case "src_browse": {
            if (brId === arg) { brId = ""; break }
            brId = arg
            var sub = ""
            for (var s = 0; s < cfg.sources.length; s++) if (String(cfg.sources[s].id) === arg) sub = String(cfg.sources[s].subpath || "")
            brBusy = true; cfg.browse(1, brId, sub); break
        }
        case "br_close": brId = ""; break
        case "br_up": if (!cfg.brHasParent) return; brBusy = true; cfg.browse(1, brId, cfg.brParent); break
        case "br_into": brBusy = true; cfg.browse(1, brId, (cfg.brPath ? cfg.brPath + "/" : "") + arg); break
        case "br_here": case "br_root":
            post(S("/api/sources/" + brId + "/subpath"), { subpath: act === "br_root" ? "" : cfg.brPath })
            brId = ""; say(Tr.t("sources.subpathSaved")); break
        case "pick_open":
            if (pickOwner === 2) { pickOwner = 0; break }
            pickOwner = 2; pickBrowse(cfg.pldir); break
        case "pick_up": if (!cfg.pkHasParent) return; pickBrowse(cfg.pkParent); break
        case "pick_into": pickBrowse(arg); break
        case "pick_create":
            if (!pickNew || !cfg.pkPath) return
            Api.post(S("/api/local/mkdir"), { path: cfg.pkPath, name: pickNew }, function() { pickBrowse(cfg.pkPath) })
            pickNew = ""; break
        case "pick_use":
            if (!cfg.pkPath) return
            if (pickOwner === 2) { post(S("/api/playlistdir"), { path: cfg.pkPath }); say(Tr.t("sources.playlistdir.saved")) }
            else { post(S("/api/sources/local"), { path: cfg.pkPath, samba: pickOwner === 3 }); say(Tr.t("sources.added")) }
            pickOwner = 0; break
        case "smb_regen": post(S("/api/internal/smb/regenerate"), {}); break
        case "smb_show": smbShowPw = !smbShowPw; break
        case "revoke_pair":
            Ui.dialogs.confirm(Tr.t("settings.webRemote.revokeAllConfirm"), Tr.t("settings.webRemote.revokeAll"), true, function(ok) {
                if (!ok) return
                post(S("/api/pair/tokens/revoke_all"), {}); cfg.mintToken(); say(Tr.t("settings.webRemote.revokeAllSuccess"))
            })
            return
        case "ssh_save": {
            var u = sshUser || cfg.shellUser
            if (!u || sshPass.length < 8) return
            post(A("/shell_account"), { username: u, password: sshPass }); sshPass = ""; say(Tr.t("settings.ssh.loginSaved")); break
        }
        case "reboot": Ui.dialogs.confirm(Tr.t("settings.msg.confirmReboot"), Tr.t("settings.controls.reboot"), true, function(ok) { if (ok) { post(A("/reboot"), {}); say(Tr.t("settings.msg.rebooting")) } }); return
        case "shutdown": Ui.dialogs.confirm(Tr.t("settings.msg.confirmShutdown"), Tr.t("settings.controls.shutdown"), true, function(ok) { if (ok) { post(A("/shutdown"), {}); say(Tr.t("settings.msg.shuttingDown")) } }); return
        case "webui_reset": Ui.dialogs.confirm(Tr.t("settings.webuiReset.confirm"), Tr.t("settings.webuiReset.button"), true, function(ok) { if (ok) { post(A("/webui_reset_credentials"), {}); say(Tr.t("settings.webuiReset.done")) } }); return
        case "factory_reset": Ui.dialogs.confirm(Tr.t("settings.factory.confirm"), Tr.t("settings.factory.button"), true, function(ok) { if (ok) { post(A("/factory_reset"), {}); say(Tr.t("settings.factory.running")) } }); return
        case "alarm_toggle": lms(["alarm", "update", "id:" + arg, "enabled:" + (row.on ? 0 : 1)]); row.on = !row.on; break
        case "alarm_delete": lms(["alarm", "delete", "id:" + arg]); break
        case "alarm_hour": {
            var hours = []; for (var hh = 0; hh < 24; hh++) hours.push(String(hh).padStart(2, "0"))
            Ui.dialogs.pick(Tr.t("settings.sections.alarm"), hours, alarmH, function(i) { if (i >= 0) { alarmH = i; rebuild() } })
            return
        }
        case "alarm_min": {
            var mins = []; for (var mm = 0; mm < 12; mm++) mins.push(String(mm * 5).padStart(2, "0"))
            Ui.dialogs.pick(Tr.t("settings.sections.alarm"), mins, alarmM / 5, function(i) { if (i >= 0) { alarmM = i * 5; rebuild() } })
            return
        }
        case "alarm_add": lms(["alarm", "add", "time:" + (alarmH * 3600 + alarmM * 60), "dow:0,1,2,3,4,5,6", "enabled:1"]); break
        case "sync_toggle": lms(row.on ? ["sync", "-"] : ["sync", arg]); say(Tr.t("settings.multiroom.saved")); break
        default: return
        }
        rebuild()
    }
    function pickBrowse(path) { pickBusy = true; cfg.browse(2, "", path) }
    Timer {
        id: countTimer
        interval: 1000; repeat: true; running: root.countdown > 0
        onTriggered: {
            root.countdown--
            if (root.countdown <= 0) { root.post(cfg.api("/ui_refresh"), { mode: "native" }); cfg.uiRefresh = "native"; root.say(Tr.t("settings.uiRefresh.reverted")) }
            else root.rebuild()
        }
    }
    // while the store checks its list or installs a skin, its state is re-read
    Timer {
        interval: 1500; repeat: true
        running: root.visible && root.active >= 0 && root.secs[root.active].id === "vuMeters" && (cfg.vuStore.checking || cfg.vuStore.busy)
        onTriggered: cfg.loadStore(false)
    }
    Timer {
        interval: 1500; repeat: true
        running: root.visible && root.active >= 0 && root.secs[root.active].id === "animations" && (cfg.animStore.checking || cfg.animStore.busy)
        onTriggered: cfg.loadAnimStore(false)
    }
    // mentre il disco si formatta lo stato va riletto da solo
    Timer { interval: 2000; repeat: true; running: root.fmtWatch; onTriggered: { if (!Ui.dialogs.active) root.fmtWatch = false; else cfg.load() } }

    // ─── la pagina ─────────────────────────────────────────────────────────
    Flickable {
        id: page
        anchors.fill: parent
        contentHeight: body.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickDeceleration: 1500; maximumFlickVelocity: 4000
        Item {
            id: body
            width: page.width
            height: 32 + (root.atRoot ? rootHead.height + 32 + secList.height : secHead.height + 32 + panel.height) + 32
            // elenco delle sezioni
            Column {
                id: rootHead
                visible: root.atRoot
                x: 32; y: 32; width: parent.width - 64
                Text { height: 40; verticalAlignment: Text.AlignVCenter; text: Tr.t("settings.title"); color: Theme.white; font.family: Theme.font; font.pixelSize: 36; font.bold: true }
                Item { width: 1; height: 8 }
                Text { height: 28; verticalAlignment: Text.AlignVCenter; text: Tr.t("settings.subtitle"); color: Theme.silver; font.family: Theme.font; font.pixelSize: 18 }
                Row {
                    visible: !cfg.loaded || !cfg.apiOk
                    height: 20; spacing: 8
                    Spinner { visible: !cfg.loaded; active: root.visible && root.atRoot; radius: 8; thickness: 2; anchors.verticalCenter: parent.verticalCenter }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: !cfg.loaded ? Tr.t("settings.loadingSystem") : Tr.t("settings.apiUnavailable"); color: !cfg.loaded ? Theme.gold : Theme.red300; font.family: Theme.font; font.pixelSize: 14 }
                }
            }
            Column {
                id: secList
                visible: root.atRoot
                x: 32; y: rootHead.y + rootHead.height + 32; width: parent.width - 64; spacing: 8
                Repeater {
                    model: root.listedSecs
                    Item {
                        id: secRow
                        required property var modelData
                        required property int index
                        width: parent.width; height: 72
                        // shadow-hifi: 0 4px 20px nero/50 + inset 0 1px 0 bianco/10
                        BoxShadow { targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 20; offsetY: 4; color: Theme.blackA(0.5) }
                        Rectangle {
                            anchors.fill: parent; radius: 16
                            color: sTap.mix(Theme.gray, Theme.light); border.width: 1; border.color: Theme.accent
                            Rectangle { x: 10; y: 1; width: parent.width - 20; height: 1; color: Theme.wa(0.1) }   // il riflesso a tutta larghezza, dentro gli angoli
                            Rectangle { x: 16; y: 17; width: 38; height: 38; radius: 8; color: Theme.goldA(0.2)
                                        Icon { anchors.centerIn: parent; name: secRow.modelData.id === "displayMode" && cfg.displayMode === "headless" ? "monitor-off" : secRow.modelData.icon; size: 22; color: Theme.gold } }
                            Text { x: 66; width: parent.width - 66 - 46; anchors.verticalCenter: parent.verticalCenter; text: Tr.t(secRow.modelData.key); elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 18 }
                            // news in the VU meter store: new skins or updates of downloaded ones
                            Rectangle { visible: (secRow.modelData.id === "vuMeters" && cfg.vuStoreNew > 0) || (secRow.modelData.id === "animations" && cfg.animStoreNew > 0); x: parent.width - 16 - 22 - 20; anchors.verticalCenter: parent.verticalCenter; width: 10; height: 10; radius: 5; color: Theme.gold }
                            Icon { x: parent.width - 16 - 22; anchors.verticalCenter: parent.verticalCenter; name: "chevron-right"; size: 22; color: Theme.silver }
                        }
                        Tap { id: sTap; onClicked: root.openSection(secRow.modelData.id) }
                    }
                }
            }
            // sezione aperta: freccia + titolo, poi il pannello
            Item {
                id: secHead
                visible: !root.atRoot
                x: 32; y: 32; width: parent.width - 64; height: 36
                Item {
                    width: 44; height: 36
                    Icon { x: 0; anchors.verticalCenter: parent.verticalCenter; name: "chevron-left"; size: 32; color: Theme.gold }
                    Tap { grow: 8; onClicked: root.goBack() }
                }
                Text { x: 44; width: parent.width - 44; height: 36; verticalAlignment: Text.AlignVCenter; text: root.active >= 0 ? Tr.t(root.secs[root.active].key) : ""; elide: Text.ElideRight; color: Theme.white; font.family: Theme.font; font.pixelSize: 30; font.bold: true }
            }
            Rectangle {
                id: panel
                visible: !root.atRoot
                x: 32; y: secHead.y + secHead.height + 32; width: parent.width - 64
                height: panelRows.height + 48
                radius: 16; color: Theme.gray; border.width: 1; border.color: Theme.accent
                BoxShadow { z: -1; targetX: 0; targetY: 0; targetW: parent.width; targetH: parent.height; radius: 16; blur: 20; offsetY: 4; color: Theme.blackA(0.5) }   // shadow-hifi
                Rectangle { x: 10; y: 1; width: parent.width - 20; height: 1; color: Theme.wa(0.1) }
                SettingsRows { id: panelRows; x: 24; y: 24; width: parent.width - 48; rows: root.rows }
            }
            // one gold flash around the row a shortcut landed on
            Rectangle {
                id: markFlash
                opacity: 0; radius: 12
                color: "transparent"; border.width: 2; border.color: Theme.gold
                SequentialAnimation {
                    id: markFlashAnim
                    NumberAnimation { target: markFlash; property: "opacity"; to: 1; duration: 150 }
                    PauseAnimation { duration: 700 }
                    NumberAnimation { target: markFlash; property: "opacity"; to: 0; duration: 500 }
                }
            }
        }
        ScrollBar_ { flick: page; x: page.width - 3 }
    }
}
