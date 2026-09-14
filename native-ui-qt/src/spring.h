// spring — la molla di framer-motion, con gli stessi parametri del JSX
// (stiffness, damping, mass), integrata a passi fissi di 1/240 s come in
// anim.c. Si usa da QML:
//     Spring { id: sp; stiffness: 200; damping: 26 }
//     sp.set(1); sp.to = 0            // parte
//     y: sp.value * height
// E' pilotata dal driver delle animazioni di Qt Quick, quindi va in
// sincrono con il vblank e si ferma da sola a riposo (nessun timer che
// gira quando non serve).
#pragma once
#include <QAbstractAnimation>
#include <QObject>
#include <qqml.h>

class Spring : public QObject {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(double value READ value NOTIFY valueChanged)
    Q_PROPERTY(double to READ to WRITE setTo NOTIFY toChanged)
    Q_PROPERTY(double stiffness MEMBER m_stiff)
    Q_PROPERTY(double damping MEMBER m_damp)
    Q_PROPERTY(double mass MEMBER m_mass)
    Q_PROPERTY(double restDelta MEMBER m_restDelta)
    Q_PROPERTY(double restSpeed MEMBER m_restSpeed)
    Q_PROPERTY(bool running READ running NOTIFY runningChanged)
public:
    explicit Spring(QObject *parent = nullptr);
    double value() const { return m_v; }
    double to() const { return m_to; }
    void setTo(double t);
    bool running() const { return m_running; }
    // Porta il valore a v senza animare.
    Q_INVOKABLE void set(double v);
    // Salta alla fine dell'animazione in corso.
    Q_INVOKABLE void finish();
    void step(double dt);
signals:
    void valueChanged();
    void toChanged();
    void runningChanged();
    void finished();
private:
    void setRunning(bool r);
    class Driver;
    Driver *m_drv;
    double m_v = 0, m_to = 0, m_vel = 0;
    double m_stiff = 200, m_damp = 26, m_mass = 1;
    double m_restDelta = 0.001, m_restSpeed = 0.05;
    bool m_running = false;
};
