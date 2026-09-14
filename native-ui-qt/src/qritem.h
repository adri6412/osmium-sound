// qritem — il codice QR disegnato da Qt Quick, con lo stesso generatore della
// UI in C (qr.c, identico a qrcode.react: modo byte, livello M alzato al
// massimo che entra, versioni 1..20).
#pragma once
#include <QQuickPaintedItem>
#include <qqml.h>

class QrItem : public QQuickPaintedItem {
    Q_OBJECT
    QML_NAMED_ELEMENT(QrCode)
    Q_PROPERTY(QString text READ text WRITE setText NOTIFY textChanged)
    Q_PROPERTY(int modules READ modules NOTIFY textChanged)
public:
    explicit QrItem(QQuickItem *parent = nullptr);
    QString text() const { return m_text; }
    void setText(const QString &t);
    int modules() const { return m_size; }
    void paint(QPainter *p) override;
signals:
    void textChanged();
private:
    QString m_text;
    int m_size = 0;
    QVector<QVector<bool>> m_m;
};
