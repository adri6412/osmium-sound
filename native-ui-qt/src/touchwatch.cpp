#include "touchwatch.h"
#include "sys.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSocketNotifier>
#include <QtDebug>

#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {
qint64 nowMs() { return QDateTime::currentMSecsSinceEpoch(); }
const char *kState = "/run/hifi-touch.json";
constexpr qint64 kStuckMs = 30000;        // a finger down this long, untouched: suspicious
constexpr qint64 kMissedMs = 1500;        // a touch the interface should have had by now

// the USB device a node belongs to (…/usb1/1-2), for the log and for the
// software "unplug": the first parent that has both `authorized` and `idVendor`
QString usbOf(const QString &inputDir) {
    QString p = QFileInfo(inputDir + "/device").canonicalFilePath();
    for (int i = 0; i < 8 && !p.isEmpty() && p != "/"; i++) {
        if (QFile::exists(p + "/authorized") && QFile::exists(p + "/idVendor")) return QFileInfo(p).fileName();
        p = QFileInfo(p).path();
    }
    return QString();
}

// what the kernel says is down right now: BTN_TOUCH, and the slots with a
// tracking id. Both fail harmlessly on the fake nodes of the test rig.
bool keyDown(int fd, int code) {
    unsigned char bits[KEY_MAX / 8 + 1] = {};
    if (ioctl(fd, EVIOCGKEY(sizeof(bits)), bits) < 0) return false;
    return bits[code / 8] & (1 << (code % 8));
}
QSet<int> slotsDown(int fd) {
    QSet<int> out;
    struct input_absinfo info {};
    if (ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &info) < 0 || info.maximum < 0 || info.maximum > 63) return out;
    const int n = info.maximum + 1;
    struct { __u32 code; __s32 values[64]; } req {};
    req.code = ABS_MT_TRACKING_ID;
    if (ioctl(fd, EVIOCGMTSLOTS(sizeof(__u32) + n * sizeof(__s32)), &req) < 0) return out;
    for (int i = 0; i < n; i++) if (req.values[i] >= 0) out.insert(i);
    return out;
}
}  // namespace

TouchWatch::TouchWatch(QObject *parent) : QObject(parent) {
    m_rescan.setSingleShot(true);
    m_rescan.setInterval(700);                // a panel that comes back appears in steps
    connect(&m_rescan, &QTimer::timeout, this, &TouchWatch::rescan);
    const QString devDir = qEnvironmentVariable("HIFI_INPUT_DEV", QStringLiteral("/dev/input"));
    if (QDir(devDir).exists()) {
        m_watch.addPath(devDir);
        connect(&m_watch, &QFileSystemWatcher::directoryChanged, this, [this]() { m_rescan.start(); });
    }
    m_tick.setInterval(1000);
    connect(&m_tick, &QTimer::timeout, this, &TouchWatch::check);
    m_tick.start();
    rescan();
}

TouchWatch::~TouchWatch() {
    const QStringList paths = m_devs.keys();
    for (const QString &p : paths) close(p, false);
}

void TouchWatch::noteQt() {
    m_qtLast = nowMs();
    for (auto it = m_devs.begin(); it != m_devs.end(); ++it) it->pendingSince = 0;
}

// the touchscreens: absolute axes on a device you touch where you look
// (INPUT_PROP_DIRECT) — a touchpad has the axes but not the property
void TouchWatch::rescan() {
    QString sysRoot = qEnvironmentVariable("HIFI_SYSFS_INPUT");
    if (sysRoot.isEmpty()) sysRoot = QStringLiteral("/sys/class/input");
    const QString devDir = qEnvironmentVariable("HIFI_INPUT_DEV", QStringLiteral("/dev/input"));
    QStringList seen;
    const QStringList entries = QDir(sysRoot).entryList(QStringList("input*"), QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QString &e : entries) {
        const QString dir = sysRoot + "/" + e;
        const QString abs = hifiSysfsRead(dir + "/capabilities/abs");
        if (!hifiSysfsBit(hifiSysfsRead(dir + "/properties"), INPUT_PROP_DIRECT)) continue;
        if (!hifiSysfsBit(abs, ABS_X) && !hifiSysfsBit(abs, ABS_MT_POSITION_X)) continue;
        const QStringList evs = QDir(dir).entryList(QStringList("event*"), QDir::Dirs | QDir::NoDotAndDotDot);
        if (evs.isEmpty()) continue;
        const QString path = devDir + "/" + evs.first();
        seen << path;
        if (!m_devs.contains(path)) open(path, hifiSysfsRead(dir + "/name").trimmed(), usbOf(dir));
    }
    const QStringList had = m_devs.keys();
    for (const QString &p : had) if (!seen.contains(p)) close(p, true);
}

void TouchWatch::open(const QString &path, const QString &name, const QString &usb) {
    const int fd = ::open(path.toLocal8Bit().constData(), O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) { qInfo("touch: %s does not open (%s)", qPrintable(path), strerror(errno)); return; }
    Dev d;
    d.path = path; d.name = name; d.usb = usb; d.fd = fd;
    d.openedAt = nowMs();
    d.contacts = slotsDown(fd);
    d.down = keyDown(fd, BTN_TOUCH) || !d.contacts.isEmpty();
    if (d.down) d.downSince = d.openedAt;
    d.notifier = new QSocketNotifier(fd, QSocketNotifier::Read, this);
    connect(d.notifier, &QSocketNotifier::activated, this, [this, path]() { read(path); });
    m_devs.insert(path, d);
    qInfo("touch: %s on %s%s%s", qPrintable(name), qPrintable(path),
          usb.isEmpty() ? "" : qPrintable(QStringLiteral(" (usb %1)").arg(usb)),
          d.down ? ", a finger already down" : "");
    m_dirty = true;
}

void TouchWatch::close(const QString &path, bool gone) {
    if (!m_devs.contains(path)) return;
    Dev d = m_devs.take(path);
    if (gone) {
        // 🚨 The line that tells the three cases apart after the fact: the
        // owner unplugs first and asks later. A silent panel shows a last
        // event long before this; a phantom finger shows "a finger down".
        const qint64 n = nowMs();
        qInfo("touch: %s disconnected — last event %s, %lld events, %s, %lld dropped",
              qPrintable(d.name),
              d.lastAt ? qPrintable(QStringLiteral("%1 s before").arg((n - d.lastAt) / 1000)) : "never",
              (long long)d.events,
              d.down ? qPrintable(QStringLiteral("a finger down for %1 s").arg((n - d.downSince) / 1000)) : "no finger down",
              (long long)d.dropped);
    }
    if (d.notifier) { d.notifier->setEnabled(false); d.notifier->deleteLater(); }
    if (d.fd >= 0) ::close(d.fd);
    m_dirty = true;
}

void TouchWatch::read(const QString &path) {
    if (!m_devs.contains(path)) return;
    struct input_event ev;
    for (int round = 0; round < 256; round++) {
        const ssize_t n = ::read(m_devs[path].fd, &ev, sizeof(ev));
        if (n != sizeof(ev)) {
            if (n == 0 || (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) close(path, true);
            return;
        }
        Dev &d = m_devs[path];
        d.events++;
        d.lastAt = nowMs();
        m_dirty = true;
        if (ev.type == EV_SYN && ev.code == SYN_DROPPED) {
            // the kernel's buffer overflowed: what follows until the next
            // report may be half a picture. Ask it what is really down.
            if (d.dropped++ % 50 == 0)
                qInfo("touch: %s dropped events (%lld so far)", qPrintable(d.name), (long long)d.dropped);
            d.contacts = slotsDown(d.fd);
            const bool down = keyDown(d.fd, BTN_TOUCH) || !d.contacts.isEmpty();
            if (down && !d.down) d.downSince = d.lastAt;
            d.down = down;
        } else if (ev.type == EV_KEY && ev.code == BTN_TOUCH) {
            if (ev.value == 1) {
                if (!d.down) d.downSince = d.lastAt;
                d.down = true;
                if (!d.pendingSince) d.pendingSince = d.lastAt;
            } else if (ev.value == 0) {
                d.down = false; d.downSince = 0; d.warnedStuck = false;
            }
        } else if (ev.type == EV_ABS && ev.code == ABS_MT_SLOT) {
            d.slot = ev.value;
        } else if (ev.type == EV_ABS && ev.code == ABS_MT_TRACKING_ID) {
            if (ev.value < 0) d.contacts.remove(d.slot); else d.contacts.insert(d.slot);
        }
    }
}

void TouchWatch::check() {
    const qint64 n = nowMs();
    for (auto it = m_devs.begin(); it != m_devs.end(); ++it) {
        Dev &d = *it;
        // case 3: the kernel had a touch, the interface never heard of it
        if (d.pendingSince && n - d.pendingSince > kMissedMs) {
            qInfo("touch: %s reported a touch the interface did not receive (last touch in the interface %s)",
                  qPrintable(d.name),
                  m_qtLast ? qPrintable(QStringLiteral("%1 s before").arg((n - m_qtLast) / 1000)) : "never");
            d.pendingSince = 0;
        }
        // case 2: a finger that never lifts
        if (d.down && !d.warnedStuck && d.downSince && n - d.downSince > kStuckMs) {
            qInfo("touch: %s has had a finger down for %lld s (%lld contacts) — a stuck contact?",
                  qPrintable(d.name), (long long)((n - d.downSince) / 1000), (long long)d.contacts.size());
            d.warnedStuck = true;
            m_dirty = true;
        }
    }
    if (m_dirty) publish();
}

void TouchWatch::publish() {
    m_dirty = false;
    QJsonArray devs;
    for (const Dev &d : std::as_const(m_devs)) {
        QJsonArray held;
        for (int s : d.contacts) held.append(s);
        devs.append(QJsonObject{
            { "name", d.name }, { "node", d.path }, { "usb", d.usb },
            { "openedAt", d.openedAt / 1000 }, { "lastEventAt", d.lastAt / 1000 },
            { "events", d.events }, { "dropped", d.dropped },
            { "fingerDown", d.down }, { "downSince", d.downSince / 1000 }, { "contacts", held },
        });
    }
    const QJsonObject o{ { "writtenAt", nowMs() / 1000 }, { "interfaceLastTouchAt", m_qtLast / 1000 }, { "screens", devs } };
    const QString tmp = QString::fromLatin1(kState) + ".tmp";
    QFile f(tmp);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) return;   // not root (the rig): nothing to keep
    f.write(QJsonDocument(o).toJson(QJsonDocument::Compact));
    f.close();
    ::rename(tmp.toLocal8Bit().constData(), kState);
}
