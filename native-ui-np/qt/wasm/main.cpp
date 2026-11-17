// The kiosk interface of Osmium Sound, built for the browser.
//
// Same objects and the same QML as the appliance (native-ui-qt/src/main.cpp
// in the Osmium Sound repository), minus what only exists there: the DRM/KMS
// video mode, the kernel command line, the Bluetooth remote bridge, the
// touchscreen watchdog and the test channel. The files the interface reads
// (QML, icons, skins, translations) are unpacked by the page into /app before
// Qt starts (site/qt/index.html), and the services it talks to answer inside
// the page (mock/device.js), under <origin>/device/....
#include "api.h"
#include "i18n.h"
#include "library.h"
#include "player.h"
#include "remote.h"
#include "qritem.h"
#include "spring.h"
#include "sys.h"
#include "vumeter.h"
#include <QFont>
#include <QFontDatabase>
#include <QGuiApplication>
#include <QQmlContext>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickView>
#include <QtDebug>
#include <emscripten/val.h>

// Every input reaches Sys before the scene consumes it: the screensaver and
// the Now Playing auto-expand time themselves on it.
class InputWatch : public QObject {
public:
    InputWatch(Sys *s, Remote *r, QQuickView *v) : m_sys(s), m_remote(r), m_view(v) {}
protected:
    bool eventFilter(QObject *, QEvent *e) override {
        switch (e->type()) {
        case QEvent::TouchBegin: case QEvent::MouseButtonPress:
            m_sys->noteInput(); m_sys->notePointer(); break;
        case QEvent::TouchUpdate: case QEvent::MouseMove: case QEvent::Wheel:
            m_sys->noteInput(); break;
        case QEvent::KeyPress: {
            m_sys->noteInput();
            // the keyboard drives the interface like a remote does on the
            // appliance (arrows, Enter, Esc), except while typing in a field
            QKeyEvent *ke = static_cast<QKeyEvent *>(e);
            QQuickItem *f = m_view->activeFocusItem();
            const bool typing = f && (f->inherits("QQuickTextInput") || f->inherits("QQuickTextEdit"));
            const QString act = m_remote->actionForQtKey(ke->key());
            if (!act.isEmpty() && !typing) { m_remote->dispatch(act, ke->isAutoRepeat(), "qt"); return true; }
            break;
        }
        default: break;
        }
        return false;
    }
private:
    Sys *m_sys;
    Remote *m_remote;
    QQuickView *m_view;
};

int main(int argc, char *argv[]) {
    // the services live on the page's own origin (see prepare.py, api.h)
    const std::string origin = emscripten::val::global("location")["origin"].as<std::string>();
    qputenv("HIFI_HOST", QByteArray::fromStdString(origin));
    qputenv("HIFI_CONFIG_DIR", "/app/config");
    QGuiApplication app(argc, argv);
    app.setApplicationName("hifi-qt");

    const QString base = "/app";
    const QString assets = base + "/assets", locales = base + "/locales";
    for (const QString &f : {"DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSansMono.ttf"})
        QFontDatabase::addApplicationFont(base + "/fonts/" + f);
    QFont font("DejaVu Sans");
    font.setPixelSize(14);
    app.setFont(font);

    Api api;
    Sys sys(assets);
    sys.setIconDir(base + "/icons");
    sys.setForcedWizard(QString(), false);
    sys.setStartExpanded(false);
    I18n i18n(locales, sys.conf("ui-language", "en"));
    api.setLang(i18n.lang());
    QObject::connect(&i18n, &I18n::langChanged, &api, [&api, &i18n]() { api.setLang(i18n.lang()); });
    Player player;
    Remote remote(sys.configDir());
    VuMeter vu;
    LibraryModel library;
    QObject::connect(&player, &Player::connectedChanged, &library, [&]() { library.setProperty("playerId", player.playerId()); });
    QObject::connect(&player, &Player::playerChanged, &library, [&]() { library.setProperty("playerId", player.playerId()); });

    qmlRegisterType<Spring>("Hifi", 1, 0, "Spring");
    qmlRegisterType<QrItem>("Hifi", 1, 0, "QrCode");
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Theme.qml"), "Hifi.Ui", 1, 0, "Theme");
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Tr.qml"), "Hifi.Ui", 1, 0, "Tr");
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Ui.qml"), "Hifi.Ui", 1, 0, "Ui");
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Nav.qml"), "Hifi.Ui", 1, 0, "Nav");
    qmlRegisterSingletonType(QUrl::fromLocalFile(base + "/qml/Meta.qml"), "Hifi.Ui", 1, 0, "Meta");
    qmlRegisterUncreatableType<LibraryModel>("Hifi", 1, 0, "LibraryModel", "use the Library instance");

    QQuickView view;
    view.setColor(QColor("#0a0a0a"));
    view.setResizeMode(QQuickView::SizeRootObjectToView);
    QQmlContext *ctx = view.rootContext();
    ctx->setContextProperty("Api", &api);
    ctx->setContextProperty("Sys", &sys);
    ctx->setContextProperty("I18n", &i18n);
    ctx->setContextProperty("Player", &player);
    ctx->setContextProperty("Remote", &remote);
    ctx->setContextProperty("Vu", &vu);
    ctx->setContextProperty("Library", &library);
    view.engine()->addImportPath(base + "/qml");
    api.setEngine(view.engine());
    sys.setWindow(&view);
    InputWatch watch(&sys, &remote, &view);
    view.installEventFilter(&watch);

    view.setSource(QUrl::fromLocalFile(base + "/qml/Main.qml"));
    if (view.status() == QQuickView::Error) {
        for (const QQmlError &e : view.errors()) qWarning("qml: %s", qPrintable(e.toString()));
        return 1;
    }
    view.showFullScreen();
    qInfo("hifi-qt (demo): %dx%d on %s", view.width(), view.height(), qPrintable(QGuiApplication::platformName()));
    player.start();
    return app.exec();
}
