// sys — piccole cose di sistema che a QML mancano: file di configurazione
// in /etc/hifi-player, tastiera fisica collegata (per decidere se mostrare
// quella a schermo), puntatore, fotografie dello schermo per il collaudo.
#pragma once
#include <QObject>
#include <QColor>
#include <QEvent>
#include <QHash>
#include <QFileSystemWatcher>
#include <QPointF>
#include <QTimer>

class QQuickWindow;
class QWindow;

// ─── helpers shared with remote.cpp ────────────────────────────────────────
// A file's first line, and one bit of a /sys/class/input bitmap (hex words,
// most significant first): the remote control classifies input devices with
// the same two helpers this file uses to decide whether a keyboard is there.
QString hifiSysfsRead(const QString &path);
bool hifiSysfsBit(const QString &bitmap, int bit);
// A mouse event through the QPA layer, like a real mouse. The test channel
// and the remote control's OK button both press on the scene this way; see
// the comment on the implementation for why a hand-built QMouseEvent is not
// the same thing.
void hifiSendMouse(QWindow *w, QEvent::Type type, const QPointF &p, Qt::MouseButton button = Qt::LeftButton);

class Sys : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool hasKeyboard READ hasKeyboard NOTIFY hasKeyboardChanged)
    Q_PROPERTY(bool hasTouch READ hasTouch NOTIFY hasKeyboardChanged)
    Q_PROPERTY(bool pointerEnabled READ pointerEnabled WRITE setPointerEnabled NOTIFY pointerEnabledChanged)
    Q_PROPERTY(QString assets READ assets CONSTANT)
    // skins downloaded from the VU meter store (api_server VU_STORE_DIR)
    Q_PROPERTY(QString vuStore READ vuStore CONSTANT)
    // Now Playing animations downloaded from their store (api_server ANIM_STORE_DIR)
    Q_PROPERTY(QString animStore READ animStore CONSTANT)
    Q_PROPERTY(QString configDir READ configDir CONSTANT)
    Q_PROPERTY(bool devMode READ devMode CONSTANT)
    Q_PROPERTY(QString forcedWizard READ forcedWizard CONSTANT)
    Q_PROPERTY(bool wizardDry READ wizardDry CONSTANT)
    Q_PROPERTY(bool startExpanded READ startExpanded CONSTANT)
    Q_PROPERTY(qint64 lastInput READ lastInput NOTIFY lastInputChanged)
public:
    explicit Sys(const QString &assets, QObject *parent = nullptr);
    void setWindow(QQuickWindow *w) { m_win = w; }
    bool hasKeyboard() const { return m_hasKeyboard; }
    bool hasTouch() const { return m_hasTouch; }
    bool pointerEnabled() const { return m_pointer; }
    void setPointerEnabled(bool on);
    QString assets() const { return m_assets; }
    QString vuStore() const { return qEnvironmentVariable("HIFI_VU_STORE_DIR", QStringLiteral("/var/lib/hifi-player/vu-skins")); }
    QString animStore() const { return qEnvironmentVariable("HIFI_ANIM_STORE_DIR", QStringLiteral("/var/lib/hifi-player/anim-scenes")); }
    QString configDir() const { return m_configDir; }
    bool devMode() const { return m_dev; }
    QString forcedWizard() const { return m_forcedWizard; }
    void setForcedWizard(const QString &w, bool dry = false) { m_forcedWizard = w; m_wizardDry = dry; }
    bool wizardDry() const { return m_wizardDry; }
    bool startExpanded() const { return m_startExpanded; }
    void setStartExpanded(bool b) { m_startExpanded = b; }

    Q_INVOKABLE QString readLine(const QString &path, const QString &fallback = QString()) const;
    Q_INVOKABLE QString readFile(const QString &path) const;
    Q_INVOKABLE bool writeLine(const QString &path, const QString &text) const;
    Q_INVOKABLE bool exists(const QString &path) const;
    // /etc/hifi-player/<name>
    Q_INVOKABLE QString conf(const QString &name, const QString &fallback = QString()) const;
    Q_INVOKABLE bool setConf(const QString &name, const QString &value) const;
    Q_INVOKABLE bool shot(const QString &path) const;
    // A press (and release) on the scene at a point in window coordinates:
    // how the remote control's OK button "touches" the control it has the
    // highlight on. `holdMs` > 0 keeps the finger down that long, which is
    // what opens a long-press menu.
    Q_INVOKABLE void tapAt(qreal x, qreal y, int holdMs = 0);
    Q_INVOKABLE void rescanInput();
    void noteRealKey();               // un tasto lettera premuto davvero
    Q_INVOKABLE void quit() const;
    Q_INVOKABLE qint64 now() const;                  // ms monotonici
    Q_INVOKABLE QString upper(const QString &s) const { return s.toUpper(); }
    Q_INVOKABLE void log(const QString &s) const;
    // Icona lucide gia' tinta (file SVG in cache): si disegna come vettore,
    // senza passare da una texture — vedi Icon.qml per il perche'.
    Q_INVOKABLE QString tintedIcon(const QString &name, const QColor &color);
    void setIconDir(const QString &dir) { m_iconDir = dir; }
    // box-shadow CSS (blur, spread, colore) per un rettangolo con angoli
    // `radius`: un PNG 9-patch pre-sfocato in cache, da usare con BoxShadow.qml
    Q_INVOKABLE QString boxShadow(qreal radius, qreal blur, qreal spread, const QColor &color);
    qint64 lastInput() const { return m_lastInput; }
    void noteInput();
    // Un dito (o il mouse) davvero appoggiato sullo schermo: il riflettore del
    // telecomando si spegne, perche' da qui in poi comanda il dito. Le
    // pressioni che il telecomando stesso inietta (Sys::tapAt) non contano.
    void notePointer();

signals:
    void hasKeyboardChanged();
    void pointerTouched();
    void pointerEnabledChanged();
    void lastInputChanged();

private:
    QString m_assets, m_configDir;
    QString m_iconDir, m_iconCacheDir;
    QHash<QString, QString> m_tinted;   // chiave nome|colore -> URL del file
    bool m_realKeyPressed = false, m_inputLogged = false, m_loggedKb = false, m_loggedTouch = false;
    bool m_hasKeyboard = false, m_hasTouch = false, m_pointer = true, m_dev = false, m_startExpanded = false;
    QString m_forcedWizard;
    bool m_wizardDry = false;
    QFileSystemWatcher m_watch;
    QTimer m_rescan;
    QQuickWindow *m_win = nullptr;
    qint64 m_lastInput = 0;
    qint64 m_injectUntil = -1;      // finestra in cui le pressioni sono nostre
};
