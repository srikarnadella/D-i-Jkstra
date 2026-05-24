import sqlite3
import pandas as pd
import streamlit as st

from models import DB_PATH, Song, map_genre


def load_songs_from_db() -> list[Song]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT track_title, artist, genre, bpm, key FROM tracks ORDER BY track_title"
    )
    rows = cursor.fetchall()
    conn.close()
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


def get_tracks_df() -> pd.DataFrame:
    """Return the full tracks table with raw column names for algorithmic use."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM tracks ORDER BY track_title", conn)
    conn.close()
    df["bpm"] = pd.to_numeric(df["bpm"], errors="coerce").fillna(0.0)
    return df


def get_library_df(search: str = "", genre_filter: list[str] | None = None) -> pd.DataFrame:
    """Return a display-ready DataFrame for the Library page."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT track_title AS Title, artist AS Artist, ROUND(bpm,1) AS BPM, "
        "key AS Key, genre AS 'Raw Genre' "
        "FROM tracks ORDER BY track_title",
        conn,
    )
    conn.close()

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


def insert_track(title: str, artist: str, bpm: float, key: str, genre: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO tracks (track_title, artist, bpm, key, genre) "
        "VALUES (?, ?, ?, ?, ?)",
        (title, artist, bpm, key, genre),
    )
    conn.commit()
    conn.close()


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
