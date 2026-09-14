// api — client HTTP asincrono per i servizi locali dell'apparecchio.
//
// Tutto parla su loopback: Lyrion :9000, api_server :8000, sources :8080.
// Da QML si chiama `Api.get(url, cb)` / `Api.post(url, body, cb)` e la
// risposta arriva nella callback JavaScript come oggetto gia' analizzato
// (o come testo se non e' JSON). Niente thread: QNetworkAccessManager e'
// asincrono per costruzione, il ciclo di disegno non aspetta mai la rete.
//
// HIFI_HOST (variabile d'ambiente) sposta tutti e tre i servizi su un altro
// host: serve a far girare l'interfaccia sul PC di sviluppo contro il Dell.
#pragma once
#include <QObject>
#include <QJSValue>
#include <QJSEngine>
#include <QNetworkAccessManager>
#include <QVariant>
#include <QTimer>

class Api : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString host READ host CONSTANT)
    Q_PROPERTY(QString apiBase READ apiBase CONSTANT)   // api_server.py  :8000
    Q_PROPERTY(QString srcBase READ srcBase CONSTANT)   // sources_server :8080
    // 🚨 NON costante: se l'apparecchio segue il Lyrion di un altro (multiroom,
    // "server esterno"), l'indirizzo cambia sotto i piedi e tutto quello che
    // punta a Lyrion — copertine comprese — deve seguirlo. La verita' sta in
    // /lms_role dell'api_server, che la ricava dal -s di squeezelite.
    Q_PROPERTY(QString lmsBase READ lmsBase NOTIFY lmsBaseChanged)   // Lyrion :9000
public:
    explicit Api(QObject *parent = nullptr);
    static Api *instance();

    QString host() const { return m_host; }
    QString apiBase() const { return "http://" + m_host + ":8000"; }
    QString srcBase() const { return "http://" + m_host + ":8080"; }
    QString lmsBase() const { return "http://" + m_lmsHost + ":9000"; }

    // Rilegge /lms_role e, se serve, sposta l'indirizzo di Lyrion. Da QML si
    // chiama subito dopo aver cambiato ruolo, per non aspettare il giro.
    Q_INVOKABLE void refreshLmsHost();

    // cb(ok, data, status): `data` e' il JSON analizzato oppure il testo grezzo.
    Q_INVOKABLE void get(const QString &url, const QJSValue &cb = QJSValue(), int timeoutMs = 8000);
    Q_INVOKABLE void post(const QString &url, const QVariant &body, const QJSValue &cb = QJSValue(), int timeoutMs = 15000);
    Q_INVOKABLE void send(const QString &method, const QString &url, const QVariant &body,
                          const QJSValue &cb = QJSValue(), int timeoutMs = 15000);

    // Uso da C++: la callback riceve (ok, dati, status).
    using Handler = std::function<void(bool ok, const QVariant &data, int status)>;
    void request(const QString &method, const QString &url, const QByteArray &body, Handler h, int timeoutMs = 8000);

    // JSON-RPC di Lyrion: {"id":1,"method":"slim.request","params":[player,[...]]}
    void lmsRequest(const QString &player, const QVariantList &params, Handler h, int timeoutMs = 8000);

signals:
    void lmsBaseChanged();

public:
    QNetworkAccessManager *nam() { return &m_nam; }
    void setEngine(QJSEngine *e) { m_engine = e; }
    // Lingua della UI, mandata come X-UI-Lang: l'api_server traduce in quella
    // lingua i testi che compone lui (esiti, passi dell'aggiornamento).
    void setLang(const QString &l) { m_lang = (l == "it") ? "it" : "en"; }
    QJSEngine *engine() const { return m_engine; }

private:
    QString m_host;
    QString m_lmsHost;              // loopback, o l'apparecchio che si segue
    QTimer m_lmsPoll;               // il ruolo si cambia anche dal web: si ricontrolla
    bool m_lmsResolved = false;     // true once /lms_role has answered at least once
    QNetworkAccessManager m_nam;
    QJSEngine *m_engine = nullptr;
    QString m_lang = "en";
};
