#include "spring.h"
#include <cmath>

class Spring::Driver : public QAbstractAnimation {
public:
    explicit Driver(Spring *s) : QAbstractAnimation(s), m_s(s) {}
    int duration() const override { return -1; }        // finche' non e' a riposo
protected:
    void updateCurrentTime(int ms) override {
        double dt = (ms - m_last) / 1000.0;
        m_last = ms;
        if (dt <= 0) return;
        if (dt > 0.1) dt = 0.1;
        m_s->step(dt);
    }
    void updateState(State ns, State) override { if (ns == Running) m_last = 0; }
private:
    Spring *m_s;
    int m_last = 0;
};

Spring::Spring(QObject *parent) : QObject(parent), m_drv(new Driver(this)) {}

void Spring::setRunning(bool r) {
    if (m_running == r) return;
    m_running = r;
    emit runningChanged();
}

void Spring::set(double v) {
    m_drv->stop();
    bool ch = v != m_v;
    m_v = m_to = v;
    m_vel = 0;
    setRunning(false);
    if (ch) emit valueChanged();
    emit toChanged();
}

void Spring::setTo(double t) {
    if (t == m_to && (m_running || t == m_v)) return;
    m_to = t;
    emit toChanged();
    if (std::fabs(m_to - m_v) < m_restDelta && std::fabs(m_vel) < m_restSpeed) { m_v = m_to; m_vel = 0; emit valueChanged(); return; }
    if (!m_running) { setRunning(true); m_drv->start(); }
}

void Spring::finish() {
    if (!m_running) return;
    m_drv->stop();
    m_v = m_to; m_vel = 0;
    setRunning(false);
    emit valueChanged();
    emit finished();
}

void Spring::step(double dt) {
    const double h = 1.0 / 240;
    for (double left = dt; left > 0; left -= h) {
        double s = left < h ? left : h;
        double f = (m_to - m_v) * m_stiff - m_vel * m_damp;
        m_vel += (f / (m_mass > 0 ? m_mass : 1)) * s;
        m_v += m_vel * s;
    }
    if (std::fabs(m_to - m_v) < m_restDelta && std::fabs(m_vel) < m_restSpeed) {
        m_v = m_to; m_vel = 0;
        m_drv->stop();
        setRunning(false);
        emit valueChanged();
        emit finished();
        return;
    }
    emit valueChanged();
}
