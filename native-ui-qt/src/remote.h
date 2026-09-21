// remote — telecomandi: una chiavetta USB (ricevitore a 2,4 GHz, ricevitore a
// infrarossi tipo MCE, Flirc) o un telecomando Bluetooth gia' accoppiato.
//
// Sotto sono la stessa cosa: il nucleo li espone come dispositivi evdev che
// mandano i codici HID standard (KEY_PLAYPAUSE, KEY_NEXTSONG, le frecce,
// KEY_OK...). Qui li si riconosce, li si legge e li si traduce in azioni
// dell'interfaccia ("playPause", "down", "ok"...) che App.qml smista.
//
// 🚨 Perche' leggere evdev invece di aspettare i tasti da Qt: su eglfs i tasti
// passano dal plugin di input di Qt, la cui mappa non copre i tasti multimedia
// su tutte le combinazioni di Qt/libinput — e comunque servono il nome del
// dispositivo (per la schermata Telecomando), il codice grezzo (per il
// pannello "premi un tasto") e la presa esclusiva.
//
// 🚨 Tastiera e telecomando mandano gli STESSI codici: un telecomando come il
// G20S PRO si presenta al nucleo come "G20S PRO Keyboard". Percio' quello che
// distingue i due non e' il codice ma il DISPOSITIVO, e tutto quello che
// l'utente decide (quale tasto fa cosa) e' scritto per dispositivo. Chi vuole,
// dice anche qual e' il suo telecomando: da quel momento di quello si
// ascoltano tutti i tasti, non solo quelli multimediali.
//
// 🚨 La presa esclusiva (EVIOCGRAB) si prende SOLO su un telecomando vero:
//   - una tastiera completa non si prende mai, o non si scrive piu';
//   - un dispositivo che e' anche puntatore (air mouse) non si prende mai, o
//     il puntatore si ferma;
//   - un telecomando preso non arriva piu' nemmeno a logind, ed e' voluto: il
//     tasto di accensione di un telecomando non deve spegnere l'apparecchio.
// Quello che non si prende si legge lo stesso, ma solo per i tasti
// multimediali: frecce e invio di una tastiera li porta gia' Qt, e agire due
// volte sullo stesso tasto sarebbe peggio che non agire.
#pragma once
#include <QElapsedTimer>
#include <QFileSystemWatcher>
#include <QHash>
#include <QObject>
#include <QStringList>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>

class QSocketNotifier;

class Remote : public QObject {
    Q_OBJECT
    // i telecomandi visti adesso: [{ name, path, bus, kind, grabbed }]
    Q_PROPERTY(QVariantList devices READ devices NOTIFY devicesChanged)
    Q_PROPERTY(bool present READ present NOTIFY devicesChanged)
    // l'ultimo tasto ricevuto, per il pannello di prova:
    // { code, key, action, device, at }
    Q_PROPERTY(QVariantMap lastKey READ lastKey NOTIFY lastKeyChanged)
    // In prova i tasti si mostrano soltanto: nessuna azione parte, o premere
    // "ok" per vedere che tasto e' finirebbe per aprire qualcosa.
    Q_PROPERTY(bool learning READ learning WRITE setLearning NOTIFY learningChanged)
    // 🚨 Il pannello di prova ascolta UN dispositivo solo: con una tastiera
    // attaccata accanto al telecomando, ogni tasto premuto per sbaglio sulla
    // tastiera si prendeva il posto di quello del telecomando.
    Q_PROPERTY(QString learnDevice READ learnDevice NOTIFY learnDeviceChanged)
    // il dispositivo che l'utente ha indicato come "il mio telecomando" ("" =
    // nessuno): di quello si ascoltano tutti i tasti
    Q_PROPERTY(QString chosen READ chosen NOTIFY devicesChanged)
public:
    explicit Remote(const QString &configDir, QObject *parent = nullptr);
    ~Remote() override;

    QVariantList devices() const { return m_devices; }
    bool present() const { return !m_devices.isEmpty(); }
    QVariantMap lastKey() const { return m_lastKey; }
    bool learning() const { return m_learning; }
    void setLearning(bool on);

    Q_INVOKABLE void rescan();
    QString learnDevice() const { return m_learnDevice; }
    // ricomincia ad ascoltare: il prossimo tasto decide il dispositivo
    Q_INVOKABLE void listenAgain();
    QString chosen() const { return m_chosen; }
    // "questo e' il mio telecomando" (nome vuoto = nessuno). Finisce in
    // <configDir>/remote-device e vale da subito.
    Q_INVOKABLE void setChosen(const QString &device);
    // l'azione di un codice evdev su quel dispositivo ("" se non fa niente):
    // prima quello che l'utente ha deciso per QUEL dispositivo, poi quello che
    // vale per tutti, poi la mappa di serie
    Q_INVOKABLE QString actionFor(int code, const QString &device = QString()) const;
    // l'azione di un tasto Qt: la strada dei dispositivi che NON prendiamo in
    // esclusiva (una tastiera con i tasti multimediali, un air mouse) e di
    // chi usa una tastiera vera attaccata all'apparecchio
    Q_INVOKABLE QString actionForQtKey(int key) const;
    // il nome del tasto, per il pannello di prova ("KEY_PLAYPAUSE", o il
    // numero quando il nome non lo conosciamo)
    Q_INVOKABLE QString keyName(int code) const;
    // tutte le azioni assegnabili, nell'ordine in cui si mostrano
    Q_INVOKABLE QStringList actionNames() const;
    // assegna un tasto a un'azione (azione vuota = il tasto non fa niente):
    // finisce in <configDir>/remote-keys.json e vale da subito
    Q_INVOKABLE bool assign(int code, const QString &action, const QString &device = QString());
    Q_INVOKABLE bool isCustom(int code, const QString &device = QString()) const;
    // toglie l'assegnazione fatta a mano: il tasto torna a quello di serie
    Q_INVOKABLE bool forget(int code, const QString &device = QString());
    // Ogni strada (evdev, tasti Qt, canale di collaudo) passa di qui: e' il
    // punto in cui si scarta il doppione quando lo stesso tasto arriva da due
    // sorgenti (un dispositivo non preso letto sia da noi che da Qt).
    Q_INVOKABLE void dispatch(const QString &action, bool repeat = false, const QString &source = QStringLiteral("qt"));

signals:
    void action(const QString &name, bool repeat);
    void devicesChanged();
    void lastKeyChanged();
    void learningChanged();
    void learnDeviceChanged();

private:
    struct Dev {
        QString path;              // /dev/input/eventN
        QString name;              // il nome che dichiara il dispositivo
        QString bus;               // "usb", "bluetooth", "other"
        bool remote = false;       // telecomando vero (non una tastiera)
        bool chosen = false;       // l'utente ha detto che e' il suo telecomando
        bool grabbed = false;      // presa esclusiva ottenuta
        int fd = -1;
        QSocketNotifier *notifier = nullptr;
    };

    void openDevice(const QString &path);
    void closeDevice(const QString &path);
    void readFrom(const QString &path);
    void onKey(Dev &dev, int code, int value);
    void publishDevices();
    void loadCustom();
    bool saveCustom(int code, const QString &device);      // scrive remote-keys.json
    void startRepeat(const QString &action);
    void stopRepeat();

    QString m_configDir;
    QHash<QString, Dev> m_open;      // path -> dispositivo aperto
    // quello che l'utente ha deciso: dispositivo ("" = vale per tutti) ->
    // codice -> azione. Da remote-keys.json.
    QHash<QString, QHash<int, QString>> m_custom;
    QString m_chosen;                // il nome del "mio telecomando"
    QString m_learnDevice;           // chi sta parlando al pannello di prova
    QVariantList m_devices;
    QVariantMap m_lastKey;
    bool m_learning = false;
    QFileSystemWatcher m_watch;
    QTimer m_rescan;
    // ripetizione nostra, per i telecomandi che non la mandano da soli
    QTimer m_repeat;
    QString m_repeatAction;
    int m_repeatCode = 0;
    bool m_kernelRepeats = false;
    // doppione fra sorgenti diverse
    QElapsedTimer m_clock;
    QString m_lastAction, m_lastSource;
    qint64 m_lastAt = -10000;
};
