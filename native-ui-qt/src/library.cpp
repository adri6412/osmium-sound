#include "library.h"
#include "api.h"
#include <QJsonDocument>
#include <algorithm>

LibraryModel::LibraryModel(QObject *parent) : QAbstractListModel(parent) {}

int LibraryModel::rowCount(const QModelIndex &parent) const { return parent.isValid() ? 0 : m_order.size(); }

QHash<int, QByteArray> LibraryModel::roleNames() const {
    return {{IdRole, "id"}, {TextRole, "text"}, {SubRole, "sub"}, {ArtRole, "art"}, {IconRole, "icon"},
            {GoRole, "go"}, {PlayRole, "play"}, {DoRole, "doact"}, {IsDirRole, "isDir"}, {HasItemsRole, "hasItems"},
            {IsAudioRole, "isAudio"}, {HasInputRole, "hasInput"}, {DurationRole, "duration"}, {LetterRole, "letter"},
            {UrlRole, "url"}, {FavUrlRole, "favUrl"}, {KindRole, "kind"}, {SectionRole, "section"},
            {AddRole, "addact"}, {AddHoldRole, "addhold"}, {PTypeRole, "ptype"}};
}

QVariant LibraryModel::data(const QModelIndex &idx, int role) const {
    if (!idx.isValid() || idx.row() < 0 || idx.row() >= m_order.size()) return QVariant();
    const LibItem &it = m_items[m_order[idx.row()]];
    switch (role) {
    case IdRole: return it.id;
    case TextRole: return it.text;
    case SubRole: return it.sub;
    case ArtRole: return it.art;
    case IconRole: return it.icon;
    case GoRole: return it.go;
    case PlayRole: return it.play;
    case DoRole: return it.doact;
    case AddRole: return it.addact;
    case AddHoldRole: return it.addhold;
    case PTypeRole: return it.ptype;
    case IsDirRole: return it.isDir;
    case HasItemsRole: return it.hasItems;
    case IsAudioRole: return it.isAudio;
    case HasInputRole: return it.hasInput;
    case DurationRole: return it.duration;
    case LetterRole: return letterOf(idx.row());
    case UrlRole: return it.url;
    case FavUrlRole: return it.favUrl;
    case KindRole: return it.kind;
    // ListView sections of the search results: one per kind, in order
    case SectionRole: return m_view == Search ? QString::number(it.kind) : QString();
    }
    return QVariant();
}

QVariantMap LibraryModel::get(int row) const {
    QVariantMap m;
    if (row < 0 || row >= m_order.size()) return m;
    const LibItem &it = m_items[m_order[row]];
    m["id"] = it.id; m["text"] = it.text; m["sub"] = it.sub; m["art"] = it.art; m["icon"] = it.icon;
    m["go"] = it.go; m["play"] = it.play; m["doact"] = it.doact; m["isDir"] = it.isDir; m["hasItems"] = it.hasItems;
    m["addact"] = it.addact; m["addhold"] = it.addhold; m["ptype"] = it.ptype;
    m["isAudio"] = it.isAudio; m["hasInput"] = it.hasInput; m["duration"] = it.duration;
    m["url"] = it.url; m["favUrl"] = it.favUrl; m["kind"] = it.kind;
    m["albumId"] = it.albumId; m["artistId"] = it.artistId;
    return m;
}

// Minuscole, accenti tolti (come `normalize` in LyrionServer.jsx); la
// punteggiatura latina U+00A0..U+00BF pesa meno di cifre e lettere, come in ICU.
QString LibraryModel::fold(const QString &s) {
    QString n = s.normalized(QString::NormalizationForm_D).toLower();
    QString out;
    out.reserve(n.size());
    for (QChar c : n) {
        if (c.category() == QChar::Mark_NonSpacing) continue;
        ushort u = c.unicode();
        if (u >= 0x00A0 && u <= 0x00BF) { out += QChar(0x01); continue; }
        out += c;
    }
    return out;
}

QString LibraryModel::letterOf(int row) const {
    if (row < 0 || row >= m_order.size()) return "#";
    const QString &f = m_items[m_order[row]].fold;
    if (f.isEmpty()) return "#";
    QChar c = f[0];
    if (c >= 'a' && c <= 'z') return QString(c.toUpper());
    return "#";
}
int LibraryModel::letterFirst(const QString &letter) const {
    for (int i = 0; i < m_order.size(); i++) if (letterOf(i) == letter) return i;
    return -1;
}
bool LibraryModel::hasLetter(const QString &letter) const { return letterFirst(letter) >= 0; }

void LibraryModel::clear() {
    beginResetModel();
    m_items.clear(); m_order.clear();
    endResetModel();
    m_state = 0;
    emit stateChanged();
    emit countChanged();
    bumpRev();
}

// Traduce un'azione del protocollo "menu" (cmd + params) nei parametri
// pronti per slim.request (lyrionApi._actionToRequest): i comandi che
// finiscono in "items" prendono offset e limite; i params dell'item si
// fondono (modello base+item di Jive).
static QVariantList buildAction(const QVariantMap &action, const QVariantMap &itemParams) {
    QVariantList cmd = action.value("cmd").toList();
    if (cmd.isEmpty()) return {};
    QVariantList out;
    for (const QVariant &c : cmd) out << c.toString();
    if (cmd.last().toString() == "items") out << "0" << "9999";
    for (int pass = 0; pass < 2; pass++) {
        QVariantMap obj = pass == 0 ? action.value("params").toMap() : itemParams;
        for (auto it = obj.constBegin(); it != obj.constEnd(); ++it) {
            const QVariant &v = it.value();
            if (v.typeId() == QMetaType::QString) out << it.key() + ":" + v.toString();
            else if (v.typeId() == QMetaType::Bool) out << it.key() + ":" + (v.toBool() ? "1" : "0");
            else if (v.canConvert<double>()) {
                double d = v.toDouble();
                out << it.key() + ":" + (d == (long long)d ? QString::number((long long)d) : QString::number(d));
            }
        }
    }
    return out;
}

static QVariantList resolveAction(const QVariantMap &base, const QVariantMap &item, const QString &name) {
    QVariantMap ia = item.value("actions").toMap().value(name).toMap();
    QVariantMap ba = base.value("actions").toMap().value(name).toMap();
    QVariantMap action = !ia.isEmpty() ? ia : ba;
    if (action.isEmpty() || !action.contains("cmd")) return {};
    QVariantMap itemParams;
    QString ip = action.value("itemsParams").toString();
    if (!ip.isEmpty() && item.contains(ip)) itemParams = item.value(ip).toMap();
    else if (ia.isEmpty() && item.contains("params")) itemParams = item.value("params").toMap();
    return buildAction(action, itemParams);
}

// `favorites add` wants a URL: plugin and menu items carry theirs in
// presetParams, the same place Lyrion's own skins read it from.
static QString favUrlOf(const QVariantMap &it) {
    QVariantMap pp = it.value("presetParams").toMap();
    QString u = pp.value("favorites_url").toString();
    if (u.isEmpty()) u = it.value("favorites_url").toString();
    return u;
}

static QString menuIcon(const QVariantMap &it) {
    QString ic = it.value("icon-id").toString();
    if (ic.isEmpty()) ic = it.value("window").toMap().value("icon-id").toString();
    if (ic.isEmpty()) ic = it.value("icon").toString();
    if (ic.isEmpty()) ic = it.value("image").toString();
    return ic;
}

static QString str(const QVariantMap &m, const char *k) {
    QVariant v = m.value(k);
    if (v.typeId() == QMetaType::Double || v.typeId() == QMetaType::LongLong || v.typeId() == QMetaType::Int)
        return QString::number(v.toLongLong());
    return v.toString();
}

static QVariantList substituteInput(QVariantList params, const QString &input) {
    for (QVariant &p : params) {
        if (p.typeId() != QMetaType::QString) continue;
        QString s = p.toString();
        s.replace("__TAGGEDINPUT__", input).replace("__INPUT__", input);
        p = s;
    }
    return params;
}

void LibraryModel::request(int view, const QVariant &p1, const QVariant &p2, const QString &input) {
    int seq = ++m_seq;
    m_view = view;
    m_state = 1;
    m_filter.clear();
    emit filterChanged();
    emit stateChanged();
    QVariantList params;
    QString s1 = p1.typeId() == QMetaType::QVariantList ? QString() : p1.toString();
    QString s2 = p2.toString();
    // server order only where Lyrion's ordering is the point (new music,
    // random, search results); the alphabetical views sort here
    m_serverOrder = view == NewMusic || view == Search || (view == Albums && s2.contains("sort:"));
    switch (view) {
    case Artists: params = {"artists", "0", "9999", "tags:s"}; break;
    // p2 = extra filter for the albums query: genre_id:N, year:YYYY, role_id:COMPOSER, sort:new…
    case Albums: params = {"albums", "0", "9999", "tags:alSj"}; if (!s1.isEmpty()) params << "artist_id:" + s1; if (!s2.isEmpty()) params << s2; break;
    case NewMusic: params = {"albums", "0", "100", "tags:alSj", "sort:new"}; break;
    case Genres: params = {"genres", "0", "9999"}; break;
    case Years: params = {"years", "0", "9999"}; break;
    case Composers: params = {"artists", "0", "9999", "tags:s", "role_id:COMPOSER"}; break;
    // Lyrion's own search: artists, albums and tracks that contain the words
    case Search: params = {"search", "0", "50", "term:" + input}; break;
    case Tracks: params = {"titles", "0", "9999", "tags:aAlcdtues"}; if (!s1.isEmpty()) params << "album_id:" + s1; break;
    case Folders: params = {"musicfolder", "0", "9999", "tags:u"}; if (!s1.isEmpty()) params << "folder_id:" + s1; break;
    case Playlists: params = {"playlists", "0", "9999", "tags:u"}; break;
    case PlaylistTracks: params = {"playlists", "tracks", "0", "9999", "playlist_id:" + s1, "tags:aAlcdtues"}; break;
    case Radios: params = {"radios", "0", "9999"}; break;
    case Apps: params = {"apps", "0", "9999"}; break;
    case MenuHome: params = {"menu", "0", "999", "direct:1"}; break;
    case Menu: params = p1.toList(); if (!input.isEmpty()) params = substituteInput(params, input); break;
    // `search:` e' come chiede la ricerca dei plugin (xmlbrowser), non
    // __TAGGEDINPUT__ del menu Jive
    case PluginItems: params = {s1, "items", "0", "9999"};
        if (!s2.isEmpty()) params << "item_id:" + s2;
        if (!input.isEmpty()) params << "search:" + input;
        break;
    default:
        beginResetModel(); m_items.clear(); m_order.clear(); endResetModel();
        m_state = 2; emit stateChanged(); emit countChanged(); bumpRev(); emit loaded();
        return;
    }
    Api::instance()->lmsRequest(m_playerId, params, [this, seq, view, s1](bool ok, const QVariant &data, int) {
        if (seq != m_seq) return;                              // superata da una richiesta piu' nuova
        beginResetModel();
        m_items.clear(); m_order.clear();
        if (ok) parse(view, s1, data.toMap().value("result").toMap());
        endResetModel();
        m_state = ok ? 2 : 3;
        applyOrderFilter();
        emit stateChanged();
        emit loaded();
    }, 20000);
}

void LibraryModel::parse(int view, const QString &cmd, const QVariantMap &res) {
    QStringList loopNames;
    switch (view) {
    case Artists: case Composers: loopNames = {"artists_loop"}; break;
    case Albums: case NewMusic: loopNames = {"albums_loop"}; break;
    case Genres: loopNames = {"genres_loop"}; break;
    case Years: loopNames = {"years_loop"}; break;
    case Search: {
        // three loops, kept in this order (the ListView shows them as sections)
        static const struct { const char *loop; const char *idKey; const char *textKey; int kind; } parts[] = {
            {"contributors_loop", "contributor_id", "contributor", 0}, {"albums_loop", "album_id", "album", 1}, {"tracks_loop", "track_id", "track", 2}};
        for (const auto &pt : parts) {
            for (const QVariant &v : res.value(pt.loop).toList()) {
                QVariantMap it = v.toMap();
                LibItem o;
                o.id = str(it, pt.idKey); o.text = str(it, pt.textKey); o.kind = pt.kind;
                if (o.id.isEmpty() || o.text.isEmpty()) continue;
                o.fold = fold(o.text);
                m_items.append(o);
            }
        }
        return;
    }
    case Tracks: loopNames = {"titles_loop"}; break;
    case Folders: loopNames = {"folder_loop"}; break;
    case Playlists: loopNames = {"playlists_loop"}; break;
    case PlaylistTracks: loopNames = {"playlisttracks_loop"}; break;
    case Radios: loopNames = {"radioss_loop", "radios_loop"}; break;
    case Apps: loopNames = {"appss_loop", "apps_loop"}; break;
    case MenuHome: case Menu: loopNames = {"item_loop"}; break;
    case PluginItems: loopNames = {"loop_loop", "item_loop", cmd + "_loop"}; break;
    }
    QVariantList loop;
    for (const QString &n : loopNames) if (res.contains(n)) { loop = res.value(n).toList(); break; }
    QVariantMap base = res.value("base").toMap();
    m_items.reserve(loop.size());
    for (const QVariant &v : loop) {
        QVariantMap it = v.toMap();
        LibItem o;
        switch (view) {
        case Artists: case Composers: o.id = str(it, "id"); o.text = str(it, "artist"); o.favUrl = str(it, "favorites_url"); break;
        case Albums: case NewMusic:
            // 🚨 no artwork_track_id = no cover: the album id is NOT a track
            // id, and /music/<album id>/cover showed some other track's cover
            o.id = str(it, "id"); o.text = str(it, "album"); o.sub = str(it, "artist"); o.art = str(it, "artwork_track_id");
            o.artistId = str(it, "artist_id");
            o.favUrl = str(it, "favorites_url");          // db:album.title=…&contributor.name=…
            break;
        case Genres: o.id = str(it, "id"); o.text = str(it, "genre"); o.favUrl = str(it, "favorites_url"); break;
        case Years: o.id = str(it, "year"); o.text = o.id == "0" ? QString("—") : o.id; o.favUrl = str(it, "favorites_url"); break;
        case Tracks: case PlaylistTracks:
            o.id = str(it, "id"); o.text = str(it, "title"); o.sub = str(it, "artist"); o.duration = it.value("duration").toDouble();
            o.url = str(it, "url"); o.favUrl = str(it, "favorites_url"); if (o.favUrl.isEmpty()) o.favUrl = o.url;
            o.albumId = str(it, "album_id"); o.artistId = str(it, "artist_id");
            break;
        case Folders:
            o.id = str(it, "id"); o.text = str(it, "filename"); if (o.text.isEmpty()) o.text = str(it, "title");
            o.isDir = str(it, "type") == "folder";
            break;
        case Playlists: o.id = str(it, "id"); o.text = str(it, "playlist"); o.url = str(it, "url"); o.favUrl = str(it, "favorites_url"); if (o.favUrl.isEmpty()) o.favUrl = o.url; break;
        case Radios: case Apps: o.id = str(it, "cmd"); o.text = str(it, "name"); o.icon = str(it, "icon"); break;
        case MenuHome: {
            QVariantMap acts = it.value("actions").toMap();
            QString node = str(it, "node"), id = str(it, "id");
            bool okNode = node == "home" || node.isEmpty() || node == "extras";
            bool hasAct = acts.contains("go") || acts.contains("do") || it.contains("input");
            bool excl = id == "myMusic" || id == "radios" || id == "playerpower";
            QString go0 = acts.value("go").toMap().value("cmd").toList().value(0).toString();
            if (!okNode || !hasAct || excl || go0 == "favorites") continue;
            o.id = id; o.text = str(it, "text"); if (o.text.isEmpty()) o.text = str(it, "name");
            o.icon = menuIcon(it);
            o.go = resolveAction({}, it, "go"); o.play = resolveAction({}, it, "play"); o.doact = resolveAction({}, it, "do");
            o.addact = resolveAction({}, it, "add"); o.addhold = resolveAction({}, it, "add-hold");
            o.favUrl = favUrlOf(it);
            o.hasInput = it.contains("input"); o.weight = it.value("weight").toDouble();
            break;
        }
        case Menu:
            o.id = str(it, "id"); o.text = str(it, "text"); if (o.text.isEmpty()) o.text = str(it, "name");
            o.icon = menuIcon(it);
            o.go = resolveAction(base, it, "go"); o.play = resolveAction(base, it, "play");
            if (o.play.isEmpty()) o.play = resolveAction(base, it, "playall");
            o.doact = resolveAction(base, it, "do"); o.hasInput = it.contains("input");
            o.addact = resolveAction(base, it, "add"); o.addhold = resolveAction(base, it, "add-hold");
            o.favUrl = favUrlOf(it);
            break;
        case PluginItems: {
            o.id = str(it, "id"); if (o.id.isEmpty()) o.id = str(it, "play");
            o.text = str(it, "name"); if (o.text.isEmpty()) o.text = str(it, "title");
            o.icon = str(it, "icon");
            QString type = str(it, "type"); o.ptype = type;
            // 🚨 Lyrion marca il nodo di ricerca con type:"search" ma gli mette
            // ANCHE hasitems:1 (il suo ripiego "Bug 7684"): non e' un vero
            // sottomenu. Entrandoci si manda al plugin una ricerca vuota, e
            // alcuni (RadioNet) rispondono con un errore. Va chiesto il testo.
            o.hasInput = type == "search";
            o.hasItems = !o.hasInput && (it.value("hasitems").toInt() == 1 || type == "link");
            o.isAudio = it.value("isaudio").toInt() == 1 || type == "audio" || it.contains("play");
            o.url = str(it, "url");
            // 🚨 what a plugin item can be saved as is in presetParams
            // (favorites_url), which Lyrion only attaches to items that are
            // music — a station, an album, a playlist, a track. Navigation
            // nodes have none, which is how the long-press menu tells the two
            // apart. `url` alone only ever covered radio stations.
            o.favUrl = favUrlOf(it); if (o.favUrl.isEmpty()) o.favUrl = o.url;
            break;
        }
        default: break;
        }
        o.fold = fold(view == Albums || view == NewMusic ? o.text + " " + o.sub : o.text);
        m_items.append(o);
    }
    if (view == MenuHome)
        std::stable_sort(m_items.begin(), m_items.end(), [](const LibItem &a, const LibItem &b) { return a.weight < b.weight; });
}

void LibraryModel::applyOrderFilter() {
    int k = m_items.size();
    QVector<int> order(k);
    for (int i = 0; i < k; i++) order[i] = i;
    if ((m_view == Artists || m_view == Albums || m_view == Composers) && !m_serverOrder)
        std::stable_sort(order.begin(), order.end(), [this](int a, int b) { return m_items[a].fold < m_items[b].fold; });
    QString f = fold(m_filter);
    if (!f.isEmpty()) {
        QVector<int> vis;
        for (int idx : order) if (m_items[idx].fold.contains(f)) vis << idx;
        order = vis;
    }
    beginResetModel();
    m_order = order;
    endResetModel();
    // 🚨 count FIRST, rev after: whoever reads a row by its number looks at
    // count to know the number is still there. The other way round it reads
    // row 5 of a list that has just become two rows long (an empty row, and a
    // QML warning for every slot of the Cover Flow).
    emit countChanged();
    bumpRev();
}

void LibraryModel::setFilter(const QString &f) {
    if (f == m_filter) return;
    m_filter = f;
    emit filterChanged();
    applyOrderFilter();
}
