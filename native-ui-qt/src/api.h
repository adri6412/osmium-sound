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

class Api : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString host READ host CONSTANT)
    Q_PROPERTY(QString apiBase READ apiBase CONSTANT)   // api_server.py  :8000
    Q_PROPERTY(QString srcBase READ srcBase CONSTANT)   // sources_server :8080
    Q_PROPERTY(QString lmsBase READ lmsBase CONSTANT)   // Lyrion         :9000
public:
    explicit Api(QObject *parent = nullptr);
    static Api *instance();

    QString host() const { return m_host; }
    QString apiBase() const { return "http://" + m_host + ":8000"; }
    QString srcBase() const { return "http://" + m_host + ":8080"; }
    QString lmsBase() const { return "http://" + m_host + ":9000"; }

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

    QNetworkAccessManager *nam() { return &m_nam; }
    void setEngine(QJSEngine *e) { m_engine = e; }
    QJSEngine *engine() const { return m_engine; }

private:
    QString m_host;
    QNetworkAccessManager m_nam;
    QJSEngine *m_engine = nullptr;
};
