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
#include <QMouseEvent>
#include <QWindow>
#include <fcntl.h>
#include <linux/input.h>
#include <sys/ioctl.h>
#include <unistd.h>
#if __has_include(<qpa/qwindowsysteminterface.h>)
#include <qpa/qwindowsysteminterface.h>
#define HIFI_HAVE_QPA_MOUSE 1
#endif

static QElapsedTimer g_clock;

// 🚨 Through the QPA layer, like a real mouse: a QMouseEvent built by hand and
// sent straight to the window does not keep the press position and the grab
// from one event to the next, so drags never turn into flicks. The header
// ships with qt6-base-private-dev; without it this falls back to the plain
// event, which is enough for a press and a release on the same point (what
// the remote control's OK button does).
void hifiSendMouse(QWindow *w, QEvent::Type type, const QPointF &p, Qt::MouseButton button) {
    if (!w) return;
    const Qt::MouseButtons held = type == QEvent::MouseButtonRelease ? Qt::NoButton : Qt::LeftButton;
#ifdef HIFI_HAVE_QPA_MOUSE
    static ulong ts = 5000;
    ts += 16;
    // a move carries NO button (like a real mouse): with one, Qt takes every
    // move for a new press and the drag restarts at each event
    const Qt::MouseButton btn = type == QEvent::MouseMove ? Qt::NoButton : button;
    QWindowSystemInterface::handleMouseEvent<QWindowSystemInterface::SynchronousDelivery>(
        w, ts, p, w->mapToGlobal(p.toPoint()), held, btn, type);
#else
    QMouseEvent ev(type, p, p, w->mapToGlobal(p.toPoint()), button, held, Qt::NoModifier);
    QCoreApplication::sendEvent(w, &ev);
#endif
}

Sys::Sys(const QString &assets, QObject *parent) : QObject(parent), m_assets(assets) {
    g_clock.start();
    // 🚨 una variabile IMPOSTATA MA VUOTA non deve azzerare il percorso: senza
    // questo la UI leggeva "/ui-language" e ripiegava sull'inglese su un
    // apparecchio impostato in italiano
    m_configDir = qEnvironmentVariable("HIFI_CONFIG_DIR");
    if (m_configDir.isEmpty()) m_configDir = "/etc/hifi-player";
    m_dev = qEnvironmentVariableIsSet("HIFI_DEV");
    m_pointer = conf("pointer-enabled", "1").trimmed() != "0";
}

// 🚨 Non si decide piu' se "c'e' una tastiera vera": la tastiera a schermo si
// apre e basta (TextField_.openVk). La regola di prima — tastiera completa su
// USB/Bluetooth, escludendo i controller touch compositi e la PS/2 fantasma —
// serviva a non nasconderla a chi usa solo il dito, ma non poteva reggere i
// telecomandi, che si presentano come tastiere e non fanno scrivere niente.
QString hifiSysfsRead(const QString &path) {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) return QString();
    return QString::fromLatin1(f.readAll()).trimmed();
}
static inline QString sysfsRead(const QString &path) { return hifiSysfsRead(path); }

// I bitmap di sysfs sono parole esadecimali, la piu' significativa per prima.
bool hifiSysfsBit(const QString &text, int bit) {
    if (text.isEmpty()) return false;
    const QStringList words = text.split(QRegularExpression("\\s+"), Qt::SkipEmptyParts);
    const int wordBits = int(sizeof(unsigned long) * 8);
    const int idx = words.size() - 1 - bit / wordBits;      // l'ultima parola sono i bit bassi
    if (idx < 0 || idx >= words.size()) return false;
    bool ok = false;
    const qulonglong w = words.at(idx).toULongLong(&ok, 16);
    return ok && ((w >> (bit % wordBits)) & 1ULL);
}
static inline bool sysfsBit(const QString &text, int bit) { return hifiSysfsBit(text, bit); }

// Il pezzo di ferro a cui appartiene un dispositivo: un USB composto (touch +
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
// Il telecomando "tocca" il riquadro che ha il riflettore: una pressione e un
// rilascio nel punto dato (coordinate della finestra), cosi' passano dallo
// stesso percorso di un dito vero — animazione della pressione compresa.
void Sys::tapAt(qreal x, qreal y, int holdMs) {
    if (!m_win) return;
    // le pressioni che seguono sono nostre: non devono spegnere il riflettore
    m_injectUntil = g_clock.elapsed() + holdMs + 400;
    const QPointF p(x, y);
    hifiSendMouse(m_win, QEvent::MouseButtonPress, p);
    if (holdMs > 0) {
        // the long press that opens a row's menu: the finger stays down past
        // MouseArea's pressAndHoldInterval (500 ms) without moving
        QTimer::singleShot(holdMs, this, [this, p]() { hifiSendMouse(m_win, QEvent::MouseButtonRelease, p); });
    } else {
        hifiSendMouse(m_win, QEvent::MouseButtonRelease, p);
    }
    noteInput();
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

void Sys::notePointer() {
    if (g_clock.elapsed() < m_injectUntil) return;
    emit pointerTouched();
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
