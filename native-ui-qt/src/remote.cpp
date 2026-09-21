#include "remote.h"
#include "sys.h"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSocketNotifier>
#include <QtDebug>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

// Codici che le intestazioni di sistema piu' vecchie potrebbero non avere:
// meglio dichiararli qui che perdere un tasto a seconda di dove si compila.
#ifndef KEY_OK
#define KEY_OK 0x160
#endif
#ifndef KEY_SELECT
#define KEY_SELECT 0x161
#endif
#ifndef KEY_INFO
#define KEY_INFO 0x166
#endif
#ifndef KEY_FAVORITES
#define KEY_FAVORITES 0x16c
#endif
#ifndef KEY_LIST
#define KEY_LIST 0x18b
#endif
#ifndef KEY_SHUFFLE
#define KEY_SHUFFLE 0x1bc
#endif
#ifndef KEY_CONTEXT_MENU
#define KEY_CONTEXT_MENU 0x1b6
#endif

namespace {

struct KeyDef {
    int code;
    const char *name;      // come lo chiama il nucleo
    const char *action;    // "" = riconosciuto ma non assegnato
};

// La mappa di serie: i codici HID che manda un telecomando qualsiasi. Chi ne
// manda di diversi se li assegna dal pannello di prova (remote-keys.json).
const KeyDef kKeys[] = {
    // riproduzione
    { KEY_PLAYPAUSE,    "KEY_PLAYPAUSE",    "playPause" },
    { KEY_PLAY,         "KEY_PLAY",         "play" },
    { KEY_PLAYCD,       "KEY_PLAYCD",       "play" },
    { KEY_PAUSE,        "KEY_PAUSE",        "pause" },
    { KEY_PAUSECD,      "KEY_PAUSECD",      "pause" },
    { KEY_STOP,         "KEY_STOP",         "stop" },
    { KEY_STOPCD,       "KEY_STOPCD",       "stop" },
    { KEY_NEXTSONG,     "KEY_NEXTSONG",     "next" },
    { KEY_PREVIOUSSONG, "KEY_PREVIOUSSONG", "prev" },
    { KEY_NEXT,         "KEY_NEXT",         "next" },
    { KEY_PREVIOUS,     "KEY_PREVIOUS",     "prev" },
    { KEY_FASTFORWARD,  "KEY_FASTFORWARD",  "forward" },
    { KEY_REWIND,       "KEY_REWIND",       "rewind" },
    // volume
    { KEY_VOLUMEUP,     "KEY_VOLUMEUP",     "volumeUp" },
    { KEY_VOLUMEDOWN,   "KEY_VOLUMEDOWN",   "volumeDown" },
    { KEY_MUTE,         "KEY_MUTE",         "mute" },
    // navigazione
    { KEY_UP,           "KEY_UP",           "up" },
    { KEY_DOWN,         "KEY_DOWN",         "down" },
    { KEY_LEFT,         "KEY_LEFT",         "left" },
    { KEY_RIGHT,        "KEY_RIGHT",        "right" },
    { KEY_ENTER,        "KEY_ENTER",        "ok" },
    { KEY_KPENTER,      "KEY_KPENTER",      "ok" },
    { KEY_OK,           "KEY_OK",           "ok" },
    { KEY_SELECT,       "KEY_SELECT",       "ok" },
    { KEY_SPACE,        "KEY_SPACE",        "ok" },
    { KEY_ESC,          "KEY_ESC",          "back" },
    { KEY_BACK,         "KEY_BACK",         "back" },
    { KEY_BACKSPACE,    "KEY_BACKSPACE",    "back" },
    { KEY_EXIT,         "KEY_EXIT",         "back" },
    { KEY_HOME,         "KEY_HOME",         "home" },
    { KEY_HOMEPAGE,     "KEY_HOMEPAGE",     "home" },
    { KEY_MENU,         "KEY_MENU",         "menu" },
    { KEY_CONTEXT_MENU, "KEY_CONTEXT_MENU", "menu" },
    { KEY_PAGEUP,       "KEY_PAGEUP",       "pageUp" },
    { KEY_PAGEDOWN,     "KEY_PAGEDOWN",     "pageDown" },
    // il resto dell'interfaccia
    { KEY_INFO,         "KEY_INFO",         "nowPlaying" },
    { KEY_MEDIA,        "KEY_MEDIA",        "nowPlaying" },
    { KEY_LIST,         "KEY_LIST",         "queue" },
    { KEY_SEARCH,       "KEY_SEARCH",       "search" },
    { KEY_FIND,         "KEY_FIND",         "search" },
    { KEY_FAVORITES,    "KEY_FAVORITES",    "favorite" },
    { KEY_SHUFFLE,      "KEY_SHUFFLE",      "shuffle" },
    // 🚨 spegnere l'apparecchio dal telecomando, no: il tasto manda lo
    // schermo a riposo (e un tocco qualsiasi lo risveglia). Un telecomando in
    // una tasca non deve poter spegnere quello che sta suonando.
    { KEY_POWER,        "KEY_POWER",        "standby" },
    { KEY_SLEEP,        "KEY_SLEEP",        "standby" },
    { KEY_EJECTCD,      "KEY_EJECTCD",      "eject" },
    { KEY_EJECTCLOSECD, "KEY_EJECTCLOSECD", "eject" },
    // riconosciuti ma senza azione: cosi' il pannello di prova li sa
    // chiamare per nome invece di mostrare un numero
    { KEY_RECORD,       "KEY_RECORD",       "" },
    { KEY_RED,          "KEY_RED",          "" },
    { KEY_GREEN,        "KEY_GREEN",        "" },
    { KEY_YELLOW,       "KEY_YELLOW",       "" },
    { KEY_BLUE,         "KEY_BLUE",         "" },
    { KEY_CHANNELUP,    "KEY_CHANNELUP",    "" },
    { KEY_CHANNELDOWN,  "KEY_CHANNELDOWN",  "" },
    { KEY_1, "KEY_1", "" }, { KEY_2, "KEY_2", "" }, { KEY_3, "KEY_3", "" },
    { KEY_4, "KEY_4", "" }, { KEY_5, "KEY_5", "" }, { KEY_6, "KEY_6", "" },
    { KEY_7, "KEY_7", "" }, { KEY_8, "KEY_8", "" }, { KEY_9, "KEY_9", "" },
    { KEY_0, "KEY_0", "" },
    { KEY_NUMERIC_1, "KEY_NUMERIC_1", "" }, { KEY_NUMERIC_2, "KEY_NUMERIC_2", "" },
    { KEY_NUMERIC_3, "KEY_NUMERIC_3", "" }, { KEY_NUMERIC_4, "KEY_NUMERIC_4", "" },
    { KEY_NUMERIC_5, "KEY_NUMERIC_5", "" }, { KEY_NUMERIC_6, "KEY_NUMERIC_6", "" },
    { KEY_NUMERIC_7, "KEY_NUMERIC_7", "" }, { KEY_NUMERIC_8, "KEY_NUMERIC_8", "" },
    { KEY_NUMERIC_9, "KEY_NUMERIC_9", "" }, { KEY_NUMERIC_0, "KEY_NUMERIC_0", "" },
};

// Le azioni assegnabili, nell'ordine in cui si mostrano nell'elenco.
const char *const kActions[] = {
    "playPause", "play", "pause", "stop", "next", "prev", "forward", "rewind",
    "volumeUp", "volumeDown", "mute",
    "up", "down", "left", "right", "ok", "back", "home", "menu", "pageUp", "pageDown",
    "nowPlaying", "fullScreen", "nextVu", "nextAnimation",
    "queue", "search", "favorite", "shuffle", "standby", "eject",
};

// I tasti Qt: la stessa tabella, ma dal lato di chi li riceve gia' tradotti.
// 🚨 Le frecce e invio ci sono di proposito: da qui passano le tastiere e i
// telecomandi che non prendiamo in esclusiva, e senza queste righe su quei
// dispositivi non si navigherebbe.
struct QtKeyDef { int key; const char *action; };
const QtKeyDef kQtKeys[] = {
    { Qt::Key_Up, "up" }, { Qt::Key_Down, "down" }, { Qt::Key_Left, "left" }, { Qt::Key_Right, "right" },
    { Qt::Key_Return, "ok" }, { Qt::Key_Enter, "ok" }, { Qt::Key_Select, "ok" }, { Qt::Key_Space, "ok" },
    { Qt::Key_Escape, "back" }, { Qt::Key_Back, "back" }, { Qt::Key_Backspace, "back" },
    { Qt::Key_HomePage, "home" }, { Qt::Key_Home, "home" },
    { Qt::Key_Menu, "menu" }, { Qt::Key_Context1, "menu" },
    { Qt::Key_PageUp, "pageUp" }, { Qt::Key_PageDown, "pageDown" },
    { Qt::Key_MediaTogglePlayPause, "playPause" }, { Qt::Key_MediaPlay, "play" },
    { Qt::Key_MediaPause, "pause" }, { Qt::Key_MediaStop, "stop" },
    { Qt::Key_MediaNext, "next" }, { Qt::Key_MediaPrevious, "prev" },
    { Qt::Key_AudioForward, "forward" }, { Qt::Key_AudioRewind, "rewind" },
    { Qt::Key_VolumeUp, "volumeUp" }, { Qt::Key_VolumeDown, "volumeDown" }, { Qt::Key_VolumeMute, "mute" },
    { Qt::Key_Search, "search" }, { Qt::Key_Favorites, "favorite" },
    { Qt::Key_LaunchMedia, "nowPlaying" }, { Qt::Key_Eject, "eject" },
};

// Quali azioni hanno senso ripetute a tasto premuto.
bool repeatable(const QString &a) {
    return a == "up" || a == "down" || a == "left" || a == "right"
        || a == "volumeUp" || a == "volumeDown"
        || a == "forward" || a == "rewind" || a == "pageUp" || a == "pageDown";
}

// I tasti che un dispositivo NON preso (una tastiera con i tasti multimediali,
// un air mouse) puo' comandare: solo quelli che Qt non porta da solo.
bool mediaOnly(const QString &a) {
    return a == "playPause" || a == "play" || a == "pause" || a == "stop"
        || a == "next" || a == "prev" || a == "forward" || a == "rewind"
        || a == "volumeUp" || a == "volumeDown" || a == "mute"
        || a == "nowPlaying" || a == "queue" || a == "favorite"
        || a == "shuffle" || a == "eject" || a == "standby"
        || a == "fullScreen" || a == "nextVu" || a == "nextAnimation";
}

}  // namespace

Remote::Remote(const QString &configDir, QObject *parent) : QObject(parent), m_configDir(configDir) {
    m_clock.start();
    {   // quale dispositivo l'utente ha indicato come il suo telecomando
        QFile f(m_configDir + "/remote-device");
        if (f.open(QIODevice::ReadOnly | QIODevice::Text))
            m_chosen = QString::fromUtf8(f.readLine()).trimmed();
    }
    loadCustom();
    m_repeat.setSingleShot(false);
    connect(&m_repeat, &QTimer::timeout, this, [this]() {
        if (m_repeatAction.isEmpty()) { m_repeat.stop(); return; }
        m_repeat.setInterval(120);
        dispatch(m_repeatAction, true, QStringLiteral("evdev"));
    });
    m_rescan.setSingleShot(true);
    m_rescan.setInterval(600);       // un dispositivo appena collegato appare in piu' passi
    connect(&m_rescan, &QTimer::timeout, this, &Remote::rescan);
    const QString devDir = qEnvironmentVariable("HIFI_INPUT_DEV", QStringLiteral("/dev/input"));
    if (QDir(devDir).exists()) {
        m_watch.addPath(devDir);
        connect(&m_watch, &QFileSystemWatcher::directoryChanged, this, [this]() { m_rescan.start(); });
    }
    rescan();
}

Remote::~Remote() {
    const QStringList paths = m_open.keys();
    for (const QString &p : paths) closeDevice(p);
}

// ─── quali dispositivi sono telecomandi ────────────────────────────────────
void Remote::rescan() {
    QString sysRoot = qEnvironmentVariable("HIFI_SYSFS_INPUT");
    if (sysRoot.isEmpty()) sysRoot = QStringLiteral("/sys/class/input");
    const QString devDir = qEnvironmentVariable("HIFI_INPUT_DEV", QStringLiteral("/dev/input"));

    QStringList seen;
    const QStringList entries = QDir(sysRoot).entryList(QStringList("input*"), QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QString &e : entries) {
        const QString dir = sysRoot + "/" + e;
        // il nodo /dev di questo dispositivo: la sottocartella eventN
        const QStringList evs = QDir(dir).entryList(QStringList("event*"), QDir::Dirs | QDir::NoDotAndDotDot);
        if (evs.isEmpty()) continue;
        const QString path = devDir + "/" + evs.first();

        const QString key = hifiSysfsRead(dir + "/capabilities/key");
        if (key.isEmpty()) continue;
        const QString rel = hifiSysfsRead(dir + "/capabilities/rel");
        const QString abs = hifiSysfsRead(dir + "/capabilities/abs");

        // tastiera completa: tutti i tasti da ESC a D (1..31), la stessa
        // regola di udev che usa Sys per la tastiera a schermo
        bool fullKeyboard = true;
        for (int b = 1; b <= 31 && fullKeyboard; b++) if (!hifiSysfsBit(key, b)) fullKeyboard = false;

        // tasti multimediali: bastano questi per dire "qui c'e' un telecomando"
        const bool media = hifiSysfsBit(key, KEY_PLAYPAUSE) || hifiSysfsBit(key, KEY_NEXTSONG)
                        || hifiSysfsBit(key, KEY_PREVIOUSSONG) || hifiSysfsBit(key, KEY_PLAYCD)
                        || hifiSysfsBit(key, KEY_STOPCD) || hifiSysfsBit(key, KEY_PLAY);
        // tastierino di navigazione (frecce + un tasto di conferma)
        const bool nav = hifiSysfsBit(key, KEY_UP) && hifiSysfsBit(key, KEY_DOWN)
                      && hifiSysfsBit(key, KEY_LEFT) && hifiSysfsBit(key, KEY_RIGHT)
                      && (hifiSysfsBit(key, KEY_ENTER) || hifiSysfsBit(key, KEY_OK) || hifiSysfsBit(key, KEY_SELECT));
        if (!media && !(nav && !fullKeyboard)) continue;

        // 🚨 niente presa esclusiva su chi e' anche puntatore o tastiera: il
        // puntatore si fermerebbe e non si scriverebbe piu'
        const bool pointer = hifiSysfsBit(rel, REL_X) && hifiSysfsBit(rel, REL_Y);
        const bool tablet = hifiSysfsBit(abs, ABS_X) || hifiSysfsBit(abs, ABS_MT_POSITION_X);
        const bool isRemote = !fullKeyboard && !pointer && !tablet;

        seen << path;
        if (m_open.contains(path)) continue;
        openDevice(path);
        if (!m_open.contains(path)) continue;
        Dev &dev = m_open[path];
        dev.name = hifiSysfsRead(dir + "/name");
        if (dev.name.isEmpty()) dev.name = evs.first();
        const int bus = hifiSysfsRead(dir + "/id/bustype").toInt(nullptr, 16);
        dev.bus = bus == BUS_BLUETOOTH ? "bluetooth" : bus == BUS_USB ? "usb" : "other";
        dev.remote = isRemote;
        dev.chosen = !m_chosen.isEmpty() && dev.name == m_chosen;
        if (isRemote && ioctl(dev.fd, EVIOCGRAB, 1) == 0) dev.grabbed = true;
        qInfo("remote: %s (%s%s) su %s", qPrintable(dev.name), qPrintable(dev.bus),
              dev.grabbed ? ", presa esclusiva" : isRemote ? ", senza presa esclusiva" : ", solo tasti multimediali",
              qPrintable(path));
    }

    // quelli spariti
    const QStringList had = m_open.keys();
    for (const QString &p : had) if (!seen.contains(p)) { qInfo("remote: %s scollegato", qPrintable(p)); closeDevice(p); }
    publishDevices();
}

void Remote::openDevice(const QString &path) {
    const int fd = ::open(path.toLocal8Bit().constData(), O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) {
        // niente permessi (sviluppo da utente normale): non e' un guasto
        qInfo("remote: %s non si apre (%s)", qPrintable(path), strerror(errno));
        return;
    }
    Dev dev;
    dev.path = path;
    dev.fd = fd;
    dev.notifier = new QSocketNotifier(fd, QSocketNotifier::Read, this);
    connect(dev.notifier, &QSocketNotifier::activated, this, [this, path]() { readFrom(path); });
    m_open.insert(path, dev);
}

void Remote::closeDevice(const QString &path) {
    if (!m_open.contains(path)) return;
    Dev dev = m_open.take(path);
    if (dev.notifier) { dev.notifier->setEnabled(false); dev.notifier->deleteLater(); }
    if (dev.fd >= 0) {
        if (dev.grabbed) ioctl(dev.fd, EVIOCGRAB, 0);
        ::close(dev.fd);
    }
    // un tasto tenuto premuto su un telecomando che sparisce non resta premuto
    stopRepeat();
}

void Remote::readFrom(const QString &path) {
    if (!m_open.contains(path)) return;
    struct input_event ev;
    for (;;) {
        const ssize_t n = ::read(m_open[path].fd, &ev, sizeof(ev));
        if (n != sizeof(ev)) {
            // il dispositivo se n'e' andato mentre lo leggevamo. 🚨 Anche n == 0
            // conta: un evdev vero non finisce mai, ma se finisse il notificatore
            // continuerebbe a svegliarci su una lettura che non da' niente.
            if (n == 0 || (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) { closeDevice(path); publishDevices(); }
            return;
        }
        if (ev.type != EV_KEY) continue;
        if (!m_open.contains(path)) return;
        onKey(m_open[path], ev.code, ev.value);
    }
}

void Remote::onKey(Dev &dev, int code, int value) {
    const QString act = actionFor(code, dev.name);

    if (value == 0) {                       // rilasciato
        if (code == m_repeatCode) stopRepeat();
        return;
    }

    if (m_learning) {
        // 🚨 Un dispositivo solo. Con una tastiera accanto al telecomando, un
        // tasto premuto li' si prendeva il posto di quello del telecomando —
        // e l'assegnazione finiva sul dispositivo sbagliato.
        if (m_learnDevice.isEmpty()) {
            m_learnDevice = dev.name;
            emit learnDeviceChanged();
        }
        if (dev.name != m_learnDevice) return;
        m_lastKey = QVariantMap{ { "code", code }, { "key", keyName(code) }, { "action", act },
                                 { "device", dev.name }, { "at", m_clock.elapsed() } };
        emit lastKeyChanged();
        return;                             // in prova non si agisce
    }
    m_lastKey = QVariantMap{ { "code", code }, { "key", keyName(code) }, { "action", act },
                             { "device", dev.name }, { "at", m_clock.elapsed() } };
    emit lastKeyChanged();

    if (act.isEmpty()) return;
    // Da un dispositivo che NON e' un telecomando (una tastiera, un air mouse)
    // solo i tasti multimediali: frecce e invio li porta gia' Qt, e agire due
    // volte sullo stesso tasto sarebbe peggio che non agire. Se invece e' un
    // telecomando — o l'utente ha detto che quello e' il suo telecomando,
    // anche se si presenta come una tastiera — si ascolta tutto: al doppione
    // ci pensa il filtro in dispatch().
    if (!dev.remote && !dev.chosen && !mediaOnly(act)) return;

    if (value == 2) {                       // ripetizione del nucleo
        if (!repeatable(act)) return;
        m_kernelRepeats = true;
        m_repeat.stop();
        dispatch(act, true, QStringLiteral("evdev"));
        return;
    }
    dispatch(act, false, QStringLiteral("evdev"));
    if (repeatable(act)) { m_repeatCode = code; startRepeat(act); }
}

void Remote::startRepeat(const QString &act) {
    m_repeatAction = act;
    m_kernelRepeats = false;
    // 400 ms prima della seconda, poi una ogni 120: la stessa cadenza di una
    // tastiera. Se intanto arrivano le ripetizioni del nucleo, il timer si
    // ferma e comandano quelle.
    m_repeat.setInterval(400);
    m_repeat.start();
}

void Remote::stopRepeat() {
    m_repeat.stop();
    m_repeatAction.clear();
    m_repeatCode = 0;
}

void Remote::dispatch(const QString &act, bool repeat, const QString &source) {
    if (act.isEmpty()) return;
    const qint64 now = m_clock.elapsed();
    // 🚨 stesso tasto da due sorgenti: un dispositivo che leggiamo noi e che
    // legge anche Qt manderebbe due volte la stessa azione (play/pausa due
    // volte = niente). Entro un quarto di secondo la seconda si butta — e a
    // tasto tenuto premuto vale lo stesso, con una finestra piu' corta della
    // nostra ripetizione, o la lista scorrerebbe a velocita' doppia.
    if (act == m_lastAction && source != m_lastSource && now - m_lastAt < (repeat ? 100 : 250)) return;
    m_lastAction = act;
    m_lastSource = source;
    m_lastAt = now;
    emit action(act, repeat);
}

// ─── nomi, azioni, assegnazioni ────────────────────────────────────────────
QString Remote::actionFor(int code, const QString &device) const {
    // prima quello che l'utente ha deciso per QUESTO dispositivo...
    if (!device.isEmpty()) {
        const auto d = m_custom.constFind(device);
        if (d != m_custom.constEnd()) {
            const auto it = d->constFind(code);
            if (it != d->constEnd()) return it.value();
        }
    }
    // ...poi quello che vale per tutti...
    const auto all = m_custom.constFind(QString());
    if (all != m_custom.constEnd()) {
        const auto it = all->constFind(code);
        if (it != all->constEnd()) return it.value();
    }
    // ...e infine la mappa di serie
    for (const KeyDef &k : kKeys) if (k.code == code) return QString::fromLatin1(k.action);
    return QString();
}

QString Remote::actionForQtKey(int key) const {
    for (const QtKeyDef &k : kQtKeys) if (k.key == key) return QString::fromLatin1(k.action);
    return QString();
}

QString Remote::keyName(int code) const {
    for (const KeyDef &k : kKeys) if (k.code == code) return QString::fromLatin1(k.name);
    return QStringLiteral("#%1").arg(code);
}

QStringList Remote::actionNames() const {
    QStringList out;
    for (const char *a : kActions) out << QString::fromLatin1(a);
    return out;
}

// remote-keys.json:
//   { "all": { "164": "playPause" },
//     "devices": { "G20S PRO Keyboard": { "398": "home" } } }
// 🚨 Un file del primo giorno era una mappa piatta codice -> azione: quello si
// legge ancora, e vale per tutti i dispositivi.
void Remote::loadCustom() {
    m_custom.clear();
    QFile f(m_configDir + "/remote-keys.json");
    if (!f.open(QIODevice::ReadOnly)) return;
    const QJsonObject o = QJsonDocument::fromJson(f.readAll()).object();
    auto readMap = [this](const QJsonObject &src, const QString &device) {
        QHash<int, QString> m;
        for (auto it = src.constBegin(); it != src.constEnd(); ++it) {
            bool ok = false;
            const int code = it.key().toInt(&ok);
            if (ok) m.insert(code, it.value().toString());
        }
        if (!m.isEmpty()) m_custom.insert(device, m);
    };
    if (o.contains("all") || o.contains("devices")) {
        readMap(o.value("all").toObject(), QString());
        const QJsonObject devs = o.value("devices").toObject();
        for (auto it = devs.constBegin(); it != devs.constEnd(); ++it) readMap(it.value().toObject(), it.key());
    } else {
        readMap(o, QString());          // il formato piatto di prima
    }
    int n = 0;
    for (const auto &m : std::as_const(m_custom)) n += m.size();
    if (n) qInfo("remote: %d tasti assegnati a mano su %lld dispositivi", n, (long long)m_custom.size());
}

bool Remote::assign(int code, const QString &act, const QString &device) {
    if (code <= 0) return false;
    if (!act.isEmpty() && !actionNames().contains(act)) return false;
    m_custom[device].insert(code, act);     // azione vuota = questo tasto non fa niente
    return saveCustom(code, device);
}

bool Remote::forget(int code, const QString &device) {
    const auto d = m_custom.find(device);
    if (d == m_custom.end() || !d->contains(code)) return true;
    d->remove(code);
    if (d->isEmpty()) m_custom.erase(d);
    return saveCustom(code, device);
}

bool Remote::isCustom(int code, const QString &device) const {
    if (!device.isEmpty()) {
        const auto d = m_custom.constFind(device);
        if (d != m_custom.constEnd() && d->contains(code)) return true;
    }
    const auto all = m_custom.constFind(QString());
    return all != m_custom.constEnd() && all->contains(code);
}

bool Remote::saveCustom(int code, const QString &device) {
    QJsonObject all, devices;
    for (auto d = m_custom.constBegin(); d != m_custom.constEnd(); ++d) {
        QJsonObject m;
        for (auto it = d->constBegin(); it != d->constEnd(); ++it) m.insert(QString::number(it.key()), it.value());
        if (d.key().isEmpty()) all = m; else devices.insert(d.key(), m);
    }
    QJsonObject o;
    o.insert("all", all);
    o.insert("devices", devices);

    QDir().mkpath(m_configDir);
    QFile f(m_configDir + "/remote-keys.json.tmp");
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) return false;
    f.write(QJsonDocument(o).toJson(QJsonDocument::Indented));
    f.close();
    QFile::remove(m_configDir + "/remote-keys.json");
    if (!QFile::rename(m_configDir + "/remote-keys.json.tmp", m_configDir + "/remote-keys.json")) return false;
    // l'ultimo tasto mostrato nel pannello prende subito la nuova azione
    if (m_lastKey.value("code").toInt() == code && m_lastKey.value("device").toString() == device) {
        m_lastKey["action"] = actionFor(code, device);
        emit lastKeyChanged();
    }
    return true;
}

void Remote::setLearning(bool on) {
    if (m_learning == on) return;
    m_learning = on;
    if (on) stopRepeat();
    // Si riparte dal telecomando dichiarato, se c'e'; altrimenti dal primo che
    // manda un tasto. Chiudendo la prova si dimentica tutto.
    const QString want = on ? m_chosen : QString();
    if (m_learnDevice != want) { m_learnDevice = want; emit learnDeviceChanged(); }
    if (!on && !m_lastKey.isEmpty()) { m_lastKey.clear(); emit lastKeyChanged(); }
    emit learningChanged();
}

void Remote::listenAgain() {
    if (!m_learnDevice.isEmpty()) { m_learnDevice.clear(); emit learnDeviceChanged(); }
    if (!m_lastKey.isEmpty()) { m_lastKey.clear(); emit lastKeyChanged(); }
}

void Remote::setChosen(const QString &device) {
    if (m_chosen == device) return;
    m_chosen = device;
    QDir().mkpath(m_configDir);
    QFile f(m_configDir + "/remote-device");
    if (f.open(QIODevice::WriteOnly | QIODevice::Truncate)) f.write(device.toUtf8() + "\n");
    for (auto it = m_open.begin(); it != m_open.end(); ++it)
        it->chosen = !m_chosen.isEmpty() && it->name == m_chosen;
    // in prova si passa ad ascoltare lui
    if (m_learning && m_learnDevice != m_chosen) { m_learnDevice = m_chosen; emit learnDeviceChanged(); }
    publishDevices();
}

void Remote::publishDevices() {
    QVariantList out;
    QStringList paths = m_open.keys();
    paths.sort();                    // l'elenco sullo schermo non deve ballare
    for (const QString &p : paths) {
        const Dev &d = m_open[p];
        out.append(QVariantMap{ { "name", d.name }, { "path", d.path }, { "bus", d.bus },
                                { "kind", d.remote ? "remote" : "keyboard" }, { "grabbed", d.grabbed },
                                { "chosen", d.chosen } });
    }
    m_devices = out;
    emit devicesChanged();
}
