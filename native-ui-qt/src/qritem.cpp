#include "qritem.h"
extern "C" {
#include "qr.h"
}
#include <QPainter>

QrItem::QrItem(QQuickItem *parent) : QQuickPaintedItem(parent) {
    setAntialiasing(false);
    setRenderTarget(QQuickPaintedItem::FramebufferObject);
}

void QrItem::setText(const QString &t) {
    if (t == m_text) return;
    m_text = t;
    QByteArray u = t.toUtf8();
    qr_t q;
    m_size = 0;
    m_m.clear();
    if (!u.isEmpty() && qr_encode(&q, (const unsigned char *)u.constData(), (size_t)u.size())) {
        m_size = q.size;
        m_m.resize(m_size);
        for (int y = 0; y < m_size; y++) {
            m_m[y].resize(m_size);
            for (int x = 0; x < m_size; x++) m_m[y][x] = q.m[y][x] != 0;
        }
    }
    emit textChanged();
    update();
}

void QrItem::paint(QPainter *p) {
    p->fillRect(boundingRect(), Qt::white);
    if (m_size <= 0) return;
    double side = qMin(width(), height());
    int ms = (int)(side / m_size);
    if (ms < 1) ms = 1;
    double ox = (width() - m_size * ms) / 2, oy = (height() - m_size * ms) / 2;
    p->setPen(Qt::NoPen);
    p->setBrush(Qt::black);
    for (int y = 0; y < m_size; y++)
        for (int x = 0; x < m_size; x++)
            if (m_m[y][x]) p->drawRect(QRectF(ox + x * ms, oy + y * ms, ms, ms));
}
