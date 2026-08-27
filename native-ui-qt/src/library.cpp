#include "library.h"
#include "api.h"
#include <QJsonDocument>
#include <algorithm>

LibraryModel::LibraryModel(QObject *parent) : QAbstractListModel(parent) {}

int LibraryModel::rowCount(const QModelIndex &parent) const { return parent.isValid() ? 0 : m_order.size(); }

QHash<int, QByteArray> LibraryModel::roleNames() const {
    return {{IdRole, "id"}, {TextRole, "text"}, {SubRole, "sub"}, {ArtRole, "art"}, {IconRole, "icon"},
            {GoRole, "go"}, {PlayRole, "play"}, {DoRole, "doact"}, {IsDirRole, "isDir"}, {HasItemsRole, "hasItems"},
            {IsAudioRole, "isAudio"}, {HasInputRole, "hasInput"}, {DurationRole, "duration"}, {LetterRole, "letter"}};
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
    case IsDirRole: return it.isDir;
    case HasItemsRole: return it.hasItems;
    case IsAudioRole: return it.isAudio;
    case HasInputRole: return it.hasInput;
    case DurationRole: return it.duration;
    case LetterRole: return letterOf(idx.row());
    }
    return QVariant();
}

QVariantMap LibraryModel::get(int row) const {
    QVariantMap m;
    if (row < 0 || row >= m_order.size()) return m;
    const LibItem &it = m_items[m_order[row]];
    m["id"] = it.id; m["text"] = it.text; m["sub"] = it.sub; m["art"] = it.art; m["icon"] = it.icon;
    m["go"] = it.go; m["play"] = it.play; m["doact"] = it.doact; m["isDir"] = it.isDir; m["hasItems"] = it.hasItems;
    m["isAudio"] = it.isAudio; m["hasInput"] = it.hasInput; m["duration"] = it.duration;
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
    switch (view) {
    case Artists: params = {"artists", "0", "9999", "tags:s"}; break;
    case Albums: params = {"albums", "0", "9999", "tags:alSj"}; if (!s1.isEmpty()) params << "artist_id:" + s1; break;
    case Tracks: params = {"titles", "0", "9999", "tags:aAlcdtu"}; if (!s1.isEmpty()) params << "album_id:" + s1; break;
    case Folders: params = {"musicfolder", "0", "9999", "tags:u"}; if (!s1.isEmpty()) params << "folder_id:" + s1; break;
    case Playlists: params = {"playlists", "0", "9999"}; break;
    case PlaylistTracks: params = {"playlists", "tracks", "0", "9999", "playlist_id:" + s1, "tags:aAlcdtu"}; break;
    case Radios: params = {"radios", "0", "9999"}; break;
    case Apps: params = {"apps", "0", "9999"}; break;
    case MenuHome: params = {"menu", "0", "999", "direct:1"}; break;
    case Menu: params = p1.toList(); if (!input.isEmpty()) params = substituteInput(params, input); break;
    case PluginItems: params = {s1, "items", "0", "9999"}; if (!s2.isEmpty()) params << "item_id:" + s2; break;
    default:
        beginResetModel(); m_items.clear(); m_order.clear(); endResetModel();
        m_state = 2; emit stateChanged(); emit countChanged(); emit loaded();
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
    case Artists: loopNames = {"artists_loop"}; break;
    case Albums: loopNames = {"albums_loop"}; break;
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
        case Artists: o.id = str(it, "id"); o.text = str(it, "artist"); break;
        case Albums:
            o.id = str(it, "id"); o.text = str(it, "album"); o.sub = str(it, "artist"); o.art = str(it, "artwork_track_id");
            if (o.art.isEmpty()) o.art = o.id;
            break;
        case Tracks: case PlaylistTracks:
            o.id = str(it, "id"); o.text = str(it, "title"); o.sub = str(it, "artist"); o.duration = it.value("duration").toDouble();
            break;
        case Folders:
            o.id = str(it, "id"); o.text = str(it, "filename"); if (o.text.isEmpty()) o.text = str(it, "title");
            o.isDir = str(it, "type") == "folder";
            break;
        case Playlists: o.id = str(it, "id"); o.text = str(it, "playlist"); break;
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
            o.hasInput = it.contains("input"); o.weight = it.value("weight").toDouble();
            break;
        }
        case Menu:
            o.id = str(it, "id"); o.text = str(it, "text"); if (o.text.isEmpty()) o.text = str(it, "name");
            o.icon = menuIcon(it);
            o.go = resolveAction(base, it, "go"); o.play = resolveAction(base, it, "play");
            if (o.play.isEmpty()) o.play = resolveAction(base, it, "playall");
            o.doact = resolveAction(base, it, "do"); o.hasInput = it.contains("input");
            break;
        case PluginItems: {
            o.id = str(it, "id"); if (o.id.isEmpty()) o.id = str(it, "play");
            o.text = str(it, "name"); if (o.text.isEmpty()) o.text = str(it, "title");
            o.icon = str(it, "icon");
            QString type = str(it, "type");
            o.hasItems = it.value("hasitems").toInt() == 1 || type == "link";
            o.isAudio = it.value("isaudio").toInt() == 1 || type == "audio" || it.contains("play");
            break;
        }
        }
        o.fold = fold(view == Albums ? o.text + " " + o.sub : o.text);
        m_items.append(o);
    }
    if (view == MenuHome)
        std::stable_sort(m_items.begin(), m_items.end(), [](const LibItem &a, const LibItem &b) { return a.weight < b.weight; });
}

void LibraryModel::applyOrderFilter() {
    int k = m_items.size();
    QVector<int> order(k);
    for (int i = 0; i < k; i++) order[i] = i;
    if (m_view == Artists || m_view == Albums)
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
    emit countChanged();
}

void LibraryModel::setFilter(const QString &f) {
    if (f == m_filter) return;
    m_filter = f;
    emit filterChanged();
    applyOrderFilter();
}
