"""Base de données SQLite : schéma, connexion et recherche plein texte (FTS5)."""
import os
import re
import sqlite3

from flask import g

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "copro.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name        TEXT NOT NULL,
    lot         TEXT,
    role        TEXT NOT NULL DEFAULT 'membre' CHECK (role IN ('admin', 'membre')),
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    code_hash   TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    category      TEXT NOT NULL,
    doc_date      TEXT,
    filename      TEXT NOT NULL,
    storage_key   TEXT NOT NULL,
    mime          TEXT,
    size          INTEGER,
    has_text      INTEGER NOT NULL DEFAULT 0,
    uploaded_by   INTEGER REFERENCES users(id),
    uploaded_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index plein texte : titre + contenu extrait du PDF / Word.
-- remove_diacritics 2 : "electricite" trouve "électricité".
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, body, tokenize = "unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS chantiers (
    id             INTEGER PRIMARY KEY,
    title          TEXT NOT NULL,
    category       TEXT NOT NULL,
    status         TEXT NOT NULL,
    description    TEXT,
    budget_prevu   REAL,
    budget_engage  REAL,
    date_debut     TEXT,
    date_echeance  TEXT,
    responsable_id INTEGER REFERENCES users(id),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chantier_documents (
    chantier_id  INTEGER NOT NULL REFERENCES chantiers(id) ON DELETE CASCADE,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    PRIMARY KEY (chantier_id, document_id)
);

CREATE TABLE IF NOT EXISTS journal (
    id       INTEGER PRIMARY KEY,
    user_id  INTEGER REFERENCES users(id),
    action   TEXT NOT NULL,
    detail   TEXT,
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(path=None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path=None):
    conn = connect(path)
    conn.executescript(SCHEMA)
    # Mise à niveau d'une base créée avec une version précédente
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(login_tokens)")}
    if "code_hash" not in cols:
        conn.execute("DELETE FROM login_tokens")
        conn.execute("ALTER TABLE login_tokens ADD COLUMN code_hash TEXT")
        conn.execute("ALTER TABLE login_tokens ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE login_tokens ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


def log(user_id, action, detail=""):
    db = get_db()
    db.execute("INSERT INTO journal (user_id, action, detail) VALUES (?, ?, ?)", (user_id, action, detail))


# ---------- Recherche ----------

_WORD = re.compile(r"[\w\-']+", re.UNICODE)


def fts_query(text):
    """Transforme la saisie libre en requête FTS5 sûre.

    Chaque mot devient un préfixe ("chauff" trouve chauffage, chauffagiste),
    tous les mots doivent être présents. Les guillemets gardent une expression exacte.
    """
    phrases = re.findall(r'"([^"]+)"', text)
    rest = re.sub(r'"[^"]+"', " ", text)
    parts = []
    for p in phrases:
        words = _WORD.findall(p)
        if words:
            parts.append('"' + " ".join(w.replace("'", " ") for w in words) + '"')
    for w in _WORD.findall(rest):
        w = w.strip("-'")
        if len(w) >= 2:
            parts.append('"' + w.replace('"', "") + '"*')
    return " AND ".join(parts)


def index_document(db, doc_id, title, body):
    db.execute("DELETE FROM documents_fts WHERE rowid = ?", (doc_id,))
    db.execute("INSERT INTO documents_fts (rowid, title, body) VALUES (?, ?, ?)", (doc_id, title, body or ""))


def unindex_document(db, doc_id):
    db.execute("DELETE FROM documents_fts WHERE rowid = ?", (doc_id,))
