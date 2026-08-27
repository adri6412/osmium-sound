#include "vumeter.h"
#include "api.h"
#include <QJsonDocument>
#include <cmath>

static const double ANGLE_MIN = -36.4, ANGLE_MAX = 37.0;
static const double SPRING_K = 150.0, SPRING_C = 15.0, SPRING_M = 0.5, SPRING_REST = 0.02;
static const double LEVEL_DELTA = 2.0;

VuMeter::VuMeter(QObject *parent) : QObject(parent) {
    m_clock.start();
    connect(&m_sock, &QTcpSocket::readyRead, this, &VuMeter::onRead);
    connect(&m_sock, &QTcpSocket::connected, this, [this]() {
        m_upgraded = false;
        m_buf.clear();
        m_sock.write("GET / HTTP/1.1\r\nHost: 127.0.0.1:9001\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     "Sec-WebSocket-Key: AAAAAAAAAAAAAAAAAAAAAA==\r\nSec-WebSocket-Version: 13\r\n\r\n");
    });
    connect(&m_sock, &QTcpSocket::disconnected, this, [this]() { m_upgraded = false; emit connectedChanged(); });
    connect(&m_sock, &QTcpSocket::errorOccurred, this, [this](QAbstractSocket::SocketError) { m_upgraded = false; });
    // 30 Hz: e' il tetto di fotogrammi della UI Electron (setFrameRate(30) in
    // App.jsx) e dimezza il costo del ridisegno della scena, che in Qt Quick
    // e' sempre intero
    m_sim.setInterval(33);
    connect(&m_sim, &QTimer::timeout, this, &VuMeter::step);
    m_reconnect.setInterval(3000);
    connect(&m_reconnect, &QTimer::timeout, this, [this]() {
        if (m_active && m_sock.state() == QAbstractSocket::UnconnectedState) connectWs();
    });
    m_throttle.setInterval(50);
    connect(&m_throttle, &QTimer::timeout, this, [this]() {
        bool changed = false;
        for (int n = 0; n < 2; n++)
            if (std::fabs(m_peak[n] - m_committed[n]) >= LEVEL_DELTA) { m_committed[n] = m_peak[n]; m_target[n] = m_peak[n]; changed = true; }
        if (changed && !m_sim.isActive()) { m_lastStep = m_clock.elapsed(); m_sim.start(); }
    });
}

double VuMeter::deg(int n) const {
    double p = qBound(0.0, m_pos[n], 100.0);
    return ANGLE_MIN + (ANGLE_MAX - ANGLE_MIN) * p / 100.0;
}

void VuMeter::connectWs() {
    m_sock.abort();
    m_sock.connectToHost(Api::instance()->host(), 9001);
    m_sock.setSocketOption(QAbstractSocket::LowDelayOption, 1);
}

void VuMeter::setActive(bool a) {
    if (m_active == a) return;
    m_active = a;
    emit activeChanged();
    if (a) {
        connectWs();
        m_reconnect.start();
        m_throttle.start();
    } else {
        m_reconnect.stop();
        m_throttle.stop();
        m_sock.abort();
        m_upgraded = false;
        for (int n = 0; n < 2; n++) { m_peak[n] = m_target[n] = m_committed[n] = 0; }
        if (!m_sim.isActive()) { m_lastStep = m_clock.elapsed(); m_sim.start(); }   // gli aghi tornano a zero
        emit connectedChanged();
    }
}

void VuMeter::pong(const QByteArray &payload) {
    QByteArray p = payload.left(125);
    QByteArray f;
    f.append((char)0x8A);
    f.append((char)(0x80 | p.size()));
    const char key[4] = {0x21, 0x5A, (char)0xC3, 0x0F};
    f.append(key, 4);
    for (int i = 0; i < p.size(); i++) f.append((char)(p[i] ^ key[i & 3]));
    m_sock.write(f);
}

static double maxArray(const QVariant &v) {
    double mx = -1;
    for (const QVariant &x : v.toList()) { double d = x.toDouble(); if (mx < 0 || d > mx) mx = d; }
    return mx;
}

void VuMeter::onRead() {
    m_buf += m_sock.readAll();
    if (!m_upgraded) {
        int e = m_buf.indexOf("\r\n\r\n");
        if (e < 0) return;
        QByteArray hdr = m_buf.left(e);
        if (!hdr.contains(" 101")) { m_sock.abort(); return; }
        m_buf.remove(0, e + 4);
        m_upgraded = true;
        emit connectedChanged();
    }
    int off = 0;
    while (m_buf.size() - off >= 2) {
        quint8 b0 = (quint8)m_buf[off], b1 = (quint8)m_buf[off + 1];
        int opcode = b0 & 0x0f;
        bool masked = b1 & 0x80;
        quint64 len = b1 & 0x7f;
        int hdr = 2;
        if (len == 126) { if (m_buf.size() - off < 4) break; len = ((quint8)m_buf[off + 2] << 8) | (quint8)m_buf[off + 3]; hdr = 4; }
        else if (len == 127) { if (m_buf.size() - off < 10) break; len = 0; for (int i = 0; i < 8; i++) len = (len << 8) | (quint8)m_buf[off + 2 + i]; hdr = 10; }
        if (masked) hdr += 4;
        if ((quint64)(m_buf.size() - off) < (quint64)hdr + len) break;
        QByteArray payload = m_buf.mid(off + hdr, (int)len);
        if (opcode == 0x1) {
            QJsonDocument d = QJsonDocument::fromJson(payload);
            QVariantMap m = d.toVariant().toMap();
            double l = maxArray(m.value("levels_l")), r = maxArray(m.value("levels_r"));
            if (l >= 0) m_peak[0] = l;
            if (r >= 0) m_peak[1] = r;
        } else if (opcode == 0x9) pong(payload);
        else if (opcode == 0x8) { m_sock.abort(); m_buf.clear(); return; }
        off += hdr + (int)len;
    }
    if (off) m_buf.remove(0, off);
    if (m_buf.size() > 65536) m_buf.clear();
}

void VuMeter::step() {
    qint64 now = m_clock.elapsed();
    double dt = (now - m_lastStep) / 1000.0;
    m_lastStep = now;
    if (dt > 0.1) dt = 0.1;
    if (dt <= 0) return;
    bool moving = false;
    for (int n = 0; n < 2; n++) {
        int steps = (int)(dt / 0.004) + 1;
        double h = dt / steps;
        for (int i = 0; i < steps; i++) {
            double a = (-SPRING_K * (m_pos[n] - m_target[n]) - SPRING_C * m_vel[n]) / SPRING_M;
            m_vel[n] += a * h;
            m_pos[n] += m_vel[n] * h;
        }
        if (std::fabs(m_pos[n] - m_target[n]) > SPRING_REST || std::fabs(m_vel[n]) > SPRING_REST) moving = true;
        else { m_pos[n] = m_target[n]; m_vel[n] = 0; }
    }
    // sotto il decimo di pixel sulla punta non vale un fotogramma (vu.c)
    if (std::fabs(deg(0) - m_shown[0]) >= 0.02 || std::fabs(deg(1) - m_shown[1]) >= 0.02) {
        m_shown[0] = deg(0); m_shown[1] = deg(1);
        emit levelsChanged();
    }
    if (!moving) m_sim.stop();
}
