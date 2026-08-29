// player — lo stato del player Lyrion e i comandi, come useLyrionPlayer.js
// e i moduli lms.c/poller.c della UI in C.
//
// Interroga `status` una volta al secondo (e subito dopo ogni comando), i
// playerpref ogni 5 s, e legge dal api_server le impostazioni che cambiano
// il player espanso (VU, auto-apertura) e lo stato dell'aggiornamento. Tutto
// asincrono: il ciclo di disegno non aspetta mai la rete.
#pragma once
#include <QObject>
#include <QJSValue>
#include <QTimer>
#include <QVariant>
#include <QElapsedTimer>

class Player : public QObject {
    Q_OBJECT
    // collegamento
    Q_PROPERTY(bool connected READ connected NOTIFY connectedChanged)
    Q_PROPERTY(QString playerName READ playerName NOTIFY connectedChanged)
    Q_PROPERTY(QString playerId READ playerId NOTIFY connectedChanged)
    // brano
    Q_PROPERTY(QString title READ title NOTIFY metaChanged)
    Q_PROPERTY(QString artist READ artist NOTIFY metaChanged)
    Q_PROPERTY(QString album READ album NOTIFY metaChanged)
    Q_PROPERTY(QString trackId READ trackId NOTIFY metaChanged)
    Q_PROPERTY(QString coverId READ coverId NOTIFY metaChanged)
    Q_PROPERTY(bool remote READ remote NOTIFY metaChanged)
    Q_PROPERTY(QString type READ type NOTIFY metaChanged)
    Q_PROPERTY(int sampleSize READ sampleSize NOTIFY metaChanged)
    Q_PROPERTY(double sampleRate READ sampleRate NOTIFY metaChanged)
    Q_PROPERTY(QString bitrate READ bitrate NOTIFY metaChanged)
    Q_PROPERTY(QString chip READ chip NOTIFY metaChanged)          // "FLAC · 24bit · 96kHz"
    Q_PROPERTY(QString artworkUrl READ artworkUrl NOTIFY artworkChanged)
    // quanti pixel chiedere a Lyrion per la copertina: la sceglie Main.qml
    // dal modo video (600 sulla tela 1 a 1, fino a 1200 a 4K)
    Q_PROPERTY(int coverPx READ coverPx WRITE setCoverPx NOTIFY coverPxChanged)
    Q_PROPERTY(bool qPcm READ qPcm NOTIFY metaChanged)
    Q_PROPERTY(bool qHires READ qHires NOTIFY metaChanged)
    Q_PROPERTY(bool qDsd READ qDsd NOTIFY metaChanged)
    // avanzamento
    Q_PROPERTY(double elapsed READ elapsed NOTIFY progressChanged)
    Q_PROPERTY(double duration READ duration NOTIFY progressChanged)
    // comandi
    Q_PROPERTY(bool playing READ playing NOTIFY controlsChanged)
    Q_PROPERTY(int volume READ volume NOTIFY controlsChanged)
    Q_PROPERTY(int shuffle READ shuffle NOTIFY controlsChanged)
    Q_PROPERTY(int repeat READ repeat NOTIFY controlsChanged)
    Q_PROPERTY(int sleepSecs READ sleepSecs NOTIFY controlsChanged)
    Q_PROPERTY(int index READ index NOTIFY controlsChanged)
    Q_PROPERTY(int total READ total NOTIFY controlsChanged)
    // derivati dai playerpref
    Q_PROPERTY(int ledMode READ ledMode NOTIFY modeChanged)          // 0 nessuno, 1 BitPerfect, 2 ReplayGain
    Q_PROPERTY(bool volumeFixed READ volumeFixed NOTIFY modeChanged)
    Q_PROPERTY(QString prefReplayGain READ prefReplayGain NOTIFY modeChanged)
    Q_PROPERTY(QString prefTransitionType READ prefTransitionType NOTIFY modeChanged)
    Q_PROPERTY(QString prefTransitionDur READ prefTransitionDur NOTIFY modeChanged)
    Q_PROPERTY(QString prefDigitalVol READ prefDigitalVol NOTIFY modeChanged)
    // impostazioni lette dal api_server
    Q_PROPERTY(bool vuEnabled READ vuEnabled WRITE setVuEnabled NOTIFY settingsChanged)
    Q_PROPERTY(int autoexpandSecs READ autoexpandSecs NOTIFY settingsChanged)
    // aggiornamento in corso
    Q_PROPERTY(QString otaState READ otaState NOTIFY otaChanged)
    Q_PROPERTY(QString otaMessage READ otaMessage NOTIFY otaChanged)
    Q_PROPERTY(QString otaKind READ otaKind NOTIFY otaChanged)
    Q_PROPERTY(int otaPercent READ otaPercent NOTIFY otaChanged)
public:
    explicit Player(QObject *parent = nullptr);
    void start();

    bool connected() const { return m_connected; }
    QString playerName() const { return m_playerName; }
    QString playerId() const { return m_playerId; }
    QString title() const { return m_title; }
    QString artist() const { return m_artist; }
    QString album() const { return m_album; }
    QString trackId() const { return m_id; }
    QString coverId() const { return m_coverId; }
    bool remote() const { return m_remote; }
    QString type() const { return m_type; }
    int sampleSize() const { return m_sampleSize; }
    double sampleRate() const { return m_sampleRate; }
    QString bitrate() const { return m_bitrate; }
    QString chip() const { return m_chip; }
    QString artworkUrl() const { return m_artworkUrl; }
    int coverPx() const { return m_coverPx; }
    void setCoverPx(int px);
    bool qPcm() const { return m_qPcm; }
    bool qHires() const { return m_qHires; }
    bool qDsd() const { return m_qDsd; }
    double elapsed() const { return m_elapsed; }
    double duration() const { return m_duration; }
    bool playing() const { return m_playing; }
    int volume() const { return m_volume; }
    int shuffle() const { return m_shuffle; }
    int repeat() const { return m_repeat; }
    int sleepSecs() const { return m_sleepSecs; }
    int index() const { return m_index; }
    int total() const { return m_total; }
    int ledMode() const { return m_ledMode; }
    bool volumeFixed() const { return m_volumeFixed; }
    QString prefReplayGain() const { return m_prefRg; }
    QString prefTransitionType() const { return m_prefTrType; }
    QString prefTransitionDur() const { return m_prefTrDur; }
    QString prefDigitalVol() const { return m_prefDigVol; }
    bool vuEnabled() const { return m_vuEnabled; }
    void setVuEnabled(bool on);
    int autoexpandSecs() const { return m_autoexpand; }
    QString otaState() const { return m_otaState; }
    QString otaMessage() const { return m_otaMsg; }
    QString otaKind() const { return m_otaKind; }
    int otaPercent() const { return m_otaPct; }

    // ─── comandi (stessi di lms.c) ────────────────────────────────────────
    Q_INVOKABLE void togglePlay();
    Q_INVOKABLE void play(bool on);
    Q_INVOKABLE void next();
    Q_INVOKABLE void prev();
    Q_INVOKABLE void seek(double seconds);
    Q_INVOKABLE void seekFraction(double f);
    Q_INVOKABLE void setVolume(int v, bool final = true);   // throttle 120 ms, come ui.c
    Q_INVOKABLE void toggleMute();
    Q_INVOKABLE void cycleShuffle();
    Q_INVOKABLE void cycleRepeat();
    Q_INVOKABLE void setShuffle(int m);
    Q_INVOKABLE void setRepeat(int m);
    Q_INVOKABLE void setSleep(int seconds);
    // Comando qualsiasi al player, es. ["playlistcontrol","cmd:load","album_id:12"].
    Q_INVOKABLE void cmd(const QVariantList &params);
    // Interrogazione con risposta: cb(ok, result) dove result e' `result` del JSON-RPC.
    Q_INVOKABLE void query(const QVariantList &params, const QJSValue &cb);
    // Come query ma senza player (comandi di server: players, serverstatus...).
    Q_INVOKABLE void queryServer(const QVariantList &params, const QJSValue &cb);
    // Testi del brano corrente: cb(text) con "" se assenti.
    Q_INVOKABLE void lyrics(const QJSValue &cb);
    // Rilegge subito lo stato.
    Q_INVOKABLE void refresh();
    Q_INVOKABLE void refreshPrefs();
    Q_INVOKABLE void refreshSettings();
    Q_INVOKABLE QString formatTime(double sec) const;

signals:
    void connectedChanged();
    void metaChanged();
    void artworkChanged();
    void coverPxChanged();
    void progressChanged();
    void controlsChanged();
    void modeChanged();
    void settingsChanged();
    void otaChanged();
    void usbMounted(const QString &label);
    void trackChanged();          // brano nuovo (titolo/artista/album diversi)

private:
    void findPlayer();
    void fetchLocalName();          // come ci chiamiamo su Lyrion (-n di squeezelite)
    void onLmsHostChanged();        // si e' passati a un altro Lyrion: si ricomincia
    void pollStatus();
    void pollPrefs();
    void pollSettings();
    void pollUsb();
    void pollOta();
    void derive();
    void updateArtwork();
    void flushVolume();
    void callJs(QJSValue cb, const QVariantList &args);

    QTimer m_tick, m_statusTimer;
    QElapsedTimer m_clock;
    qint64 m_lastStatus = 0, m_lastPrefs = 0, m_lastSettings = 0, m_lastUsb = 0, m_lastOta = 0, m_lastElapsedTick = 0;
    bool m_statusInFlight = false, m_wantNow = false;

    bool m_connected = false;
    QString m_playerName, m_playerId, m_localName;
    QString m_title, m_artist, m_album, m_id, m_coverId, m_artworkUrlLms, m_type, m_bitrate, m_chip, m_currentTitle;
    QString m_artworkUrl, m_artKey;
    bool m_remote = false, m_qPcm = false, m_qHires = false, m_qDsd = false;
    int m_sampleSize = 0;
    double m_sampleRate = 0, m_elapsed = 0, m_duration = 0;
    bool m_playing = false;
    int m_volume = 0, m_shuffle = 0, m_repeat = 0, m_sleepSecs = 0, m_index = 0, m_total = 0;
    int m_ledMode = 0;
    int m_coverPx = 600;
    bool m_volumeFixed = false;
    QString m_prefRg = "0", m_prefTrType = "0", m_prefTrDur = "0", m_prefDigVol = "1";
    bool m_vuEnabled = true;
    int m_autoexpand = 0;
    QString m_otaState = "idle", m_otaMsg, m_otaKind;
    int m_otaPct = 0;
    // volume: throttle
    qint64 m_volSentMs = 0;
    int m_volPending = -1;
    // chiavette usb
    QStringList m_usbSeen;
    bool m_usbBaseline = false;
};
