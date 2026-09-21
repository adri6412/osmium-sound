#include "btghid.h"
#include <QDBusArgument>
#include <QDBusConnection>
#include <QDBusInterface>
#include <QDBusMessage>
#include <QDBusMetaType>
#include <QDBusReply>
#include <QDBusUnixFileDescriptor>
#include <QDir>
#include <QFile>
#include <QRegularExpression>
#include <QSocketNotifier>
#include <QtDebug>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uhid.h>
#include <string.h>
#include <unistd.h>

using InterfaceMap = QMap<QString, QVariantMap>;
using ManagedObjects = QMap<QDBusObjectPath, InterfaceMap>;
Q_DECLARE_METATYPE(InterfaceMap)
Q_DECLARE_METATYPE(ManagedObjects)

namespace {

const char *BLUEZ = "org.bluez";
const QString HID_SERVICE = QStringLiteral("00001812");          // HID over GATT
const QString UUID_REPORT_MAP = QStringLiteral("00002a4b-0000-1000-8000-00805f9b34fb");
const QString UUID_REPORT = QStringLiteral("00002a4d-0000-1000-8000-00805f9b34fb");
const QString UUID_REPORT_REF = QStringLiteral("00002908-0000-1000-8000-00805f9b34fb");
// come si firma il dispositivo che creiamo noi, per riconoscerlo in sysfs
#define UHID_PHYS "osmium-btghid"
// 🚨 Quanto si aspetta prima di rimpiazzare il nucleo: BlueZ il suo giro lo
// finisce in un paio di secondi, e intervenire prima vuol dire creare un
// doppione del dispositivo che stava per funzionare.
const qint64 GRACE_MS = 6000;
// 🚨 Quanti rapporti si leggono per ogni risveglio del descrittore. Un
// telecomando che parla in continuazione (i sensori di movimento di certi
// telecomandi Android) teneva il ciclo dentro `read` e l'interfaccia si
// fermava: lo schermo restava fermo col processo vivo.
const int MAX_REPORTS_PER_WAKE = 32;

// Le collection della mappa si chiudono tutte? E' esattamente il controllo che
// fa il nucleo prima di rifiutare un descrittore.
bool balanced(const QByteArray &d) {
    int i = 0, depth = 0;
    while (i < d.size()) {
        const quint8 b = quint8(d.at(i));
        if (b == 0xfe) {                                  // long item
            const int size = i + 1 < d.size() ? quint8(d.at(i + 1)) : 0;
            i += 3 + size;
            continue;
        }
        int size = b & 0x03;
        if (size == 3) size = 4;
        const int tag = b & 0xfc;
        if (tag == 0xa0) depth++;                         // Collection
        else if (tag == 0xc0) depth--;                    // End Collection
        i += 1 + size;
    }
    return depth == 0 && i == d.size();
}

bool uhidSend(int fd, uhid_event &ev) {
    if (fd < 0) return false;
    const ssize_t n = ::write(fd, &ev, sizeof(ev));
    if (n != sizeof(ev)) { qWarning("btghid: scrittura su /dev/uhid fallita (%s)", strerror(errno)); return false; }
    return true;
}

void setField(__u8 *dst, size_t len, const QString &s) {
    const QByteArray b = s.toUtf8().left(int(len) - 1);
    memset(dst, 0, len);
    memcpy(dst, b.constData(), size_t(b.size()));
}

}  // namespace

BtGattHid::BtGattHid(QObject *parent) : QObject(parent) {
    qDBusRegisterMetaType<InterfaceMap>();
    qDBusRegisterMetaType<ManagedObjects>();
    connect(&m_poll, &QTimer::timeout, this, &BtGattHid::poll);
    m_poll.setInterval(4000);
    // 🚨 Il giro costa una chiamata a BlueZ ogni quattro secondi e basta: si
    // guarda solo l'elenco degli oggetti, nessuna radio, nessuna paginazione.
    // Senza Bluetooth in funzione la chiamata fallisce e non si fa nulla.
    m_poll.start();
    poll();
}

BtGattHid::~BtGattHid() {
    const QStringList paths = m_bridges.keys();
    for (const QString &p : paths) stop(p);
}

QVariantList BtGattHid::bridged() const {
    QVariantList out;
    for (auto it = m_bridges.constBegin(); it != m_bridges.constEnd(); ++it)
        if (it->created)
            out.append(QVariantMap{ { "mac", it->mac }, { "name", it->name },
                                    { "reports", it->reports.size() } });
    return out;
}

QStringList BtGattHid::bridgedNames() const {
    QStringList out;
    for (auto it = m_bridges.constBegin(); it != m_bridges.constEnd(); ++it)
        if (it->created) out << it->name;
    return out;
}

// ─── chi ha bisogno del ponte ──────────────────────────────────────────────
// Un dispositivo di input Bluetooth porta scritto l'indirizzo del telecomando
// in `uniq`: se c'e', il nucleo ce l'ha fatta da solo e noi non c'entriamo.
bool BtGattHid::kernelHandles(const QString &mac) const {
    const QString root = qEnvironmentVariable("HIFI_SYSFS_INPUT", QStringLiteral("/sys/class/input"));
    const QStringList entries = QDir(root).entryList(QStringList("input*"), QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QString &e : entries) {
        QFile u(root + "/" + e + "/uniq");
        if (!u.open(QIODevice::ReadOnly | QIODevice::Text)) continue;
        if (QString::fromLatin1(u.readAll()).trimmed().compare(mac, Qt::CaseInsensitive) != 0) continue;
        // 🚨 ...ma non deve essere il nostro: il dispositivo che creiamo noi
        // porta lo stesso indirizzo, e senza questo controllo ci vedremmo da
        // soli e non chiuderemmo mai un ponte diventato inutile.
        QFile p(root + "/" + e + "/phys");
        QString phys;
        if (p.open(QIODevice::ReadOnly | QIODevice::Text)) phys = QString::fromLatin1(p.readAll()).trimmed();
        if (phys != QLatin1String(UHID_PHYS)) return true;
    }
    return false;
}

void BtGattHid::poll() {
    QDBusInterface om(BLUEZ, "/", "org.freedesktop.DBus.ObjectManager", QDBusConnection::systemBus());
    QDBusReply<ManagedObjects> reply = om.call("GetManagedObjects");
    if (!reply.isValid()) return;                 // Bluetooth spento: niente da fare
    const ManagedObjects objs = reply.value();

    QStringList alive;
    for (auto it = objs.constBegin(); it != objs.constEnd(); ++it) {
        const QVariantMap dev = it.value().value("org.bluez.Device1");
        if (dev.isEmpty()) continue;
        if (!dev.value("Connected").toBool() || !dev.value("ServicesResolved").toBool()) continue;
        bool hid = false;
        for (const QString &u : dev.value("UUIDs").toStringList())
            if (u.startsWith(HID_SERVICE)) { hid = true; break; }
        if (!hid) continue;

        const QString path = it.key().path();
        const QString mac = dev.value("Address").toString().toUpper();
        alive << path;
        if (!m_seen.contains(path)) m_seen.insert(path, QDateTime::currentMSecsSinceEpoch());
        if (m_bridges.contains(path)) {
            // il nucleo ce l'ha fatta dopo di noi: il ponte non serve piu'
            if (kernelHandles(mac)) {
                qInfo("btghid: %s: ci ha pensato il nucleo, ponte chiuso", qPrintable(mac));
                stop(path);
            }
            continue;
        }
        if (m_failed.contains(path)) continue;
        if (kernelHandles(mac)) continue;         // funziona da se': non si tocca
        // gli si lascia il tempo di farcela da solo
        if (QDateTime::currentMSecsSinceEpoch() - m_seen.value(path) < GRACE_MS) continue;

        const QString name = dev.value("Alias").toString().isEmpty()
                           ? dev.value("Name").toString() : dev.value("Alias").toString();
        // le caratteristiche di questo dispositivo, dalla stessa istantanea
        QVariantMap chars;
        for (auto c = objs.constBegin(); c != objs.constEnd(); ++c) {
            if (!c.key().path().startsWith(path)) continue;
            const QVariantMap ch = c.value().value("org.bluez.GattCharacteristic1");
            const QVariantMap de = c.value().value("org.bluez.GattDescriptor1");
            if (!ch.isEmpty()) chars.insert(c.key().path(), ch);
            else if (!de.isEmpty()) chars.insert(c.key().path(), de);
        }
        start(path, mac, name, chars);
    }

    // chi si e' scollegato
    const QStringList had = m_bridges.keys();
    for (const QString &p : had) if (!alive.contains(p)) stop(p);
    for (const QString &p : m_failed) if (!alive.contains(p)) m_failed.removeAll(p);
    const QStringList seen = m_seen.keys();
    for (const QString &p : seen) if (!alive.contains(p)) m_seen.remove(p);
}

// ─── leggere per intero cio' che BlueZ legge a meta' ───────────────────────
QByteArray BtGattHid::readCharacteristic(const QString &path) const {
    QByteArray out;
    int first = -1;
    for (int guard = 0; guard < 64; guard++) {
        QDBusInterface ch(BLUEZ, path, "org.bluez.GattCharacteristic1", QDBusConnection::systemBus());
        QVariantMap opts;
        if (!out.isEmpty()) opts.insert("offset", QVariant::fromValue<quint16>(quint16(out.size())));
        QDBusReply<QByteArray> r = ch.call("ReadValue", opts);
        if (!r.isValid()) break;
        const QByteArray part = r.value();
        if (part.isEmpty()) break;
        if (first < 0) first = part.size();
        out += part;
        if (part.size() < first) break;           // ultimo pezzo
        if (out.size() >= int(HID_MAX_DESCRIPTOR_SIZE)) break;
    }
    return out;
}

void BtGattHid::start(const QString &devPath, const QString &mac, const QString &name,
                      const QVariantMap &objs) {
    // 1. la mappa dei rapporti, a blocchi
    QString mapPath;
    QList<QPair<QString, QVariantMap>> reportChars;
    for (auto it = objs.constBegin(); it != objs.constEnd(); ++it) {
        const QVariantMap m = it.value().toMap();
        const QString uuid = m.value("UUID").toString().toLower();
        if (uuid == UUID_REPORT_MAP) mapPath = it.key();
        else if (uuid == UUID_REPORT) reportChars.append({ it.key(), m });
    }
    if (mapPath.isEmpty() || reportChars.isEmpty()) { m_failed << devPath; return; }

    const QByteArray rd = readCharacteristic(mapPath);
    if (rd.size() > int(HID_MAX_DESCRIPTOR_SIZE)) {
        qWarning("btghid: %s: mappa dei tasti troppo lunga (%lld byte)", qPrintable(name), (long long)rd.size());
        m_failed << devPath;
        return;
    }
    if (rd.isEmpty() || !balanced(rd)) {
        qWarning("btghid: %s: mappa dei tasti illeggibile (%lld byte)", qPrintable(name), (long long)rd.size());
        m_failed << devPath;
        return;
    }
    qInfo("btghid: %s (%s): mappa dei tasti di %lld byte, letta a blocchi",
          qPrintable(name), qPrintable(mac), (long long)rd.size());

    Bridge b;
    b.devPath = devPath;
    b.mac = mac;
    b.name = name;

    // 2. quali rapporti sono di ingresso, e con che numero
    for (const auto &rc : reportChars) {
        if (!rc.second.value("Flags").toStringList().contains("notify")) continue;
        int id = 0, type = 0;
        for (auto d = objs.constBegin(); d != objs.constEnd(); ++d) {
            if (!d.key().startsWith(rc.first + "/")) continue;
            if (d.value().toMap().value("UUID").toString().toLower() != UUID_REPORT_REF) continue;
            QDBusInterface desc(BLUEZ, d.key(), "org.bluez.GattDescriptor1", QDBusConnection::systemBus());
            QDBusReply<QByteArray> r = desc.call("ReadValue", QVariantMap());
            if (r.isValid() && r.value().size() >= 2) { id = quint8(r.value().at(0)); type = quint8(r.value().at(1)); }
        }
        if (type != 1) continue;                  // 1 = ingresso (i tasti)
        Report rep;
        rep.path = rc.first;
        rep.id = id;
        b.reports.append(rep);
    }
    if (b.reports.isEmpty()) { m_failed << devPath; return; }

    // 3. il dispositivo HID nostro
    b.uhid = ::open("/dev/uhid", O_RDWR | O_CLOEXEC | O_NONBLOCK);
    if (b.uhid < 0) {
        qWarning("btghid: /dev/uhid non si apre (%s)", strerror(errno));
        m_failed << devPath;
        return;
    }
    quint32 vid = 0, pid = 0;
    {   // vendor e prodotto dal Modalias del dispositivo ("usb:v1D5ApC081d0000")
        QDBusInterface dev(BLUEZ, devPath, "org.freedesktop.DBus.Properties", QDBusConnection::systemBus());
        QDBusReply<QDBusVariant> r = dev.call("Get", "org.bluez.Device1", "Modalias");
        if (r.isValid()) {
            static const QRegularExpression re("v([0-9A-Fa-f]{4})p([0-9A-Fa-f]{4})");
            const auto m = re.match(r.value().variant().toString());
            if (m.hasMatch()) { vid = m.captured(1).toUInt(nullptr, 16); pid = m.captured(2).toUInt(nullptr, 16); }
        }
    }
    uhid_event ev{};
    ev.type = UHID_CREATE2;
    setField(ev.u.create2.name, sizeof(ev.u.create2.name), name);
    setField(ev.u.create2.phys, sizeof(ev.u.create2.phys), QStringLiteral("osmium-btghid"));
    setField(ev.u.create2.uniq, sizeof(ev.u.create2.uniq), mac);
    ev.u.create2.rd_size = quint16(rd.size());
    ev.u.create2.bus = BUS_BLUETOOTH;
    ev.u.create2.vendor = vid;
    ev.u.create2.product = pid;
    ev.u.create2.version = 0;
    ev.u.create2.country = 0;
    memcpy(ev.u.create2.rd_data, rd.constData(), size_t(rd.size()));
    if (!uhidSend(b.uhid, ev)) { ::close(b.uhid); m_failed << devPath; return; }
    b.created = true;
    b.uhidNotifier = new QSocketNotifier(b.uhid, QSocketNotifier::Read, this);
    connect(b.uhidNotifier, &QSocketNotifier::activated, this, [this, devPath]() { onUhidEvent(devPath); });

    // 4. le notifiche dei rapporti: un descrittore di file per ciascuno
    m_bridges.insert(devPath, b);
    Bridge &bb = m_bridges[devPath];
    for (int i = 0; i < bb.reports.size(); i++) {
        QDBusInterface ch(BLUEZ, bb.reports[i].path, "org.bluez.GattCharacteristic1", QDBusConnection::systemBus());
        QDBusMessage msg = ch.call("AcquireNotify", QVariantMap());
        if (msg.type() != QDBusMessage::ReplyMessage || msg.arguments().isEmpty()) {
            qWarning("btghid: %s report %d: AcquireNotify rifiutata (%s)",
                     qPrintable(name), bb.reports[i].id, qPrintable(msg.errorMessage()));
            continue;
        }
        const QDBusUnixFileDescriptor fd = msg.arguments().at(0).value<QDBusUnixFileDescriptor>();
        bb.reports[i].fd = ::dup(fd.fileDescriptor());
        if (bb.reports[i].fd < 0) continue;
        ::fcntl(bb.reports[i].fd, F_SETFL, O_NONBLOCK);
        bb.reports[i].notifier = new QSocketNotifier(bb.reports[i].fd, QSocketNotifier::Read, this);
        connect(bb.reports[i].notifier, &QSocketNotifier::activated, this, [this, devPath, i]() { onReport(devPath, i); });
    }
    int live = 0;
    for (const Report &r : bb.reports) if (r.fd >= 0) live++;
    qInfo("btghid: %s: ponte attivo, %d rapporti in ascolto su %lld",
          qPrintable(name), live, (long long)bb.reports.size());
    emit bridgedChanged();
}

void BtGattHid::stop(const QString &devPath) {
    if (!m_bridges.contains(devPath)) return;
    Bridge b = m_bridges.take(devPath);
    for (Report &r : b.reports) {
        if (r.notifier) { r.notifier->setEnabled(false); r.notifier->deleteLater(); }
        if (r.fd >= 0) ::close(r.fd);
    }
    if (b.uhidNotifier) { b.uhidNotifier->setEnabled(false); b.uhidNotifier->deleteLater(); }
    if (b.uhid >= 0) {
        uhid_event ev{};
        ev.type = UHID_DESTROY;
        uhidSend(b.uhid, ev);
        ::close(b.uhid);
    }
    qInfo("btghid: %s: ponte chiuso", qPrintable(b.name));
    emit bridgedChanged();
}

// Un rapporto dal telecomando: dentro il dispositivo HID nostro, col suo
// numero davanti (le notifiche GATT non lo portano, lo dice il Report
// Reference della caratteristica).
void BtGattHid::onReport(const QString &devPath, int index) {
    if (!m_bridges.contains(devPath)) return;
    Bridge &b = m_bridges[devPath];
    if (index < 0 || index >= b.reports.size()) return;
    Report &r = b.reports[index];
    for (int n_read = 0; n_read < MAX_REPORTS_PER_WAKE; n_read++) {
        char buf[UHID_DATA_MAX];
        const ssize_t n = ::read(r.fd, buf, sizeof(buf));
        if (n <= 0) {
            if (n == 0 || (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)) stop(devPath);
            return;
        }
        uhid_event ev{};
        ev.type = UHID_INPUT2;
        int len = 0;
        if (r.id > 0) ev.u.input2.data[len++] = quint8(r.id);
        const int take = qMin(int(sizeof(ev.u.input2.data)) - len, int(n));
        memcpy(ev.u.input2.data + len, buf, size_t(take));
        ev.u.input2.size = quint16(len + take);
        uhidSend(b.uhid, ev);
    }
}

// Il nucleo ci parla: a una richiesta di rapporto si risponde comunque, o
// resta ad aspettare cinque secondi per ognuna.
void BtGattHid::onUhidEvent(const QString &devPath) {
    if (!m_bridges.contains(devPath)) return;
    Bridge &b = m_bridges[devPath];
    for (;;) {
        uhid_event ev{};
        const ssize_t n = ::read(b.uhid, &ev, sizeof(ev));
        if (n <= 0) return;
        if (ev.type == UHID_GET_REPORT) {
            uhid_event out{};
            out.type = UHID_GET_REPORT_REPLY;
            out.u.get_report_reply.id = ev.u.get_report.id;
            out.u.get_report_reply.err = EIO;
            uhidSend(b.uhid, out);
        } else if (ev.type == UHID_SET_REPORT) {
            uhid_event out{};
            out.type = UHID_SET_REPORT_REPLY;
            out.u.set_report_reply.id = ev.u.set_report.id;
            out.u.set_report_reply.err = EIO;
            uhidSend(b.uhid, out);
        }
    }
}
