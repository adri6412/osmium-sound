#include "sys.h"
#include <QCoreApplication>
#include <QCursor>
#include <QDir>
#include <QStandardPaths>
#include <QUrl>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QSet>
#include <QRegularExpression>
#include <QGuiApplication>
#include <QImage>
#include <QPainter>
#include <QCryptographicHash>
#include <cmath>
#include <algorithm>
#include <vector>
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
// ─── quale dispositivo e' "una tastiera su cui si puo' scrivere" ────────────
// 🚨 Stessa regola di main/inputDevices.js del kiosk Electron, e per lo stesso
// motivo: NON basta chiedere "esiste un dispositivo con i tasti", perche'
//   - quasi tutti i controller dei touchscreen USB (ILITEK, eGalax, Elo,
//     Weida, i pannelli HDMI stile WaveShare) sono dispositivi HID composti e
//     accanto al digitalizzatore espongono una "tastiera";
//   - il vecchio controller PS/2 di quasi tutte le schede x86 registra una
//     "AT Translated Set 2 keyboard" anche senza niente attaccato.
// Prendere per buone quelle due cose significa spegnere la tastiera a schermo
// su un apparecchio che si usa SOLO col dito: nessun modo di scrivere.
// Quindi: tastiera completa, su un bus a cui si attacca qualcosa (USB o
// Bluetooth), e il cui pezzo di ferro non sia anche un touchscreen.
// Le tastiere interne dei portatili (i8042/I2C/SPI) restano fuori di
// proposito: le copre il tasto lettera premuto davvero (Sys::noteRealKey).
static QString sysfsRead(const QString &path) {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) return QString();
    return QString::fromLatin1(f.readAll()).trimmed();
}

// I bitmap di sysfs sono parole esadecimali, la piu' significativa per prima.
static bool sysfsBit(const QString &text, int bit) {
    if (text.isEmpty()) return false;
    const QStringList words = text.split(QRegularExpression("\\s+"), Qt::SkipEmptyParts);
    const int wordBits = int(sizeof(unsigned long) * 8);
    const int idx = words.size() - 1 - bit / wordBits;      // l'ultima parola sono i bit bassi
    if (idx < 0 || idx >= words.size()) return false;
    bool ok = false;
    const qulonglong w = words.at(idx).toULongLong(&ok, 16);
    return ok && ((w >> (bit % wordBits)) & 1ULL);
}

// Il pezzo di ferro a cui appartiene un dispositivo: un USB composto (touch +
// "tastiera", oppure tastiera + touchpad, o un ricevitore senza fili) si
// dirama in piu' dispositivi che pendono tutti dalla stessa cartella del
// dispositivo USB (quella con idVendor; le interfacce hanno bInterfaceNumber).
static QString physicalUnit(const QString &inputDir) {
    QString dev = QFileInfo(inputDir + "/device").canonicalFilePath();
    if (dev.isEmpty()) return inputDir;
    static const QRegularExpression hci("^hci\\d+:\\d+$");
    for (QString d = dev; d.length() > 1 && d != "/sys"; d = QFileInfo(d).path()) {
        if (QFile::exists(d + "/idVendor")) return d;
        if (hci.match(QFileInfo(d).fileName()).hasMatch()) return d;
    }
    return dev;
}

void Sys::rescanInput() {
    // radice sovrascrivibile: serve alle prove con un finto albero sysfs
    QString root = qEnvironmentVariable("HIFI_SYSFS_INPUT");
    if (root.isEmpty()) root = "/sys/class/input";
    bool kb = false, touch = false;
    struct Dev { bool isKeyboard, isTouch; int bus; QString unit; };
    QList<Dev> devs;
    const QStringList entries = QDir(root).entryList(QStringList("input*"), QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QString &e : entries) {
        const QString dir = root + "/" + e;
        const QString key = sysfsRead(dir + "/capabilities/key");
        const QString abs = sysfsRead(dir + "/capabilities/abs");
        const QString props = sysfsRead(dir + "/properties");
        // tastiera completa: tutti i tasti da ESC a D (codici 1..31), come udev
        bool isKeyboard = true;
        for (int b = 1; b <= 31 && isKeyboard; b++) if (!sysfsBit(key, b)) isKeyboard = false;
        // touchscreen: puntamento diretto, oppure X/Y assolute con BTN_TOUCH e
        // senza cio' che ne farebbe un touchpad, una tavoletta o un mouse assoluto
        bool isTouch;
        if (sysfsBit(props, INPUT_PROP_DIRECT)) isTouch = true;
        else if (sysfsBit(props, INPUT_PROP_POINTER)) isTouch = false;
        else {
            const bool xy = (sysfsBit(abs, ABS_X) && sysfsBit(abs, ABS_Y))
                         || (sysfsBit(abs, ABS_MT_POSITION_X) && sysfsBit(abs, ABS_MT_POSITION_Y));
            isTouch = xy && sysfsBit(key, BTN_TOUCH)
                      && !sysfsBit(key, BTN_TOOL_FINGER) && !sysfsBit(key, BTN_TOOL_PEN)
                      && !sysfsBit(key, BTN_STYLUS) && !sysfsBit(key, BTN_LEFT);
        }
        const int bus = sysfsRead(dir + "/id/bustype").toInt(nullptr, 16);
        devs.append({ isKeyboard, isTouch, bus, physicalUnit(dir) });
        if (isTouch) touch = true;
    }
    QSet<QString> touchUnits;
    for (const Dev &d : devs) if (d.isTouch) touchUnits.insert(d.unit);
    for (const Dev &d : devs)
        if (d.isKeyboard && (d.bus == 0x03 || d.bus == 0x05) && !touchUnits.contains(d.unit)) kb = true;
    if (m_realKeyPressed) kb = true;                 // qualcuno ha premuto una lettera vera
    if (qEnvironmentVariableIsSet("HIFI_NO_KEYBOARD")) kb = false;
    if (kb != m_hasKeyboard || touch != m_hasTouch) { m_hasKeyboard = kb; m_hasTouch = touch; emit hasKeyboardChanged(); }
    // in chiaro nel giornale: e' la riga che spiega perche' la tastiera a
    // schermo compare o no su un apparecchio in campo
    if (!m_inputLogged || kb != m_loggedKb || touch != m_loggedTouch) {
        m_inputLogged = true; m_loggedKb = kb; m_loggedTouch = touch;
        qInfo("input: tastiera su cui scrivere=%s, touchscreen=%s (%lld dispositivi)",
              kb ? "si" : "no", touch ? "si" : "no", (long long)devs.size());
    }
}

// Un tasto lettera premuto davvero: copre le tastiere interne dei portatili,
// che la regola sopra lascia fuori. La tastiera a schermo non passa di qui
// (scrive nel campo senza generare eventi di tasto).
void Sys::noteRealKey() {
    if (m_realKeyPressed) return;
    m_realKeyPressed = true;
    if (!m_hasKeyboard) { m_hasKeyboard = true; emit hasKeyboardChanged(); }
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

// ─── box-shadow ──────────────────────────────────────────────────────────────
// Un box-shadow CSS e' la sagoma (allargata di `spread`) sfocata con una
// gaussiana di sigma blur/2. Qui la si calcola UNA volta per (raggio, blur,
// spread, colore) in un'immagine 9-patch: angoli interi, centro di 3 px che
// BorderImage stira a qualsiasi misura. Costa zero a ogni fotogramma — la
// sfocatura di MultiEffect avrebbe una passata per scheda per fotogramma.
// La gaussiana e' approssimata con tre box blur (Kutskir), che e' come fanno
// anche i browser.
static void boxBlur1D(std::vector<float> &src, std::vector<float> &dst, int w, int h, int r, bool horizontal) {
    const float iarr = 1.0f / (r + r + 1);
    if (horizontal) {
        for (int y = 0; y < h; y++) {
            const float *row = &src[y * w]; float *out = &dst[y * w];
            float acc = 0;
            for (int x = -r; x <= r; x++) acc += row[std::clamp(x, 0, w - 1)];
            for (int x = 0; x < w; x++) {
                out[x] = acc * iarr;
                acc += row[std::clamp(x + r + 1, 0, w - 1)] - row[std::clamp(x - r, 0, w - 1)];
            }
        }
    } else {
        for (int x = 0; x < w; x++) {
            float acc = 0;
            for (int y = -r; y <= r; y++) acc += src[std::clamp(y, 0, h - 1) * w + x];
            for (int y = 0; y < h; y++) {
                dst[y * w + x] = acc * iarr;
                acc += src[std::clamp(y + r + 1, 0, h - 1) * w + x] - src[std::clamp(y - r, 0, h - 1) * w + x];
            }
        }
    }
}

QString Sys::boxShadow(qreal radius, qreal blur, qreal spread, const QColor &color) {
    const QString key = QString("bs|%1|%2|%3|%4").arg(radius).arg(blur).arg(spread).arg(color.name(QColor::HexArgb));
    auto it = m_tinted.constFind(key);
    if (it != m_tinted.constEnd()) return *it;
    if (m_iconCacheDir.isEmpty()) {
        m_iconCacheDir = QStandardPaths::writableLocation(QStandardPaths::TempLocation)
                         + "/hifi-qt-icons-" + QString::number(getuid());
        QDir().mkpath(m_iconCacheDir);
    }
    const QString path = m_iconCacheDir + "/shadow-" + QString::fromLatin1(QCryptographicHash::hash(key.toUtf8(), QCryptographicHash::Md5).toHex().left(12)) + ".png";
    if (!QFile::exists(path)) {
        const double sigma = blur / 2.0;
        const int margin = int(std::ceil(blur * 1.5)) + 1;          // coda della gaussiana
        const double r = std::max(0.0, radius + spread);
        const int core = 2 * int(std::ceil(r)) + 3;                 // angoli + 3 px stirabili
        const int size = core + 2 * margin;
        QImage shape(size, size, QImage::Format_ARGB32_Premultiplied);
        shape.fill(Qt::transparent);
        {
            QPainter p(&shape);
            p.setRenderHint(QPainter::Antialiasing);
            p.setPen(Qt::NoPen); p.setBrush(Qt::white);
            p.drawRoundedRect(QRectF(margin, margin, core, core), r, r);
        }
        std::vector<float> a(size * size), b(size * size);
        for (int y = 0; y < size; y++) for (int x = 0; x < size; x++) a[y * size + x] = qAlpha(shape.pixel(x, y)) / 255.0f;
        if (sigma > 0.01) {
            // tre box blur che approssimano la gaussiana (Kutskir)
            const int n = 3;
            double wIdeal = std::sqrt(12.0 * sigma * sigma / n + 1.0);
            int wl = int(std::floor(wIdeal)); if (wl % 2 == 0) wl--;
            int wu = wl + 2;
            double mIdeal = (12.0 * sigma * sigma - n * wl * wl - 4.0 * n * wl - 3.0 * n) / (-4.0 * wl - 4.0);
            int m = int(std::round(mIdeal));
            for (int i = 0; i < n; i++) {
                int rr = ((i < m ? wl : wu) - 1) / 2;
                boxBlur1D(a, b, size, size, rr, true);
                boxBlur1D(b, a, size, size, rr, false);
            }
        }
        QImage out(size, size, QImage::Format_ARGB32_Premultiplied);
        const double ca = color.alphaF();
        for (int y = 0; y < size; y++) {
            QRgb *line = reinterpret_cast<QRgb *>(out.scanLine(y));
            for (int x = 0; x < size; x++) {
                double al = std::clamp(double(a[y * size + x]) * ca, 0.0, 1.0);
                line[x] = qPremultiply(qRgba(color.red(), color.green(), color.blue(), int(std::lround(al * 255))));
            }
        }
        out.save(path + ".tmp.png", "PNG");
        QFile::remove(path);
        QFile::rename(path + ".tmp.png", path);
    }
    const QString url = QUrl::fromLocalFile(path).toString();
    m_tinted.insert(key, url);
    return url;
}
