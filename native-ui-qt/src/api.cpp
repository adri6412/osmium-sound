#include "api.h"
#include <QJSEngine>
#include <QJsonDocument>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QQmlEngine>
#include <QtGlobal>

static Api *g_api = nullptr;

Api::Api(QObject *parent) : QObject(parent) {
    m_host = qEnvironmentVariable("HIFI_HOST", "127.0.0.1");
    g_api = this;
    // una connessione riusata per richiesta consecutiva (keep-alive di Qt)
    m_nam.setTransferTimeout(8000);
}

Api *Api::instance() { return g_api; }

void Api::request(const QString &method, const QString &url, const QByteArray &body, Handler h, int timeoutMs) {
    QNetworkRequest req{QUrl(url)};
    req.setTransferTimeout(timeoutMs);
    req.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::NoLessSafeRedirectPolicy);
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
