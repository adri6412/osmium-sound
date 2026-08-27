// vumeter — i livelli dal daemon (vu_meter_daemon.py, WebSocket :9001) e la
// molla degli aghi, con gli stessi numeri di AnalogVUMeter.jsx e vu.c:
// throttle 50 ms, soglia 2, molla k 150 / c 15 / m 0,5, angoli -36,4..+37.
//
// Espone leftDeg/rightDeg gia' pronti per `rotation` in QML. La simulazione
// gira solo mentre gli aghi si muovono: a riposo non c'e' nessun timer.
#pragma once
#include <QObject>
#include <QTcpSocket>
#include <QTimer>
#include <QElapsedTimer>

class VuMeter : public QObject {
    Q_OBJECT
    Q_PROPERTY(bool active READ active WRITE setActive NOTIFY activeChanged)
    Q_PROPERTY(bool connected READ connected NOTIFY connectedChanged)
    Q_PROPERTY(double leftDeg READ leftDeg NOTIFY levelsChanged)
    Q_PROPERTY(double rightDeg READ rightDeg NOTIFY levelsChanged)
    Q_PROPERTY(double left READ left NOTIFY levelsChanged)      // 0..100
    Q_PROPERTY(double right READ right NOTIFY levelsChanged)
public:
    explicit VuMeter(QObject *parent = nullptr);
    bool active() const { return m_active; }
    void setActive(bool a);
    bool connected() const { return m_sock.state() == QAbstractSocket::ConnectedState && m_upgraded; }
    double leftDeg() const { return deg(0); }
    double rightDeg() const { return deg(1); }
    double left() const { return m_pos[0]; }
    double right() const { return m_pos[1]; }
signals:
    void activeChanged();
    void connectedChanged();
    void levelsChanged();
private:
    double deg(int n) const;
    void connectWs();
    void onRead();
    void step();
    void pong(const QByteArray &payload);
    QTcpSocket m_sock;
    QByteArray m_buf;
    bool m_active = false, m_upgraded = false;
    QTimer m_sim, m_reconnect, m_throttle;
    QElapsedTimer m_clock;
    qint64 m_lastStep = 0;
    double m_peak[2] = {0, 0}, m_target[2] = {0, 0}, m_pos[2] = {0, 0}, m_vel[2] = {0, 0}, m_committed[2] = {0, 0};
    double m_shown[2] = {-1000, -1000};
};
