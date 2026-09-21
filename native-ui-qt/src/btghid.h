// btghid — il ponte per i telecomandi Bluetooth che il nucleo rifiuta.
//
// 🚨 Perche' esiste. Un telecomando BLE dichiara i suoi tasti in una "mappa
// dei rapporti" HID che BlueZ legge con UNA sola lettura ATT. Con l'MTU
// minimo (23) quella lettura torna 22 byte, e la mappa di un telecomando
// qualsiasi e' lunga il decuplo: arriva mozzata, il nucleo la scarta
// ("unbalanced collection at end of report description") e NON crea nessun
// /dev/input. Il telecomando risulta collegato e non fa niente. Misurato sul
// campo con un G20S PRO: 22 byte su 228.
//
// Qui la si rilegge come andava letta — a blocchi, con l'offset, che da D-Bus
// si puo' chiedere — e con la mappa intera si crea un dispositivo HID nostro
// (/dev/uhid). Poi ci si mette in ascolto delle notifiche dei rapporti e le si
// riversa dentro. Da li' in poi il nucleo fa il suo mestiere: nasce un
// /dev/input normale, e tutto il resto dell'interfaccia (remote.cpp, la
// navigazione, la mappatura dei tasti) non sa nemmeno che e' successo.
//
// 🚨 Si interviene SOLO sui dispositivi che il nucleo ha rifiutato: se il
// telecomando funziona da se', qui non si tocca niente. E siccome "ce l'ha
// fatta" si vede solo dopo che BlueZ ha finito il suo giro, si aspetta qualche
// secondo prima di decidere, e si chiude il ponte se il nodo del nucleo
// compare dopo — altrimenti lo stesso telecomando finisce a mandare i tasti
// due volte (successo con un telecomando Xiaomi: quattro nodi invece di due).
#pragma once
#include <QDBusObjectPath>
#include <QDBusVariant>
#include <QHash>
#include <QObject>
#include <QStringList>
#include <QTimer>
#include <QVariantList>

class QSocketNotifier;

class BtGattHid : public QObject {
    Q_OBJECT
    // i telecomandi per cui stiamo facendo da ponte, per la schermata
    // Telecomando: [{ mac, name, reports }]
    Q_PROPERTY(QVariantList bridged READ bridged NOTIFY bridgedChanged)
public:
    explicit BtGattHid(QObject *parent = nullptr);
    ~BtGattHid() override;

    QVariantList bridged() const;
    // I nomi dei dispositivi di input che abbiamo creato noi: remote.cpp li
    // tratta come telecomandi veri (li ha creati il nucleo, ma sappiamo che
    // dietro c'e' il nostro ponte).
    QStringList bridgedNames() const;
    Q_INVOKABLE void rescan() { poll(); }

signals:
    void bridgedChanged();

private:
    struct Report {
        QString path;          // la caratteristica GATT
        int id = 0;            // report id, dal Report Reference
        int fd = -1;           // quello che ci da' AcquireNotify
        QSocketNotifier *notifier = nullptr;
    };
    struct Bridge {
        QString devPath;       // /org/bluez/hci0/dev_XX_XX...
        QString mac, name;
        int uhid = -1;
        QSocketNotifier *uhidNotifier = nullptr;
        QList<Report> reports;
        bool created = false;
    };

    void poll();
    bool kernelHandles(const QString &mac) const;   // il nucleo ce l'ha gia' fatto?
    void start(const QString &devPath, const QString &mac, const QString &name,
               const QVariantMap &props);
    void stop(const QString &devPath);
    QByteArray readCharacteristic(const QString &path) const;   // a blocchi
    void onReport(const QString &devPath, int index);
    void onUhidEvent(const QString &devPath);

    QHash<QString, Bridge> m_bridges;     // devPath -> ponte
    QStringList m_failed;                 // dispositivi su cui abbiamo gia' rinunciato
    QHash<QString, qint64> m_seen;        // devPath -> da quando e' collegato (ms)
    QTimer m_poll;
};
