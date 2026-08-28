#include "i18n.h"
#include <QFile>
#include <QJsonDocument>
#include <QtDebug>

I18n::I18n(const QString &dir, const QString &lang, QObject *parent) : QObject(parent), m_dir(dir) {
    if (!load("en", m_en)) qWarning("i18n: manca %s/en.json", qPrintable(dir));
    m_lang = "";
    setLang(lang);
}

bool I18n::load(const QString &lang, QVariantMap &out) const {
    QFile f(m_dir + "/" + lang + ".json");
    if (!f.open(QIODevice::ReadOnly)) return false;
    QJsonParseError pe;
    QJsonDocument d = QJsonDocument::fromJson(f.readAll(), &pe);
    if (pe.error != QJsonParseError::NoError) { qWarning("i18n: %s non valido: %s", qPrintable(f.fileName()), qPrintable(pe.errorString())); return false; }
    out = d.toVariant().toMap();
    return true;
}

void I18n::setLang(const QString &l0) {
    QString l = l0.isEmpty() ? "en" : l0;
    if (l == m_lang) return;
    m_lang = l;
    m_haveActive = false;
    m_active.clear();
    if (l != "en") {
        m_haveActive = load(l, m_active);
        if (!m_haveActive) qWarning("i18n: manca %s/%s.json, uso l'inglese", qPrintable(m_dir), qPrintable(l));
    }
    emit langChanged();
}

QVariant I18n::lookup(const QVariantMap &root, const QString &key) const {
    QVariant cur = root;
    for (const QString &part : key.split('.')) {
        if (cur.typeId() != QMetaType::QVariantMap) return QVariant();
        QVariantMap m = cur.toMap();
        auto it = m.constFind(part);
        if (it == m.constEnd()) return QVariant();
        cur = *it;
    }
    return cur;
}

QString I18n::t(const QString &key) const {
    if (key.isEmpty()) return QString();
    if (m_haveActive) { QVariant v = lookup(m_active, key); if (v.typeId() == QMetaType::QString) return v.toString(); }
    QVariant v = lookup(m_en, key);
    if (v.typeId() == QMetaType::QString) return v.toString();
    return key;                       // buco visibile invece di stringa vuota
}

QString I18n::tf(const QString &key, const QString &name, const QString &value) const {
    QString s = t(key);
    QString n1 = "{{" + name + "}}", n2 = "{" + name + "}";
    if (s.contains(n1)) return s.replace(n1, value);
    return s.replace(n2, value);
}

QVariant I18n::node(const QString &key) const {
    if (m_haveActive) { QVariant v = lookup(m_active, key); if (v.isValid()) return v; }
    return lookup(m_en, key);
}
