#include "player.h"
#include "api.h"
#include <QJSEngine>
#include <QQmlEngine>
#include <QUrl>
#include <QtDebug>
#include <cmath>

Player::Player(QObject *parent) : QObject(parent) {
    m_clock.start();
    m_tick.setInterval(100);
    connect(&m_tick, &QTimer::timeout, this, [this]() {
        qint64 now = m_clock.elapsed();
        if (!m_connected && now - m_lastStatus >= 2000) { m_lastStatus = now; findPlayer(); }
        else if (m_connected && !m_statusInFlight && (m_wantNow || now - m_lastStatus >= 1000)) { m_wantNow = false; m_lastStatus = now; pollStatus(); }
        if (m_connected && now - m_lastPrefs >= 5000) { m_lastPrefs = now; pollPrefs(); }
        if (now - m_lastSettings >= 5000) { m_lastSettings = now; pollSettings(); }
        if (now - m_lastUsb >= 4000) { m_lastUsb = now; pollUsb(); }
        if (now - m_lastOta >= 3000) { m_lastOta = now; pollOta(); }
        // l'avanzamento scorre in locale fra un poll e l'altro (app.c)
        if (m_playing && m_duration > 0 && now - m_lastElapsedTick >= 500) {
            m_lastElapsedTick = now;
            m_elapsed += 0.5;
            if (m_elapsed > m_duration) m_elapsed = m_duration;
            emit progressChanged();
        }
        flushVolume();
    });
}

void Player::start() {
    connect(Api::instance(), &Api::lmsBaseChanged, this, &Player::onLmsHostChanged);
    fetchLocalName();
    findPlayer();
    pollSettings();
    pollUsb();
    pollOta();
    m_lastSettings = m_lastUsb = m_lastOta = m_clock.elapsed();
    m_tick.start();
}

void Player::callJs(QJSValue cb, const QVariantList &args) {
    if (!cb.isCallable()) return;
    QJSEngine *eng = Api::instance()->engine();
    QJSValueList a;
    for (const QVariant &v : args) a << (eng ? eng->toScriptValue(v) : QJSValue(v.toString()));
    QJSValue r = cb.call(a);
    if (r.isError()) qWarning("player: errore nella callback: %s", qPrintable(r.toString()));
}

// ─── player locale ─────────────────────────────────────────────────────────
void Player::findPlayer() {
    Api::instance()->lmsRequest("", {"players", "0", "20"}, [this](bool ok, const QVariant &data, int) {
        if (!ok) { if (m_connected) { m_connected = false; emit connectedChanged(); } return; }
        QVariantList loop = data.toMap().value("result").toMap().value("players_loop").toList();
        QString id, name;
        // 🚨 Ci si riconosce dal NOME (quello dato a squeezelite con -n), come fa
        // il kiosk Electron. L'indirizzo di partenza non basta: se l'apparecchio
        // segue il Lyrion di un altro, il nostro squeezelite non arriva piu' da
        // loopback ma dalla rete, e si finiva col pilotare il lettore altrui —
        // now playing, copertine e liste erano di un altro apparecchio.
        if (!m_localName.isEmpty()) {
            for (const QVariant &p : loop) {
                QVariantMap m = p.toMap();
                if (m.value("name").toString() == m_localName && !m.value("playerid").toString().isEmpty()) {
                    id = m.value("playerid").toString(); name = m.value("name").toString(); break;
                }
            }
        }
        for (const QVariant &p : loop) {                       // ripiego: squeezelite locale, ip su loopback
            if (!id.isEmpty()) break;
            QVariantMap m = p.toMap();
            if (m.value("ip").toString().startsWith("127.0.0.1") && !m.value("playerid").toString().isEmpty()) {
                id = m.value("playerid").toString(); name = m.value("name").toString(); break;
            }
        }
        if (id.isEmpty() && !loop.isEmpty()) {
            QVariantMap m = loop.first().toMap();
            id = m.value("playerid").toString(); name = m.value("name").toString();
        }
        if (id.isEmpty()) { if (m_connected) { m_connected = false; emit connectedChanged(); } return; }
        bool was = m_connected;
        m_playerId = id; m_playerName = name.isEmpty() ? id : name;
        m_connected = true;
        if (!was) { emit connectedChanged(); pollPrefs(); m_wantNow = true; }
    }, 4000);
}

// Il nome che questo apparecchio ha su Lyrion: lo tiene l'api_server (e' il -n
// passato a squeezelite). Serve a riconoscere il PROPRIO lettore in un elenco
// che, su un server condiviso, contiene anche quelli degli altri.
void Player::fetchLocalName() {
    Api *api = Api::instance();
    api->request("GET", api->apiBase() + "/player_name", {}, [this](bool ok, const QVariant &d, int) {
        if (!ok) return;
        const QString n = d.toMap().value("name").toString();
        if (n.isEmpty() || n == m_localName) return;
        m_localName = n;
        findPlayer();
    }, 5000);
}

// L'apparecchio ha cambiato Lyrion (proprio ↔ quello di un altro): il lettore
// va ritrovato la' dentro, e l'indirizzo della copertina rifatto da capo —
// updateArtwork() salta il lavoro se la "chiave" non cambia, e la chiave non
// contiene l'host.
void Player::onLmsHostChanged() {
    m_playerId.clear();
    m_artKey.clear();
    if (m_connected) { m_connected = false; emit connectedChanged(); }
    m_wantNow = true;
    fetchLocalName();
    findPlayer();
}

static QString S(const QVariantMap &m, const char *k) { return m.value(k).toString(); }

void Player::pollStatus() {
    m_statusInFlight = true;
    Api::instance()->lmsRequest(m_playerId, {"status", "-", "1", "tags:aldoTINxcK"}, [this](bool ok, const QVariant &data, int) {
        m_statusInFlight = false;
        QVariantMap r = data.toMap().value("result").toMap();
        if (!ok || r.isEmpty()) {
            if (m_connected) { m_connected = false; emit connectedChanged(); }
            return;
        }
        if (!m_connected) { m_connected = true; emit connectedChanged(); }
        bool playing = S(r, "mode") == "play";
        double elapsed = r.value("time").toDouble(), duration = r.value("duration").toDouble();
        int volume = r.value("mixer volume").toInt(), index = r.value("playlist_cur_index").toInt();
        int total = r.value("playlist_tracks").toInt(), repeat = r.value("playlist repeat").toInt();
        int shuffle = r.value("playlist shuffle").toInt(), sleep = r.value("will_sleep_in").toInt();
        QString currentTitle = S(r, "current_title");
        QVariantList pl = r.value("playlist_loop").toList();
        QVariantMap tr = pl.isEmpty() ? QVariantMap() : pl.first().toMap();
        QString title = S(tr, "title"), artist = S(tr, "artist"), album = S(tr, "album");
        QString coverid = S(tr, "coverid"), aurl = S(tr, "artwork_url"), bitrate = S(tr, "bitrate");
        QString type = S(tr, "type"), id = S(tr, "id");
        int ssize = tr.value("samplesize").toInt();
        double srate = tr.value("samplerate").toDouble();
        bool remote = tr.value("remote").toInt() != 0;
        if (duration == 0) duration = tr.value("duration").toDouble();
        if (remote && artist.isEmpty()) {                 // "Artista - Titolo" nel solo title
            int sep = title.indexOf(" - ");
            if (sep > 0) { artist = title.left(sep); title = title.mid(sep + 3); }
        }

        bool meta = title != m_title || artist != m_artist || album != m_album || type != m_type ||
                    ssize != m_sampleSize || srate != m_sampleRate || id != m_id || coverid != m_coverId ||
                    remote != m_remote || bitrate != m_bitrate;
        bool track = title != m_title || artist != m_artist || album != m_album;
        bool prog = std::fabs(elapsed - m_elapsed) > 0.4 || std::fabs(duration - m_duration) > 0.4;
        bool ctl = playing != m_playing || volume != m_volume || shuffle != m_shuffle || repeat != m_repeat ||
                   sleep != m_sleepSecs || index != m_index || total != m_total;
        m_title = title; m_artist = artist; m_album = album; m_type = type; m_sampleSize = ssize; m_sampleRate = srate;
        m_id = id; m_coverId = coverid; m_artworkUrlLms = aurl; m_remote = remote; m_bitrate = bitrate; m_currentTitle = currentTitle;
        m_elapsed = elapsed; m_duration = duration;
        m_playing = playing; m_volume = volume; m_shuffle = shuffle; m_repeat = repeat; m_sleepSecs = sleep; m_index = index; m_total = total;
        m_lastElapsedTick = m_clock.elapsed();
        if (meta) { derive(); emit metaChanged(); }
        if (prog) emit progressChanged();
        if (ctl) { derive(); emit controlsChanged(); }
        if (track) emit trackChanged();
        updateArtwork();
    }, 8000);
}

void Player::pollPrefs() {
    static const char *names[4] = {"replayGainMode", "transitionType", "transitionDuration", "digitalVolumeControl"};
    for (int i = 0; i < 4; i++) {
        QString name = names[i];
        Api::instance()->lmsRequest(m_playerId, {"playerpref", name, "?"}, [this, i](bool ok, const QVariant &data, int) {
            if (!ok) return;
            QVariant v = data.toMap().value("result").toMap().value("_p2");
            if (!v.isValid()) return;
            QString s = v.toString();
            QString *dst = i == 0 ? &m_prefRg : i == 1 ? &m_prefTrType : i == 2 ? &m_prefTrDur : &m_prefDigVol;
            if (*dst == s) return;
            *dst = s;
            derive();
            emit modeChanged();
        }, 4000);
    }
}

void Player::refreshPrefs() { if (m_connected) pollPrefs(); }

void Player::pollSettings() {
    Api *a = Api::instance();
    a->request("GET", a->apiBase() + "/nowplaying_autoexpand", {}, [this](bool ok, const QVariant &d, int) {
        if (!ok || d.typeId() != QMetaType::QVariantMap) return;
        int v = d.toMap().value("seconds").toInt();
        if (v != m_autoexpand) { m_autoexpand = v; emit settingsChanged(); }
    }, 3000);
    a->request("GET", a->apiBase() + "/vu_meter", {}, [this](bool ok, const QVariant &d, int) {
        if (!ok || d.typeId() != QMetaType::QVariantMap) return;
        bool v = d.toMap().value("enabled", true).toBool();
        if (v != m_vuEnabled) { m_vuEnabled = v; emit settingsChanged(); }
    }, 3000);
}
void Player::refreshSettings() { pollSettings(); }

void Player::setVuEnabled(bool on) {
    if (m_vuEnabled == on) return;
    m_vuEnabled = on;
    emit settingsChanged();
}

// Chiavette USB comparse dopo il primo giro (App.jsx / poller.c)
void Player::pollUsb() {
    Api *a = Api::instance();
    a->request("GET", a->srcBase() + "/api/sources", {}, [this](bool ok, const QVariant &d, int) {
        if (!ok || d.typeId() != QMetaType::QVariantMap) return;
        QStringList ids;
        QString fresh;
        for (const QVariant &v : d.toMap().value("sources").toList()) {
            QVariantMap s = v.toMap();
            if (s.value("type").toString() != "usb") continue;
            QString id = s.value("id").toString();
            if (id.isEmpty()) continue;
            ids << id;
            if (m_usbBaseline && fresh.isEmpty() && !m_usbSeen.contains(id)) {
                fresh = s.value("name").toString();
                if (fresh.isEmpty()) fresh = s.value("label").toString();
                if (fresh.isEmpty()) fresh = "USB";
            }
        }
        m_usbBaseline = true;
        m_usbSeen = ids;
        if (!fresh.isEmpty()) emit usbMounted(fresh);
    }, 4000);
}

void Player::pollOta() {
    Api *a = Api::instance();
    a->request("GET", a->apiBase() + "/update/status", {}, [this](bool ok, const QVariant &d, int) {
        if (!ok || d.typeId() != QMetaType::QVariantMap) return;
        QVariantMap m = d.toMap();
        QString st = m.value("state", "idle").toString(), msg = m.value("message").toString(), kind = m.value("kind").toString();
        int pct = m.value("percent").toInt();
        if (st == m_otaState && msg == m_otaMsg && kind == m_otaKind && pct == m_otaPct) return;
        m_otaState = st; m_otaMsg = msg; m_otaKind = kind; m_otaPct = pct;
        emit otaChanged();
    }, 4000);
}

// ─── stato derivato (useLyrionPlayer.js / app.c derive()) ──────────────────
void Player::derive() {
    QString t = m_type.toLower();
    bool isDsd = t == "dsf" || t == "dsd";
    bool hiresPcm = !isDsd && (m_sampleRate > 44100 || m_sampleSize > 16);
    if (!m_type.isEmpty()) { m_qPcm = !isDsd; m_qHires = isDsd || hiresPcm; m_qDsd = isDsd; }
    else m_qPcm = m_qHires = m_qDsd = false;

    bool rg = m_prefRg != "0";
    bool dva = m_prefDigVol == "1";
    bool fixed = m_prefDigVol == "0";
    bool trn = m_prefTrType != "0" && m_prefTrDur.toDouble() > 0;
    bool bit = m_playing && !rg && !dva && !trn;
    int mode = !m_playing ? 0 : rg ? 2 : (bit ? 1 : 0);
    if (mode != m_ledMode || fixed != m_volumeFixed) { m_ledMode = mode; m_volumeFixed = fixed; emit modeChanged(); }

    if (!m_type.isEmpty()) {
        QString c = m_type.toUpper();
        if (m_sampleSize) c += QString(" · %1bit").arg(m_sampleSize);
        if (m_sampleRate > 0) c += QString(" · %1kHz").arg((int)(m_sampleRate / 1000.0 + 0.5));
        m_chip = c;
    } else m_chip.clear();
}

void Player::setCoverPx(int px) {
    px = qBound(300, px, 2000);
    if (px == m_coverPx) return;
    m_coverPx = px;
    emit coverPxChanged();
    // la chiave contiene solo il brano: la misura e' cambiata sotto, quindi va
    // buttata a mano o l'immagine resterebbe quella piccola fino al brano dopo
    m_artKey.clear();
    updateArtwork();
}

void Player::updateArtwork() {
    // stessa chiave di app.c: per le radio l'immagine puo' cambiare col brano
    QString key = QString("%1|%2|%3|%4|%5").arg(m_id.left(30), m_coverId, QString::number(m_remote),
                                              m_remote ? m_currentTitle.left(60) : QString(),
                                              QString::number(m_remote ? (int)(m_elapsed / 10) : 0));
    if (key == m_artKey) return;
    m_artKey = key;
    QString url;
    if (m_remote) {
        url = Api::instance()->lmsBase() + "/music/current/cover.jpg?player=" +
              QString::fromLatin1(QUrl::toPercentEncoding(m_playerId)) +
              "&size=" + QString::number(m_coverPx) + "&k=" +
              QString::number(qHash(key));
    } else if (!m_id.isEmpty()) {
        // 🚨 come il kiosk Electron: `/music/<id del brano>/cover?size=N`, con
        // coverid solo come marcatore per la cache. La forma
        // `cover_<W>x<H>_o.jpg` lasciava nere le copertine che Lyrion non sa
        // ridimensionare in quel modo.
        url = Api::instance()->lmsBase() + "/music/" + m_id + "/cover?size=" + QString::number(m_coverPx);
        if (!m_coverId.isEmpty()) url += "&coverid=" + QString::fromLatin1(QUrl::toPercentEncoding(m_coverId));
    }
    if (url != m_artworkUrl) { m_artworkUrl = url; emit artworkChanged(); }
}

// ─── comandi ───────────────────────────────────────────────────────────────
void Player::cmd(const QVariantList &params) {
    if (m_playerId.isEmpty()) return;
    // (gli array QML si convertono da soli in QVariantList: qui basta l'id)
    Api::instance()->lmsRequest(m_playerId, params, [this](bool, const QVariant &, int) { m_wantNow = true; }, 8000);
}
void Player::refresh() { m_wantNow = true; }

void Player::play(bool on) {
    cmd(on ? QVariantList{"play"} : QVariantList{"pause", "1"});
    if (m_playing != on) { m_playing = on; derive(); emit controlsChanged(); }
}
void Player::togglePlay() { play(!m_playing); }
void Player::next() { cmd({"playlist", "index", "+1"}); }
void Player::prev() { cmd({"playlist", "index", "-1"}); }
void Player::seek(double s) {
    if (s < 0) s = 0;
    cmd({"time", QString::number(s, 'f', 1)});
    m_elapsed = s;
    emit progressChanged();
}
void Player::seekFraction(double f) {
    if (m_duration <= 0) return;
    seek(m_duration * qBound(0.0, f, 1.0));
}
void Player::setVolume(int v, bool final) {
    if (m_volumeFixed) return;
    v = qBound(0, v, 100);
    if (v != m_volume) { m_volume = v; emit controlsChanged(); }
    qint64 now = m_clock.elapsed();
    if (final || now - m_volSentMs >= 120) { cmd({"mixer", "volume", QString::number(v)}); m_volSentMs = now; m_volPending = -1; }
    else m_volPending = v;
}
void Player::flushVolume() {
    if (m_volPending >= 0 && m_clock.elapsed() - m_volSentMs >= 120) {
        cmd({"mixer", "volume", QString::number(m_volPending)});
        m_volSentMs = m_clock.elapsed();
        m_volPending = -1;
    }
}
void Player::toggleMute() {
    // toggleMute in useLyrionPlayer.js: 0 -> 50, altrimenti -> 0
    if (m_volumeFixed) return;
    setVolume(m_volume > 0 ? 0 : 50, true);
}
void Player::setShuffle(int m) { m_shuffle = m; cmd({"playlist", "shuffle", QString::number(m)}); emit controlsChanged(); }
void Player::setRepeat(int m)  { m_repeat = m;  cmd({"playlist", "repeat", QString::number(m)});  emit controlsChanged(); }
void Player::cycleShuffle() { setShuffle((m_shuffle + 1) % 3); }
void Player::cycleRepeat()  { setRepeat((m_repeat + 1) % 3); }
void Player::setSleep(int s) {
    if (s < 0) s = 0;
    m_sleepSecs = s;
    cmd({"sleep", QString::number(s)});
    emit controlsChanged();
}

void Player::query(const QVariantList &params, const QJSValue &cb) {
    QJSValue f = cb;
    Api::instance()->lmsRequest(m_playerId, params, [this, f](bool ok, const QVariant &data, int) mutable {
        callJs(f, {ok, data.toMap().value("result")});
    }, 15000);
}
void Player::queryServer(const QVariantList &params, const QJSValue &cb) {
    QJSValue f = cb;
    Api::instance()->lmsRequest("", params, [this, f](bool ok, const QVariant &data, int) mutable {
        callJs(f, {ok, data.toMap().value("result")});
    }, 15000);
}

// Toglie i tag HTML e decodifica le entita' piu' comuni (lms.c strip_html)
static QString stripHtml(const QString &in) {
    QString out;
    out.reserve(in.size());
    for (int i = 0; i < in.size();) {
        QChar c = in[i];
        if (c == '<') {
            int e = in.indexOf('>', i);
            if (e < 0) break;
            QString tag = in.mid(i, e - i + 1).toLower();
            if (tag.startsWith("<br") || tag.startsWith("</p") || tag.startsWith("</div")) out += '\n';
            i = e + 1;
        } else if (c == '&') {
            static const struct { const char *e; const char *r; } ents[] = {
                {"&amp;", "&"}, {"&lt;", "<"}, {"&gt;", ">"}, {"&quot;", "\""}, {"&#39;", "'"}, {"&apos;", "'"}, {"&nbsp;", " "}};
            bool hit = false;
            for (const auto &en : ents) if (in.mid(i).startsWith(QLatin1String(en.e))) { out += QLatin1String(en.r); i += (int)strlen(en.e); hit = true; break; }
            if (!hit) { out += c; i++; }
        } else { out += c; i++; }
    }
    return out;
}

void Player::lyrics(const QJSValue &cb) {
    QVariantList params;
    if (!m_id.isEmpty()) params = {"musicartistinfo", "lyrics", "track_id:" + m_id};
    else if (!m_artist.isEmpty() || !m_title.isEmpty()) params = {"musicartistinfo", "lyrics", "artist:" + m_artist, "title:" + m_title};
    else { callJs(cb, {QString()}); return; }
    QJSValue f = cb;
    Api::instance()->lmsRequest(m_playerId, params, [this, f](bool ok, const QVariant &data, int) mutable {
        QString text;
        if (ok) text = stripHtml(data.toMap().value("result").toMap().value("lyrics").toString());
        if (text.trimmed().isEmpty()) text.clear();
        callJs(f, {text});
    }, 15000);
}

QString Player::formatTime(double sec) const {
    // formatTime in useLyrionPlayer.js non passa mai alle ore ("72:05")
    if (sec < 0 || std::isnan(sec)) sec = 0;
    int tt = (int)sec;
    return QString("%1:%2").arg(tt / 60).arg(tt % 60, 2, 10, QChar('0'));
}
