// library — il modello delle viste del browser (artisti, album, brani,
// cartelle, playlist, radio, app, menu Jive, voci di plugin), con gli
// stessi comandi Lyrion di useLyrionPlayer.js fetchViewData e lib.c.
//
// E' un QAbstractListModel: la ListView/GridView di QML lo consuma diretto.
// Le righe sono quelle VISIBILI (ordinate e filtrate): artisti e album si
// ordinano lato client e il filtro della barra di ricerca agisce qui.
#pragma once
#include <QAbstractListModel>
#include <QVariant>
#include <QVector>

struct LibItem {
    QString id, text, sub, art, icon;
    QString url, favUrl;        // the item's URL (tracks, playlists, plugin audio) and what `favorites add` wants for it
    QString ptype;              // plugin items: the type Lyrion gives them (audio, playlist, link, search)
    QString albumId, artistId;  // tracks and albums: where "go to album / artist" leads
    int kind = -1;              // search results only: 0 artist, 1 album, 2 track
    // Jive menus carry their own actions: `add` puts the item at the end of
    // the queue, `add-hold` plays it next — the same pair SqueezePlay binds to
    // a tap and a long press on ADD.
    QVariantList go, play, doact, addact, addhold;
    bool isDir = false, hasItems = false, isAudio = false, hasInput = false;
    double duration = 0, weight = 0;
    QString fold;               // testo normalizzato per ordinare/filtrare
};

class LibraryModel : public QAbstractListModel {
    Q_OBJECT
    Q_PROPERTY(int state READ state NOTIFY stateChanged)          // 0 idle 1 loading 2 ready 3 error
    Q_PROPERTY(int view READ view NOTIFY stateChanged)
    Q_PROPERTY(int count READ count NOTIFY countChanged)
    Q_PROPERTY(int totalCount READ totalCount NOTIFY countChanged)
    Q_PROPERTY(QString filter READ filter WRITE setFilter NOTIFY filterChanged)
    Q_PROPERTY(int seq READ seq NOTIFY stateChanged)
    Q_PROPERTY(QString playerId MEMBER m_playerId)
public:
    // The new views sit at the end so the numbers the QML compares against
    // stay what they were. Genres/Years/Composers/NewMusic are `genres`,
    // `years`, `artists role_id:COMPOSER` and `albums sort:new`; Search is
    // Lyrion's server-side `search` (artists, albums and tracks in one list,
    // see `kind`). Albums also takes a filter in p2 (genre_id:, year:, role_id:).
    // AlbumPage and ArtistPage are the album and artist pages: they load their
    // own data (AlbumPage.qml, ArtistPage.qml), this model stays empty for them.
    enum View { Home, Artists, Albums, Tracks, Folders, Playlists, PlaylistTracks, Radios, Apps, MenuHome, Menu, PluginItems,
                Genres, Years, Composers, NewMusic, Search, AlbumPage, ArtistPage };
    Q_ENUM(View)
    enum Roles { IdRole = Qt::UserRole + 1, TextRole, SubRole, ArtRole, IconRole, GoRole, PlayRole, DoRole,
                 IsDirRole, HasItemsRole, IsAudioRole, HasInputRole, DurationRole, LetterRole,
                 UrlRole, FavUrlRole, KindRole, SectionRole, AddRole, AddHoldRole, PTypeRole };
    explicit LibraryModel(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = QModelIndex()) const override;
    QVariant data(const QModelIndex &idx, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    int state() const { return m_state; }
    int view() const { return m_view; }
    int count() const { return m_order.size(); }
    int totalCount() const { return m_items.size(); }
    int seq() const { return m_seq; }
    QString filter() const { return m_filter; }
    void setFilter(const QString &f);

    // Avvia il caricamento. p1/p2 dipendono dalla vista (vedi lib.h):
    //   Albums: p1 = artist_id; Tracks: p1 = album_id; Folders: p1 = folder_id;
    //   PlaylistTracks: p1 = playlist_id; PluginItems: p1 = comando, p2 = item_id;
    //   Menu: p1 = parametri dell'azione "go" (array), input = testo cercato.
    Q_INVOKABLE void request(int view, const QVariant &p1 = QVariant(), const QVariant &p2 = QVariant(), const QString &input = QString());
    Q_INVOKABLE void clear();
    Q_INVOKABLE QVariantMap get(int row) const;
    Q_INVOKABLE int letterFirst(const QString &letter) const;     // prima riga con quella lettera, -1
    Q_INVOKABLE bool hasLetter(const QString &letter) const;
    Q_INVOKABLE QString letterOf(int row) const;

signals:
    void stateChanged();
    void countChanged();
    void filterChanged();
    void loaded();

private:
    void parse(int view, const QString &cmd, const QVariantMap &result);
    void applyOrderFilter();
    static QString fold(const QString &s);
    QVector<LibItem> m_items;
    QVector<int> m_order;
    int m_state = 0, m_view = 0, m_seq = 0;
    bool m_serverOrder = false;     // keep Lyrion's order (sort:new, search results)
    QString m_filter, m_playerId;
};
