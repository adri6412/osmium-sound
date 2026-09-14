// i18n — le stesse traduzioni della UI Electron, caricate a runtime da
// locales/{en,it}.json. Da QML si usa il singleton Tr: `Tr.t("player.queue")`
// che si riaggiorna da solo al cambio di lingua.
#pragma once
#include <QObject>
#include <QVariantMap>

class I18n : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString lang READ lang WRITE setLang NOTIFY langChanged)
    Q_PROPERTY(QString dir READ dir CONSTANT)
public:
    explicit I18n(const QString &dir, const QString &lang, QObject *parent = nullptr);
    QString lang() const { return m_lang; }
    void setLang(const QString &l);
    QString dir() const { return m_dir; }

    // Traduce una chiave puntata; ripiega sull'inglese, poi sulla chiave stessa.
    Q_INVOKABLE QString t(const QString &key) const;
    // Sostituisce {{name}} o {name}.
    Q_INVOKABLE QString tf(const QString &key, const QString &name, const QString &value) const;
    // Sotto-albero (per elenchi: es. le voci di un menu)
    Q_INVOKABLE QVariant node(const QString &key) const;

signals:
    void langChanged();

private:
    QVariant lookup(const QVariantMap &root, const QString &key) const;
    bool load(const QString &lang, QVariantMap &out) const;
    QString m_dir, m_lang;
    QVariantMap m_en, m_active;
    bool m_haveActive = false;
};
