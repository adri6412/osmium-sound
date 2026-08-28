#include "sys.h"
#include <QCoreApplication>
#include <QCursor>
#include <QDir>
#include <QStandardPaths>
#include <QUrl>
#include <QElapsedTimer>
#include <QFile>
#include <QGuiApplication>
#include <QImage>
#include <QQuickWindow>
#include <QTextStream>
#include <QtDebug>
#include <fcntl.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <unistd.h>

static QElapsedTimer g_clock;

Sys::Sys(const QString &assets, QObject *parent) : QObject(parent), m_assets(assets) {
    g_clock.start();
    // 🚨 una variabile IMPOSTATA MA VUOTA non deve azzerare il percorso: senza
    // questo la UI leggeva "/ui-language" e ripiegava sull'inglese su un
    // apparecchio impostato in italiano
    m_configDir = qEnvironmentVariable("HIFI_CONFIG_DIR");
    if (m_configDir.isEmpty()) m_configDir = "/etc/hifi-player";
    m_dev = qEnvironmentVariableIsSet("HIFI_DEV");
    m_pointer = conf("pointer-enabled", "1").trimmed() != "0";
    rescanInput();
    if (QDir("/dev/input").exists()) {
        m_watch.addPath("/dev/input");
        connect(&m_watch, &QFileSystemWatcher::directoryChanged, this, [this]() { m_rescan.start(); });
    }
    m_rescan.setSingleShot(true);
    m_rescan.setInterval(500);
    connect(&m_rescan, &QTimer::timeout, this, &Sys::rescanInput);
}

static bool testBit(const unsigned long *arr, int bit) {
    return (arr[bit / (8 * sizeof(long))] >> (bit % (8 * sizeof(long)))) & 1;
}

// Stessa discriminante di input.c / main/inputDevices.js: una tastiera ha le
// lettere vere, non solo tasti speciali (i controller touch compositi e la
// PS/2 fantasma non contano).
void Sys::rescanInput() {
    bool kb = false, touch = false;
    QDir d("/dev/input");
    for (const QString &name : d.entryList({"event*"}, QDir::System | QDir::Files | QDir::NoDotAndDotDot)) {
        int fd = open(QString("/dev/input/" + name).toLocal8Bit().constData(), O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) continue;
        unsigned long evbits[(EV_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        unsigned long keybits[(KEY_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        unsigned long absbits[(ABS_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        unsigned long relbits[(REL_MAX + 8 * sizeof(long)) / (8 * sizeof(long))] = {0};
        ioctl(fd, EVIOCGBIT(0, sizeof evbits), evbits);
        ioctl(fd, EVIOCGBIT(EV_KEY, sizeof keybits), keybits);
        ioctl(fd, EVIOCGBIT(EV_ABS, sizeof absbits), absbits);
        ioctl(fd, EVIOCGBIT(EV_REL, sizeof relbits), relbits);
        close(fd);
        bool hasAbs = testBit(evbits, EV_ABS) && (testBit(absbits, ABS_MT_POSITION_X) || testBit(absbits, ABS_X));
        bool isTouch = hasAbs && testBit(keybits, BTN_TOUCH);
        bool isMouse = testBit(evbits, EV_REL) && testBit(relbits, REL_X) && testBit(relbits, REL_Y) && testBit(keybits, BTN_LEFT);
        bool isKey = testBit(evbits, EV_KEY) && testBit(keybits, KEY_A) && testBit(keybits, KEY_Z) && testBit(keybits, KEY_SPACE) && !isMouse;
        if (isKey) kb = true;
        if (isTouch) touch = true;
    }
    if (qEnvironmentVariableIsSet("HIFI_NO_KEYBOARD")) kb = false;
    if (kb != m_hasKeyboard || touch != m_hasTouch) { m_hasKeyboard = kb; m_hasTouch = touch; emit hasKeyboardChanged(); }
}

void Sys::setPointerEnabled(bool on) {
    if (m_pointer == on) return;
    m_pointer = on;
    emit pointerEnabledChanged();
    while (QGuiApplication::overrideCursor()) QGuiApplication::restoreOverrideCursor();
    if (!on) QGuiApplication::setOverrideCursor(QCursor(Qt::BlankCursor));
}

QString Sys::readLine(const QString &path, const QString &fallback) const {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) return fallback;
    QString l = QString::fromUtf8(f.readLine()).trimmed();
    return l.isEmpty() ? fallback : l;
}
QString Sys::readFile(const QString &path) const {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) return QString();
    return QString::fromUtf8(f.readAll());
}
bool Sys::writeLine(const QString &path, const QString &text) const {
    QFile f(path);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate | QIODevice::Text)) { qWarning("sys: non scrivibile %s", qPrintable(path)); return false; }
    f.write((text + "\n").toUtf8());
    return true;
}
bool Sys::exists(const QString &path) const { return QFile::exists(path); }
QString Sys::conf(const QString &name, const QString &fallback) const { return readLine(m_configDir + "/" + name, fallback); }
bool Sys::setConf(const QString &name, const QString &value) const { return writeLine(m_configDir + "/" + name, value); }

bool Sys::shot(const QString &path) const {
    if (!m_win) return false;
    QImage img = m_win->grabWindow();
    if (img.isNull()) return false;
    bool ok = img.save(path.isEmpty() ? "/tmp/hifi-qt.png" : path);
    if (ok) qInfo("sys: fotografia in %s", qPrintable(path.isEmpty() ? "/tmp/hifi-qt.png" : path));
    return ok;
}
void Sys::quit() const { QCoreApplication::quit(); }
qint64 Sys::now() const { return g_clock.elapsed(); }
void Sys::log(const QString &s) const { qInfo("qml: %s", qPrintable(s)); }

// Ogni tocco, movimento o tasto conta come attivita' (salvaschermo,
// auto-apertura del player). Chiamata dal filtro degli eventi in main.cpp.
void Sys::noteInput() {
    qint64 n = g_clock.elapsed();
    if (n - m_lastInput < 200) { m_lastInput = n; return; }   // non inondare i binding
    m_lastInput = n;
    emit lastInputChanged();
}

// ─── icone tinte ────────────────────────────────────────────────────────────
// Le icone sono SVG lucide con stroke/fill "#ffffff" (gen-icons.mjs). Qui si
// sostituisce il bianco col colore voluto e, se il colore ha trasparenza, la
// si mette come stroke-opacity/fill-opacity sulla radice: e' PER FORMA, come fa
// Chromium con currentColor + colore CSS con alpha (i tratti che si
// sovrappongono si sommano, identico a Electron). Il file finisce in una
// cartella temporanea e si genera una volta sola per coppia (icona, colore):
// le coppie sono poche decine, nessun colore e' animato.
QString Sys::tintedIcon(const QString &name, const QColor &color) {
    if (name.isEmpty() || m_iconDir.isEmpty()) return QString();
    const QString key = name + '|' + color.name(QColor::HexArgb);
    auto it = m_tinted.constFind(key);
    if (it != m_tinted.constEnd()) return *it;
    if (m_iconCacheDir.isEmpty()) {
        m_iconCacheDir = QStandardPaths::writableLocation(QStandardPaths::TempLocation)
                         + "/hifi-qt-icons-" + QString::number(getuid());
        QDir().mkpath(m_iconCacheDir);
    }
    const QString path = m_iconCacheDir + '/' + name + '-' + color.name(QColor::HexArgb).mid(1) + ".svg";
    if (!QFile::exists(path)) {
        QFile in(m_iconDir + '/' + name + ".svg");
        if (!in.open(QIODevice::ReadOnly)) { qWarning("icona mancante: %s", qPrintable(in.fileName())); m_tinted.insert(key, QString()); return QString(); }
        QByteArray svg = in.readAll();
        svg.replace("#ffffff", color.name(QColor::HexRgb).toLatin1());
        if (color.alphaF() < 0.999) {
            // sulla radice <svg ...>: gli attributi si ereditano dalle forme
            int gt = svg.indexOf('>');
            int svgTag = svg.indexOf("<svg");
            if (svgTag >= 0) gt = svg.indexOf('>', svgTag);
            if (gt > 0) {
                const QByteArray a = QByteArray::number(color.alphaF(), 'f', 3);
                svg.insert(gt, " stroke-opacity=\"" + a + "\" fill-opacity=\"" + a + "\"");
            }
        }
        QFile out(path + ".tmp");
        if (!out.open(QIODevice::WriteOnly | QIODevice::Truncate)) { m_tinted.insert(key, QString()); return QString(); }
        out.write(svg); out.close();
        QFile::remove(path);
        QFile::rename(path + ".tmp", path);
    }
    const QString url = QUrl::fromLocalFile(path).toString();
    m_tinted.insert(key, url);
    return url;
}
