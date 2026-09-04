// sys — piccole cose di sistema che a QML mancano: file di configurazione
// in /etc/hifi-player, tastiera fisica collegata (per decidere se mostrare
// quella a schermo), puntatore, fotografie dello schermo per il collaudo.
#pragma once
#include <QObject>
#include <QColor>
#include <QHash>
#include <QFileSystemWatcher>
#include <QTimer>

class QQuickWindow;

class Sys : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool hasKeyboard READ hasKeyboard NOTIFY hasKeyboardChanged)
    Q_PROPERTY(bool hasTouch READ hasTouch NOTIFY hasKeyboardChanged)
    Q_PROPERTY(bool pointerEnabled READ pointerEnabled WRITE setPointerEnabled NOTIFY pointerEnabledChanged)
    Q_PROPERTY(QString assets READ assets CONSTANT)
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

signals:
    void hasKeyboardChanged();
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
};
