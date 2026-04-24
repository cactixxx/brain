PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entries (
    id              INTEGER PRIMARY KEY,
    type            TEXT NOT NULL CHECK(type IN ('decision','fact','todo','note','spec')),
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    alternatives    TEXT,
    tags            TEXT,
    keywords        TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','superseded','done','cancelled')),
    superseded_by   INTEGER REFERENCES entries(id),
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_type       ON entries(type);
CREATE INDEX IF NOT EXISTS idx_entries_status     ON entries(status);
CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at);

CREATE TABLE IF NOT EXISTS edges (
    id         INTEGER PRIMARY KEY,
    from_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    to_id      INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK(kind IN (
                   'depends_on','blocks','relates_to','uses',
                   'replaces','implements','contradicts')),
    note       TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(from_id, to_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to   ON edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, body, tags, keywords,
    content='entries',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS entries_fts_insert AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, body, tags, keywords)
    VALUES (new.id, new.title, new.body, COALESCE(new.tags,''), COALESCE(new.keywords,''));
END;

CREATE TRIGGER IF NOT EXISTS entries_fts_update AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, body, tags, keywords)
    VALUES ('delete', old.id, old.title, old.body, COALESCE(old.tags,''), COALESCE(old.keywords,''));
    INSERT INTO entries_fts(rowid, title, body, tags, keywords)
    VALUES (new.id, new.title, new.body, COALESCE(new.tags,''), COALESCE(new.keywords,''));
END;

CREATE TRIGGER IF NOT EXISTS entries_fts_delete AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, body, tags, keywords)
    VALUES ('delete', old.id, old.title, old.body, COALESCE(old.tags,''), COALESCE(old.keywords,''));
END;
