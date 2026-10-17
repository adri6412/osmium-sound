// kmsplan_test — what kmsPlan() decides for one or more monitors, without a
// DRM device: `make test` (builds next to hifi-qt, same flags).
#include "kmsmode.h"
#include <QJsonArray>
#include <QJsonDocument>
#include <cstdio>

static int failures = 0;
static void expect(const char *what, const QString &got, const QString &want) {
    if (got == want) return;
    failures++;
    std::printf("FAIL %s\n  got:  %s\n  want: %s\n", what, qPrintable(got), qPrintable(want));
}
static QString js(const QJsonObject &o) { return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact)); }

static KmsMode M(int w, int h, int hz, bool pref = false) { KmsMode m; m.w = w; m.h = h; m.hz = hz; m.preferred = pref; return m; }
// a 1080p PC monitor without 720p (common), a TV with everything, a 1024x600
// touch panel, a 16:10 monitor
static KmsOutput pcMonitor(const QString &n) { return { n, { M(1920, 1080, 60, true), M(1680, 1050, 60), M(1280, 1024, 60), M(1024, 768, 60) } }; }
static KmsOutput tv(const QString &n) { return { n, { M(3840, 2160, 30), M(1920, 1080, 60, true), M(1920, 1080, 50), M(1280, 720, 60), M(1280, 720, 50) } }; }
static KmsOutput panel7(const QString &n) { return { n, { M(1024, 600, 60, true) } }; }
static KmsOutput wide(const QString &n) { return { n, { M(1920, 1200, 60, true), M(1920, 1080, 60), M(1280, 720, 60), M(1280, 800, 60) } }; }

int main() {
    const QString D = "\"device\":\"/dev/dri/card0\"";

    // one monitor: as before — nothing when it stays native, the capped mode otherwise
    expect("one monitor, native", js(kmsPlan({ tv("HDMI1") }, "native", "mirror")), "{}");
    expect("one monitor, auto caps a TV to 720p", js(kmsPlan({ tv("HDMI1") }, "auto", "mirror")),
           "{" + D + ",\"outputs\":[{\"mode\":\"1280x720@60\",\"name\":\"HDMI1\"}]}");
    expect("one monitor already at its own size", js(kmsPlan({ panel7("DSI1") }, "auto", "mirror")), "{}");
    expect("no monitor", js(kmsPlan({}, "auto", "mirror")), "{}");

    // duplicate: the first is the source, the others clone it at one common size
    expect("duplicate, TV + 16:10 monitor at 720p",
           js(kmsPlan({ tv("HDMI1"), wide("DP1") }, "auto", "mirror")),
           "{" + D + ",\"hwcursor\":false,\"outputs\":[{\"mode\":\"1280x720@60\",\"name\":\"HDMI1\",\"primary\":true},"
           "{\"clones\":\"HDMI1\",\"mode\":\"1280x720@60\",\"name\":\"DP1\"}]}");
    expect("duplicate, native: the first one's own size when the other has it",
           js(kmsPlan({ tv("HDMI1"), wide("DP1") }, "native", "mirror")),
           "{" + D + ",\"hwcursor\":false,\"outputs\":[{\"mode\":\"1920x1080@60\",\"name\":\"HDMI1\",\"primary\":true},"
           "{\"clones\":\"HDMI1\",\"mode\":\"1920x1080@60\",\"name\":\"DP1\"}]}");
    expect("duplicate, cap 720 but no 720p in common: the smallest above",
           js(kmsPlan({ pcMonitor("DP1"), tv("HDMI1") }, "auto", "mirror")),
           "{" + D + ",\"hwcursor\":false,\"outputs\":[{\"mode\":\"1920x1080@60\",\"name\":\"DP1\",\"primary\":true},"
           "{\"clones\":\"DP1\",\"mode\":\"1920x1080@60\",\"name\":\"HDMI1\"}]}");
    expect("duplicate on three",
           js(kmsPlan({ tv("HDMI1"), wide("DP1"), tv("HDMI2") }, "auto", "mirror")),
           "{" + D + ",\"hwcursor\":false,\"outputs\":[{\"mode\":\"1280x720@60\",\"name\":\"HDMI1\",\"primary\":true},"
           "{\"clones\":\"HDMI1\",\"mode\":\"1280x720@60\",\"name\":\"DP1\"},{\"clones\":\"HDMI1\",\"mode\":\"1280x720@60\",\"name\":\"HDMI2\"}]}");
    expect("duplicate with nothing in common: only the first, the rest off",
           js(kmsPlan({ panel7("DSI1"), pcMonitor("HDMI1") }, "auto", "mirror")),
           "{" + D + ",\"outputs\":[{\"mode\":\"preferred\",\"name\":\"DSI1\",\"primary\":true},{\"mode\":\"off\",\"name\":\"HDMI1\"}]}");

    // only on one: that one on (with the usual cap), the others off
    expect("only on the second",
           js(kmsPlan({ tv("HDMI1"), wide("DP1") }, "auto", "only:DP1")),
           "{" + D + ",\"outputs\":[{\"mode\":\"off\",\"name\":\"HDMI1\"},{\"mode\":\"1280x800@60\",\"name\":\"DP1\",\"primary\":true}]}");
    expect("only on one, native",
           js(kmsPlan({ tv("HDMI1"), wide("DP1") }, "native", "only:HDMI1")),
           "{" + D + ",\"outputs\":[{\"mode\":\"preferred\",\"name\":\"HDMI1\",\"primary\":true},{\"mode\":\"off\",\"name\":\"DP1\"}]}");
    expect("only on a monitor that is gone: duplicate",
           js(kmsPlan({ tv("HDMI1"), wide("DP1") }, "auto", "only:HDMI2")),
           js(kmsPlan({ tv("HDMI1"), wide("DP1") }, "auto", "mirror")));

    // Qt's names, or the configuration is silently ignored
    expect("HDMI-A", kmsOutputName(11, 1), "HDMI1");
    expect("HDMI-B", kmsOutputName(12, 2), "HDMI2");
    expect("DVI-I", kmsOutputName(2, 1), "DVI1");
    expect("DVI-D", kmsOutputName(3, 2), "DVI2");
    expect("DP", kmsOutputName(10, 3), "DP3");
    expect("eDP", kmsOutputName(14, 1), "eDP1");
    expect("DPI and later", kmsOutputName(17, 1), "UNKNOWN1");

    std::printf("kmsplan_test: %s\n", failures ? "FAILED" : "ok");
    return failures ? 1 : 0;
}
