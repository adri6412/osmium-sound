// hifi-qt — l'interfaccia dell'apparecchio in Qt Quick, dritta su DRM/KMS
// (piattaforma eglfs, nessun compositore), con la stessa tela logica
// 1024x600 della UI Electron e della UI in C.
//
//   --assets DIR      cartella degli asset (default: accanto al binario)
//   --locales DIR     cartella con en.json/it.json
//   --expanded        parte col player espanso
//   --wizard setup|install   forza una delle due schermate iniziali (sviluppo)
//
// Variabili d'ambiente:
//   HIFI_HOST         host dei servizi (default 127.0.0.1)
//   HIFI_CONFIG_DIR   cartella dei file di configurazione (default /etc/hifi-player)
//   HIFI_DEV          abilita il canale di collaudo /tmp/hifi-qt.cmd
//   QT_QPA_PLATFORM   eglfs sull'apparecchio; xcb/offscreen in sviluppo
#include "api.h"
#include "i18n.h"
#include "library.h"
#include "player.h"
#include "kmsmode.h"
#include "qritem.h"
#include "spring.h"
#include "sys.h"
#include "vumeter.h"
#include <QFile>
#include <QFont>
#include <QFontDatabase>
#include <QGuiApplication>
#include <QMouseEvent>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQmlExpression>
#include <QQuickItem>
#include <QQuickView>
#include <QScreen>
#include <QTimer>
#include <QWheelEvent>
#include <QWindow>
#include <QtDebug>
#include <cstdio>
#include <signal.h>

static QQuickView *g_view = nullptr;

// Segnala a Sys ogni evento di input, prima che lo consumi la scena.
class InputWatch : public QObject {
public:
    explicit InputWatch(Sys *s) : m_sys(s) {}
protected:
    bool eventFilter(QObject *, QEvent *e) override {
        switch (e->type()) {
        case QEvent::MouseButtonPress: case QEvent::MouseMove: case QEvent::Wheel:
        case QEvent::TouchBegin: case QEvent::TouchUpdate:
            m_sys->noteInput(); break;
        case QEvent::KeyPress: {
            m_sys->noteInput();
            // solo le lettere: i tasti di un telecomando a infrarossi (cifre,
            // frecce, invio) non sono "qualcuno sta scrivendo su una tastiera"
            const int k = static_cast<QKeyEvent *>(e)->key();
            if (k >= Qt::Key_A && k <= Qt::Key_Z) m_sys->noteRealKey();
            break;
        }
        default: break;
        }
        return false;
    }
private:
    Sys *m_sys;
};
static volatile sig_atomic_t g_shot = 0;
static void onUsr1(int) { g_shot = 1; }
// systemctl stop manda SIGTERM: uscita pulita dal ciclo degli eventi, non un
// processo "ucciso" (che systemd segna come fallito)
static void onTerm(int) { QCoreApplication::exit(0); }

static QPointF canvasToWin(double x, double y) {
    QQuickItem *root = g_view->rootObject();
    double s = root->property("s").toDouble();
    double ox = root->property("ox").toDouble(), oy = root->property("oy").toDouble();
    return QPointF(ox + x * s, oy + y * s);
}

static void mouse(QEvent::Type t, QPointF p, Qt::MouseButton b = Qt::LeftButton) {
    QMouseEvent ev(t, p, p, g_view->mapToGlobal(p.toPoint()), b, t == QEvent::MouseButtonRelease ? Qt::NoButton : Qt::LeftButton, Qt::NoModifier);
    QCoreApplication::sendEvent(g_view, &ev);
}

static void keyPress(int key, const QString &text = QString()) {
    QKeyEvent d(QEvent::KeyPress, key, Qt::NoModifier, text);
    QKeyEvent u(QEvent::KeyRelease, key, Qt::NoModifier, text);
    QCoreApplication::sendEvent(g_view, &d);
    QCoreApplication::sendEvent(g_view, &u);
}

// Collaudo da remoto: /tmp/hifi-qt.cmd, una riga per comando (coordinate
// della tela 1024x600). Il file viene consumato e cancellato.
//   tap X Y | hold X Y | move X Y | release X Y | scroll X Y DY
//   type testo | key esc|enter|backspace|left|right|up|down
//   shot [file] | eval <javascript nel contesto della radice> | quit
static void cmdfilePoll() {
    QFile f("/tmp/hifi-qt.cmd");
    if (!f.exists() || !f.open(QIODevice::ReadOnly | QIODevice::Text)) return;
    QList<QByteArray> lines = f.readAll().split('\n');
    f.close();
    QFile::remove("/tmp/hifi-qt.cmd");
    for (QByteArray l : lines) {
        QString line = QString::fromUtf8(l).trimmed();
        if (line.isEmpty()) continue;
        QStringList a = line.split(' ', Qt::SkipEmptyParts);
        const QString c = a[0];
        if ((c == "tap" || c == "hold" || c == "move" || c == "release") && a.size() >= 3) {
            QPointF p = canvasToWin(a[1].toDouble(), a[2].toDouble());
            if (c == "tap") { mouse(QEvent::MouseButtonPress, p); mouse(QEvent::MouseButtonRelease, p); }
            else if (c == "hold") mouse(QEvent::MouseButtonPress, p);
            else if (c == "move") mouse(QEvent::MouseMove, p);
            else mouse(QEvent::MouseButtonRelease, p);
        } else if (c == "scroll" && a.size() >= 4) {
            QPointF p = canvasToWin(a[1].toDouble(), a[2].toDouble());
            double dy = a[3].toDouble();
            QWheelEvent ev(p, g_view->mapToGlobal(p.toPoint()), QPoint(), QPoint(0, (int)(-dy * 120 / 100)), Qt::NoButton, Qt::NoModifier, Qt::NoScrollPhase, false);
            QCoreApplication::sendEvent(g_view, &ev);
        } else if (c == "type") {
            QString text = line.mid(5);
            for (QChar ch : text) keyPress(0, QString(ch));
        } else if (c == "key" && a.size() >= 2) {
            static const QHash<QString, int> keys = {{"esc", Qt::Key_Escape}, {"enter", Qt::Key_Return}, {"backspace", Qt::Key_Backspace},
                                                     {"left", Qt::Key_Left}, {"right", Qt::Key_Right}, {"up", Qt::Key_Up}, {"down", Qt::Key_Down}, {"tab", Qt::Key_Tab}};
            if (keys.contains(a[1])) keyPress(keys[a[1]]);
        } else if (c == "shot") {
            QString path = a.size() >= 2 ? a[1] : "/tmp/hifi-qt.png";
            // dopo che gli eventi appena iniettati sono stati disegnati
            QTimer::singleShot(150, [path]() { QImage img = g_view->grabWindow(); img.save(path); qInfo("shot: %s", qPrintable(path)); });
        } else if (c == "eval") {
            QQmlExpression e(g_view->rootContext(), g_view->rootObject(), line.mid(5));
            QVariant r = e.evaluate();
            if (e.hasError()) qWarning("eval: %s", qPrintable(e.error().toString()));
            else qInfo("eval: %s", qPrintable(r.toString()));
            QFile out("/tmp/hifi-qt.out");
            if (out.open(QIODevice::WriteOnly | QIODevice::Text)) out.write((e.hasError() ? "ERR " + e.error().toString() : r.toString()).toUtf8() + "\n");
        } else if (c == "quit") {
            QCoreApplication::quit();
        }
    }
}

int main(int argc, char *argv[]) {
    if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM")) qputenv("QT_QPA_PLATFORM", "eglfs");
    // Modo video da /etc/hifi-player/ui-resolution, prima che eglfs apra il DRM.
    if (qEnvironmentVariable("QT_QPA_PLATFORM") == "eglfs" && qEnvironmentVariableIsEmpty("QT_QPA_EGLFS_KMS_CONFIG")) {
        QString cdir = qEnvironmentVariable("HIFI_CONFIG_DIR");
        if (cdir.isEmpty()) cdir = "/etc/hifi-player";
        QFile rf(cdir + "/ui-resolution");
        QString pref = "auto";
        if (rf.open(QIODevice::ReadOnly)) pref = QString::fromUtf8(rf.readLine()).trimmed();
        QString cfg = kmsConfigFor(pref.isEmpty() ? "auto" : pref);
        if (!cfg.isEmpty()) { qputenv("QT_QPA_EGLFS_KMS_CONFIG", cfg.toUtf8()); qputenv("QT_QPA_EGLFS_ALWAYS_SET_MODE", "1"); }
    }
    QGuiApplication app(argc, argv);
    app.setApplicationName("hifi-qt");

    const QString base = QCoreApplication::applicationDirPath();
    QString assets = base + "/assets", locales = base + "/locales", wizard;
    bool expanded = false;
    QStringList args = app.arguments();
    for (int i = 1; i < args.size(); i++) {
        if (args[i] == "--assets" && i + 1 < args.size()) assets = args[++i];
        else if (args[i] == "--locales" && i + 1 < args.size()) locales = args[++i];
        else if (args[i] == "--expanded") expanded = true;
        else if (args[i] == "--wizard" && i + 1 < args.size()) wizard = args[++i];
    }

    // Il carattere dell'apparecchio: DejaVu Sans (il body stack di Electron
    // sul dispositivo si risolve li').
    QFont font("DejaVu Sans");
    font.setPixelSize(14);
    app.setFont(font);

    Api api;
    Sys sys(assets);
    sys.setIconDir(base + "/icons");
    sys.setForcedWizard(wizard);
    sys.setStartExpanded(expanded);
    I18n i18n(locales, sys.conf("ui-language", "en"));
    Player player;
    VuMeter vu;
    LibraryModel library;
    QObject::connect(&player, &Player::connectedChanged, &library, [&]() { library.setProperty("playerId", player.playerId()); });

    qmlRegisterType<Spring>("Hifi", 1, 0, "Spring");
    qmlRegisterType<QrItem>("Hifi", 1, 0, "QrCode");
    // singleton QML (tinte, traduzioni, agganci), senza qmldir
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Theme.qml"), "Hifi.Ui", 1, 0, "Theme");
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Tr.qml"), "Hifi.Ui", 1, 0, "Tr");
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Ui.qml"), "Hifi.Ui", 1, 0, "Ui");
    qmlRegisterUncreatableType<LibraryModel>("Hifi", 1, 0, "LibraryModel", "usare l'istanza Library");

    QQuickView view;
    g_view = &view;
    view.setColor(QColor("#0a0a0a"));
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    QQmlContext *ctx = view.rootContext();
    ctx->setContextProperty("Api", &api);
    ctx->setContextProperty("Sys", &sys);
    ctx->setContextProperty("I18n", &i18n);
    ctx->setContextProperty("Player", &player);
    ctx->setContextProperty("Vu", &vu);
    ctx->setContextProperty("Library", &library);
    view.engine()->addImportPath(base + "/qml");
    api.setEngine(view.engine());
    sys.setWindow(&view);
    InputWatch watch(&sys);
    view.installEventFilter(&watch);
    if (!sys.pointerEnabled()) QGuiApplication::setOverrideCursor(QCursor(Qt::BlankCursor));

    view.setSource(QUrl::fromLocalFile(base + "/qml/Main.qml"));
    if (view.status() == QQuickView::Error) {
        for (const QQmlError &e : view.errors()) fprintf(stderr, "qml: %s\n", qPrintable(e.toString()));
        return 1;
    }
    if (qEnvironmentVariableIsSet("HIFI_WINDOW")) {           // sviluppo: finestra normale
        QStringList wh = qEnvironmentVariable("HIFI_WINDOW").split('x');
        view.resize(wh.value(0, "1280").toInt(), wh.value(1, "720").toInt());
        view.show();
    } else view.showFullScreen();
    qInfo("hifi-qt: %dx%d su %s", view.width(), view.height(), qPrintable(QGuiApplication::platformName()));
    player.start();

    signal(SIGUSR1, onUsr1);
    signal(SIGTERM, onTerm);
    signal(SIGINT, onTerm);
    // collaudo: quanti fotogrammi al secondo disegna la scena (a riposo deve essere ~0)
    static int frames = 0;
    QObject::connect(&view, &QQuickWindow::frameSwapped, [&]() { frames++; });
    QTimer fpsLog;
    if (sys.devMode()) {
        QObject::connect(&fpsLog, &QTimer::timeout, [&]() { qInfo("fps: %.1f", frames / 5.0); frames = 0; });
        fpsLog.start(5000);
    }
    QTimer poll;
    QObject::connect(&poll, &QTimer::timeout, [&]() {
        if (g_shot) { g_shot = 0; sys.shot("/tmp/hifi-qt.png"); }
        if (sys.devMode()) cmdfilePoll();
    });
    poll.start(200);

    bool ok = false;
    int secs = qEnvironmentVariableIntValue("HIFI_QT_SECONDS", &ok);
    if (ok && secs > 0) QTimer::singleShot(secs * 1000, &app, &QGuiApplication::quit);
    return app.exec();
}
