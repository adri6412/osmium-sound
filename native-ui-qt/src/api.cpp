#include "api.h"
#include <QJSEngine>
#include <QJsonDocument>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QQmlEngine>
#include <QtGlobal>

static Api *g_api = nullptr;

// Retry interval for /lms_role before and after the first answer.
static const int LMS_POLL_FAST = 1000;
static const int LMS_POLL_SLOW = 15000;

Api::Api(QObject *parent) : QObject(parent) {
    m_host = qEnvironmentVariable("HIFI_HOST", "127.0.0.1");
    m_lmsHost = m_host;
    g_api = this;
    // una connessione riusata per richiesta consecutiva (keep-alive di Qt)
    m_nam.setTransferTimeout(8000);
    // 🚨 The role (own Lyrion, or another device's) is also changed from the
    // web admin page without going through here, so it is re-read on a timer
    // as well as on demand. Fast until the first answer, then slow: at boot
    // this runs before hifi-api is up, and until the role is known everything
    // Lyrion-side points at loopback — on a unit that follows another server
    // that is the wrong one — which is how a startup ends up on the local
    // server even though an external one was chosen.
    m_lmsPoll.setInterval(LMS_POLL_FAST);
    connect(&m_lmsPoll, &QTimer::timeout, this, &Api::refreshLmsHost);
    m_lmsPoll.start();
    QTimer::singleShot(0, this, &Api::refreshLmsHost);
}

void Api::refreshLmsHost() {
    request("GET", apiBase() + "/lms_role", {}, [this](bool ok, const QVariant &d, int) {
        if (!ok) return;
        if (!m_lmsResolved) {           // answered: back off to the watch interval
            m_lmsResolved = true;
            m_lmsPoll.setInterval(LMS_POLL_SLOW);
        }
        const QVariantMap m = d.toMap();
        const QString host = m.value("host").toString();
        // "local" vuol dire il Lyrion di questo apparecchio: si torna a m_host
        // (non a 127.0.0.1 fisso, o si romperebbe HIFI_HOST in sviluppo).
        const QString want = (m.value("mode").toString() == "follow" && !host.isEmpty()) ? host : m_host;
        if (want == m_lmsHost) return;
        qInfo("lyrion: si passa a %s", qPrintable(want));
        m_lmsHost = want;
        emit lmsBaseChanged();
    }, 6000);
}

Api *Api::instance() { return g_api; }

void Api::request(const QString &method, const QString &url, const QByteArray &body, Handler h, int timeoutMs) {
    QNetworkRequest req{QUrl(url)};
    req.setTransferTimeout(timeoutMs);
    req.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
    req.setRawHeader("X-UI-Lang", m_lang.toUtf8());
    if (!body.isEmpty() || method == "POST")
        req.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    QNetworkReply *rep = m_nam.sendCustomRequest(req, method.toUtf8(), body);
    connect(rep, &QNetworkReply::finished, this, [rep, h]() {
        rep->deleteLater();
        int status = rep->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        bool ok = rep->error() == QNetworkReply::NoError || (status >= 200 && status < 600 && rep->error() == QNetworkReply::ContentNotFoundError) ||
                  (status > 0 && rep->error() != QNetworkReply::OperationCanceledError && rep->error() != QNetworkReply::ConnectionRefusedError &&
                   rep->error() != QNetworkReply::TimeoutError && rep->error() != QNetworkReply::HostNotFoundError &&
                   rep->error() != QNetworkReply::RemoteHostClosedError);
        QByteArray raw = rep->readAll();
        QVariant data;
        QJsonParseError pe;
        QJsonDocument doc = QJsonDocument::fromJson(raw, &pe);
        if (pe.error == QJsonParseError::NoError && !doc.isNull()) data = doc.toVariant();
        else data = QString::fromUtf8(raw);
        if (h) h(ok, data, status);
    });
}

static QByteArray bodyBytes(const QVariant &body0) {
    QVariant body = body0;
    // 🚨 un oggetto passato da QML arriva come QJSValue, non come QVariantMap:
    // senza scartarlo QJsonDocument::fromVariant produce "null" e il servizio
    // risponde 400 (era il motivo per cui NESSUNA impostazione veniva salvata)
    if (body.userType() == qMetaTypeId<QJSValue>()) body = body.value<QJSValue>().toVariant();
    if (!body.isValid() || body.isNull()) return QByteArray();
    if (body.typeId() == QMetaType::QString) return body.toString().toUtf8();
    if (body.typeId() == QMetaType::QByteArray) return body.toByteArray();
    return QJsonDocument::fromVariant(body).toJson(QJsonDocument::Compact);
}

void Api::send(const QString &method, const QString &url, const QVariant &body, const QJSValue &cb, int timeoutMs) {
    QJSValue f = cb;
    request(method, url, bodyBytes(body), [f](bool ok, const QVariant &data, int status) mutable {
        if (!f.isCallable()) return;
        QJSEngine *eng = Api::instance()->engine();
        QJSValueList args;
        if (eng) {
            args << QJSValue(ok) << eng->toScriptValue(data) << QJSValue(status);
        } else {
            args << QJSValue(ok) << QJSValue(data.toString()) << QJSValue(status);
        }
        QJSValue r = f.call(args);
        if (r.isError()) qWarning("api: errore nella callback: %s", qPrintable(r.toString()));
    }, timeoutMs);
}

void Api::get(const QString &url, const QJSValue &cb, int timeoutMs) { send("GET", url, QVariant(), cb, timeoutMs); }
void Api::post(const QString &url, const QVariant &body, const QJSValue &cb, int timeoutMs) {
    QVariant b = body;
    if (!b.isValid()) b = QVariantMap();
    send("POST", url, b, cb, timeoutMs);
}

void Api::lmsRequest(const QString &player, const QVariantList &params, Handler h, int timeoutMs) {
    QVariantMap m;
    m["id"] = 1;
    m["method"] = "slim.request";
    m["params"] = QVariantList{player, params};
    request("POST", lmsBase() + "/jsonrpc.js", QJsonDocument::fromVariant(m).toJson(QJsonDocument::Compact), h, timeoutMs);
}
