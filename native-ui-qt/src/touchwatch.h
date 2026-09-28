// touchwatch — what the touchscreen is doing, seen from the kernel's side.
//
// 🚨 Born from a report (2026-09-28, TSTP MTouch panel): now and then the
// whole screen stops answering the finger, and only unplugging its USB cable
// brings it back. The kernel logs nothing, and three different things fit:
//   1. the panel goes silent (its controller hangs: no events at all);
//   2. a "phantom finger": the kernel keeps a contact down, and every later
//      touch is taken as a second finger;
//   3. the kernel gets the touches but the interface does not (libinput/Qt).
// So the panel is read here too, alongside Qt and without taking it from
// anyone (no EVIOCGRAB): when its last event came, whether a finger is down
// and since when, how many contacts, dropped events — and when Qt last
// delivered a touch. It goes to /run/hifi-touch.json (in the support bundle)
// and, when something looks wrong, to the journal — which survives the
// unplugging the owner does before anyone can look.
#pragma once
#include <QFileSystemWatcher>
#include <QHash>
#include <QObject>
#include <QSet>
#include <QTimer>

class QSocketNotifier;

class TouchWatch : public QObject {
    Q_OBJECT
public:
    explicit TouchWatch(QObject *parent = nullptr);
    ~TouchWatch() override;
    // a touch reached the interface (the event filter in main.cpp)
    void noteQt();

private:
    struct Dev {
        QString path, name, usb;
        int fd = -1;
        QSocketNotifier *notifier = nullptr;
        qint64 openedAt = 0, lastAt = 0, downSince = 0;
        qint64 events = 0, dropped = 0;
        bool down = false;
        bool warnedStuck = false;
        int slot = 0;
        QSet<int> contacts;          // slots with a finger on them
        qint64 pendingSince = 0;     // a touch the interface has not seen yet
    };
    void rescan();
    void open(const QString &path, const QString &name, const QString &usb);
    void close(const QString &path, bool gone);
    void read(const QString &path);
    void check();
    void publish();

    QHash<QString, Dev> m_devs;
    QFileSystemWatcher m_watch;
    QTimer m_rescan, m_tick;
    qint64 m_qtLast = 0;
    bool m_dirty = true;
};
