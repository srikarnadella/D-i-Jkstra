import json
import sqlite3
import pandas as pd
import streamlit as st

from models import DB_PATH, Song, map_genre


def _ensure_saved_setlists_table() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_setlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vibe TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                track_data TEXT NOT NULL
            )
        """)


def load_songs_from_db() -> list[Song]:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT track_title, artist, genre, bpm, key FROM tracks ORDER BY track_title"
        )
        rows = cursor.fetchall()
    return [
        Song(
            name=row[0],
            artist=row[1],
            genre=row[2],
            bpm=float(row[3]) if row[3] is not None else 0.0,
            key=row[4] or "",
        )
        for row in rows
    ]


@st.cache_data(ttl=60)
def get_songs() -> list[Song]:
    return load_songs_from_db()


@st.cache_data(ttl=60)
def get_tracks_df() -> pd.DataFrame:
    """Return the full tracks table with raw column names for algorithmic use."""
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query("SELECT * FROM tracks ORDER BY track_title", conn)
    df["bpm"] = pd.to_numeric(df["bpm"], errors="coerce").fillna(0.0)
    return df


def get_library_df(search: str = "", genre_filter: list[str] | None = None) -> pd.DataFrame:
    """Return a display-ready DataFrame for the Library page."""
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT track_title AS Title, artist AS Artist, ROUND(bpm,1) AS BPM, "
            "key AS Key, genre AS 'Raw Genre' "
            "FROM tracks ORDER BY track_title",
            conn,
        )

    df.insert(4, "Genre", df["Raw Genre"].apply(map_genre))
    df = df.drop(columns=["Raw Genre"])

    if search:
        mask = (
            df["Title"].str.contains(search, case=False, na=False)
            | df["Artist"].str.contains(search, case=False, na=False)
        )
        df = df[mask]
    if genre_filter:
        df = df[df["Genre"].isin(genre_filter)]

    return df


def insert_track(title: str, artist: str, bpm: float, key: str, genre: str) -> bool:
    """Insert a track. Returns True if inserted, False if it already exists."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO tracks (track_title, artist, bpm, key, genre) "
            "VALUES (?, ?, ?, ?, ?)",
            (title, artist, bpm, key, genre),
        )
        return cursor.rowcount > 0


def update_track(title: str, artist: str, bpm: float, key: str, genre: str) -> None:
    """Update BPM, key, and genre for a track identified by (title, artist)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE tracks SET bpm=?, key=?, genre=? WHERE track_title=? AND artist=?",
            (bpm, key, genre, title, artist),
        )


def delete_tracks(keys: list[tuple[str, str]]) -> None:
    """Delete tracks by (track_title, artist) pairs."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "DELETE FROM tracks WHERE track_title=? AND artist=?",
            keys,
        )


def save_library_changes(
    to_delete: list[tuple[str, str]],
    to_update: list[dict],
) -> None:
    """Apply deletions and BPM/key/genre edits in a single transaction.

    to_delete: list of (track_title, artist) pairs
    to_update: list of dicts with keys title, artist, bpm, key, genre
    """
    with sqlite3.connect(DB_PATH) as conn:
        if to_delete:
            conn.executemany(
                "DELETE FROM tracks WHERE track_title=? AND artist=?",
                to_delete,
            )
        for row in to_update:
            conn.execute(
                "UPDATE tracks SET bpm=?, key=?, genre=? WHERE track_title=? AND artist=?",
                (row["bpm"], row["key"], row["genre"], row["title"], row["artist"]),
            )


def save_setlist(name: str, vibe: str, songs: list[Song]) -> int:
    """Persist a setlist. Returns the new row ID."""
    _ensure_saved_setlists_table()
    track_data = json.dumps([
        {"name": s.name, "artist": s.artist, "genre": s.genre, "bpm": s.bpm, "key": s.key}
        for s in songs
    ])
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO saved_setlists (name, vibe, track_data) VALUES (?, ?, ?)",
            (name.strip(), vibe, track_data),
        )
        return cursor.lastrowid


def get_saved_setlists() -> list[dict]:
    """Return all saved setlists as dicts (id, name, vibe, created_at, songs list)."""
    _ensure_saved_setlists_table()
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, name, vibe, created_at, track_data FROM saved_setlists ORDER BY id DESC"
        ).fetchall()
    result = []
    for row in rows:
        try:
            tracks = [Song(**t) for t in json.loads(row[4])]
        except Exception:
            tracks = []
        result.append({
            "id": row[0], "name": row[1], "vibe": row[2],
            "created_at": row[3], "songs": tracks,
        })
    return result


def delete_setlist(setlist_id: int) -> None:
    _ensure_saved_setlists_table()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM saved_setlists WHERE id=?", (setlist_id,))


def adapt_uploaded_csv(df: pd.DataFrame) -> pd.DataFrame:
    """Rename and validate columns from an uploaded CSV into the standard format."""
    rename_map = {
        "track_title": "name", "Title": "name",
        "Artist": "artist", "Genre": "genre", "BPM": "bpm", "Key": "key",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    missing = [c for c in ["name", "artist", "genre", "bpm", "key"] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    df = df[["name", "artist", "genre", "bpm", "key"]].copy()
    df["bpm"] = pd.to_numeric(df["bpm"], errors="coerce").fillna(0.0)
    return df
