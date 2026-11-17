import functools
import json
import os
import xml.etree.ElementTree as ET  # building XML only

from defusedxml.ElementTree import fromstring as safe_fromstring  # parsing uploaded XML
import sqlite3
import pandas as pd
import streamlit as st

import models
from models import DB_PATH, TRACK_DURATION_SECONDS, parse_key, Song, map_genre, parse_duration, parse_energy, to_camelot


class ReadOnlyError(RuntimeError):
    pass


def _check_writable() -> None:
    """Every user-triggered write calls this first; DJ_READ_ONLY=1 makes them all refuse."""
    if models.READ_ONLY:
        raise ReadOnlyError("This is a read-only demo — changes are disabled.")


DEMO_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_tracks.csv")


@functools.cache
def _ensure_schema() -> None:
    """Idempotent, additive migrations — runs once per process. A brand-new DB file is
    seeded from demo_tracks.csv so the app is usable on a fresh clone / deployment."""
    fresh = not os.path.exists(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                track_title TEXT, artist TEXT, bpm REAL, key TEXT, genre TEXT,
                UNIQUE(track_title, artist)
            )
        """)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(tracks)")}
        for col, ddl in (("duration", "REAL"), ("location", "TEXT"), ("energy", "INTEGER")):  # NULL = unknown
            if col not in cols:
                conn.execute(f"ALTER TABLE tracks ADD COLUMN {col} {ddl}")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cues (
                track_title TEXT NOT NULL, artist TEXT NOT NULL,
                num INTEGER NOT NULL,        -- -1 = memory cue, 0-7 = hot cue
                name TEXT, start_seconds REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transitions (
                from_title TEXT NOT NULL, from_artist TEXT NOT NULL,
                to_title TEXT NOT NULL, to_artist TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (from_title, from_artist, to_title, to_artist)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_setlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                vibe TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                track_data TEXT NOT NULL
            )
        """)
    if fresh and os.path.exists(DEMO_CSV):
        demo = adapt_uploaded_csv(pd.read_csv(DEMO_CSV))
        with sqlite3.connect(DB_PATH) as conn:  # direct SQL: insert_track() would re-enter this function
            conn.executemany(
                "INSERT OR IGNORE INTO tracks (track_title, artist, bpm, key, genre, duration) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                demo[["name", "artist", "bpm", "key", "genre", "duration"]].itertuples(index=False),
            )


def load_songs_from_db() -> list[Song]:
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT track_title, artist, genre, bpm, key, duration, location, energy FROM tracks ORDER BY track_title"
        )
        rows = cursor.fetchall()
    return [
        Song(
            name=row[0],
            artist=row[1],
            genre=row[2],
            bpm=float(row[3]) if row[3] is not None else 0.0,
            key=row[4] or "",
            duration=row[5] or TRACK_DURATION_SECONDS,
            location=row[6],
            energy=row[7],
        )
        for row in rows
    ]


@st.cache_data(ttl=60)
def get_songs() -> list[Song]:
    return load_songs_from_db()


def get_library_df(search: str = "", genre_filter: list[str] | None = None) -> pd.DataFrame:
    """Return a display-ready DataFrame for the Library page."""
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT track_title AS Title, artist AS Artist, ROUND(bpm,1) AS BPM, "
            "key AS Key, genre AS 'Raw Genre', duration AS 'Length (s)', energy AS Energy "
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


def insert_track(title: str, artist: str, bpm: float, key: str, genre: str,
                 duration: float | None = None, location: str | None = None,
                 energy: int | None = None) -> bool:
    """Insert a track. Returns True if inserted, False if it already exists."""
    _check_writable()
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO tracks (track_title, artist, bpm, key, genre, duration, location, energy) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, artist, bpm, key, genre, duration, location, energy),
        )
        return cursor.rowcount > 0


def save_library_changes(
    to_delete: list[tuple[str, str]],
    to_update: list[dict],
) -> None:
    """Apply deletions and BPM/key/genre edits in a single transaction.

    to_delete: list of (track_title, artist) pairs
    to_update: list of dicts with keys title, artist, bpm, key, genre, duration
    """
    _check_writable()
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        if to_delete:
            for table in ("tracks", "cues"):  # transitions are history — kept
                conn.executemany(
                    f"DELETE FROM {table} WHERE track_title=? AND artist=?",
                    to_delete,
                )
        for row in to_update:
            conn.execute(
                "UPDATE tracks SET bpm=?, key=?, genre=?, duration=?, energy=? WHERE track_title=? AND artist=?",
                (row["bpm"], row["key"], row["genre"], row.get("duration"), row.get("energy"),
                 row["title"], row["artist"]),
            )


def save_setlist(name: str, vibe: str, songs: list[Song]) -> int:
    """Persist a setlist. Returns the new row ID."""
    _check_writable()
    _ensure_schema()
    track_data = json.dumps([s._asdict() for s in songs])
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO saved_setlists (name, vibe, track_data) VALUES (?, ?, ?)",
            (name.strip(), vibe, track_data),
        )
        return cursor.lastrowid


def get_saved_setlists() -> list[dict]:
    """Return all saved setlists as dicts (id, name, vibe, created_at, songs list).
    Songs are refreshed from the current library (BPM/key/energy edits show up); tracks
    deleted since saving fall back to their saved snapshot."""
    _ensure_schema()
    current = {(s.name, s.artist): s for s in load_songs_from_db()}
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, name, vibe, created_at, track_data FROM saved_setlists ORDER BY id DESC"
        ).fetchall()
    result = []
    for row in rows:
        try:
            snapshots = [Song(**t) for t in json.loads(row[4])]
            tracks = [current.get((s.name, s.artist), s) for s in snapshots]
        except Exception:
            tracks = []
        result.append({
            "id": row[0], "name": row[1], "vibe": row[2],
            "created_at": row[3], "songs": tracks,
        })
    return result


def delete_setlist(setlist_id: int) -> None:
    _check_writable()
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM saved_setlists WHERE id=?", (setlist_id,))


def adapt_uploaded_csv(df: pd.DataFrame, fill_duration: bool = True) -> pd.DataFrame:
    """Rename and validate uploaded columns into the standard format:
    name, artist, genre, bpm, key (Camelot), duration (seconds; a missing one becomes TRACK_DURATION_SECONDS
    when fill_duration, else None so the library keeps it as unknown),
    location (or None), energy (1–10 from a number or "Energy N" comment, or None).
    Musical keys ("Am", "F#") are converted to Camelot; Duration may be seconds or m:ss."""
    rename_map = {
        "track_title": "name", "Title": "name",
        "Artist": "artist", "Genre": "genre", "BPM": "bpm", "Key": "key",
        "Duration": "duration", "Length": "duration", "length": "duration",
        "Location": "location", "Energy": "energy",
    }
    if "Energy" not in df.columns and "energy" not in df.columns:
        rename_map["Comments"] = "energy"     # Mixed In Key "… Energy N" comments
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    missing = [c for c in ["name", "artist", "genre", "bpm", "key"] if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")
    for optional in ("duration", "location", "energy"):
        if optional not in df.columns:
            df[optional] = None
    df = df[["name", "artist", "genre", "bpm", "key", "duration", "location", "energy"]].copy()
    df["energy"] = pd.Series([parse_energy(v) for v in df["energy"]], index=df.index, dtype=object)
    df["location"] = pd.Series(
        [v.strip() if isinstance(v, str) and v.strip() else None for v in df["location"]],
        index=df.index, dtype=object)  # real None (not NaN) when missing
    df["bpm"] = pd.to_numeric(df["bpm"], errors="coerce").fillna(0.0)
    for col in ("name", "artist", "genre", "key"):
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["key"] = df["key"].map(to_camelot)
    df["duration"] = pd.Series(
        [parse_duration(v) or (TRACK_DURATION_SECONDS if fill_duration else None) for v in df["duration"]],
        index=df.index, dtype=object)
    return df


def parse_rekordbox_xml(data: bytes) -> pd.DataFrame:
    """Read a Rekordbox collection export (File → Export Collection in xml format)
    into the same shape as adapt_uploaded_csv()."""
    root = safe_fromstring(data)
    collection = root.find("COLLECTION")
    rows = [
        {
            "name": t.get("Name", ""), "artist": t.get("Artist", ""),
            "genre": t.get("Genre", ""), "bpm": t.get("AverageBpm"),
            "key": t.get("Tonality", ""), "duration": t.get("TotalTime"),
            "location": t.get("Location"),
            "energy": t.get("Comments"),  # Mixed In Key writes "… Energy N" here
        }
        for t in (collection if collection is not None else root).iter("TRACK")
        if t.get("Name")  # playlist entries are <TRACK Key=".."/> with no Name
    ]
    if not rows:
        raise ValueError("No tracks found — is this a Rekordbox collection XML export?")
    return adapt_uploaded_csv(pd.DataFrame(rows), fill_duration=False)


def parse_rekordbox_cues(data: bytes) -> list[dict]:
    """Cue points from a Rekordbox collection export: dicts with title, artist, num
    (-1 = memory cue, 0-7 = hot cue), name, start_seconds. Loops and fade markers are skipped."""
    root = safe_fromstring(data)
    return [
        {"title": t.get("Name", ""), "artist": t.get("Artist", ""), "num": int(m.get("Num", -1)),
         "name": m.get("Name", ""), "start_seconds": float(m.get("Start", 0))}
        for t in root.iter("TRACK") if t.get("Name")
        for m in t.findall("POSITION_MARK") if m.get("Type") == "0"
    ]


def save_cues(cues: list[dict]) -> None:
    """Replace the stored cues for every (title, artist) present in `cues`."""
    _check_writable()
    _ensure_schema()
    pairs = {(c["title"], c["artist"]) for c in cues}
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany("DELETE FROM cues WHERE track_title=? AND artist=?", pairs)
        conn.executemany(
            "INSERT INTO cues (track_title, artist, num, name, start_seconds) VALUES (?, ?, ?, ?, ?)",
            [(c["title"], c["artist"], c["num"], c["name"], c["start_seconds"]) for c in cues],
        )


def get_cues(title: str, artist: str) -> list[dict]:
    """Cues for one track, in time order."""
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT num, name, start_seconds FROM cues WHERE track_title=? AND artist=? "
            "ORDER BY start_seconds", (title, artist)).fetchall()
    return [{"num": n, "name": name, "start_seconds": t} for n, name, t in rows]


def setlist_to_rekordbox_xml(name: str, songs: list[Song]) -> bytes:
    """Rekordbox collection-XML containing `songs` and one playlist `name` in set order.
    Rekordbox links playlist entries to your tracks by file Location, so songs without
    one are included but won't link."""
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="rekordbox", Version="6.0.0", Company="AlphaTheta")
    coll = ET.SubElement(root, "COLLECTION", Entries=str(len(songs)))
    for i, s in enumerate(songs, 1):
        attrs = {"TrackID": str(i), "Name": s.name, "Artist": s.artist, "Genre": s.genre or "",
                 "AverageBpm": f"{s.bpm:.2f}", "Tonality": s.key or "", "TotalTime": str(int(s.duration))}
        if s.location:
            attrs["Location"] = s.location
        if s.energy is not None:
            attrs["Comments"] = f"Energy {int(s.energy)}"
        ET.SubElement(coll, "TRACK", attrs)
    node = ET.SubElement(ET.SubElement(ET.SubElement(root, "PLAYLISTS"), "NODE", Type="0", Name="ROOT", Count="1"),
                         "NODE", Name=name or "D-i-Jkstra set", Type="1", KeyType="0", Entries=str(len(songs)))
    for i in range(1, len(songs) + 1):
        ET.SubElement(node, "TRACK", Key=str(i))
    ET.indent(root)
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def get_all_cues() -> dict:
    """{(title, artist): [cue dicts]} for every track with cues."""
    _ensure_schema()
    out: dict = {}
    with sqlite3.connect(DB_PATH) as conn:
        for t, a, n, name, start in conn.execute(
                "SELECT track_title, artist, num, name, start_seconds FROM cues ORDER BY start_seconds"):
            out.setdefault((t, a), []).append({"num": n, "name": name, "start_seconds": start})
    return out


def parse_rekordbox_playlists(data: bytes) -> dict[str, list[tuple[str, str]]]:
    """{"Folder/Playlist": [(title, artist), …] in play order} from a Rekordbox collection export."""
    root = safe_fromstring(data)
    coll = root.find("COLLECTION")
    by_id = {t.get("TrackID"): (t.get("Name", ""), t.get("Artist", ""))
             for t in (coll if coll is not None else [])}
    out: dict[str, list[tuple[str, str]]] = {}

    def walk(node, prefix):
        for child in node.findall("NODE"):
            name = child.get("Name", "")
            if child.get("Type") == "1":
                tracks = [by_id[t.get("Key")] for t in child.findall("TRACK") if t.get("Key") in by_id]
                if tracks:
                    out[prefix + name] = tracks
            else:
                walk(child, prefix + name + "/" if name and name != "ROOT" else prefix)

    playlists = root.find("PLAYLISTS")
    if playlists is not None:
        walk(playlists, "")
    return out


def record_transitions(sequences: list[list[tuple[str, str]]]) -> int:
    """Count every consecutive pair in the played sequences. Returns pairs recorded."""
    _check_writable()
    _ensure_schema()
    pairs = [(a[0], a[1], b[0], b[1]) for seq in sequences for a, b in zip(seq, seq[1:]) if a != b]
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            "INSERT INTO transitions (from_title, from_artist, to_title, to_artist, count) VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT(from_title, from_artist, to_title, to_artist) DO UPDATE SET count = count + 1", pairs)
    return len(pairs)


def get_transition_counts() -> dict:
    """{((from_title, from_artist), (to_title, to_artist)): times played}."""
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT from_title, from_artist, to_title, to_artist, count FROM transitions").fetchall()
    return {((a, b), (c, d)): n for a, b, c, d, n in rows}


def clear_transitions() -> None:
    _check_writable()
    _ensure_schema()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM transitions")


# ── Library page logic (kept here so it's testable without Streamlit) ─────────

def _changed(a, b) -> bool:
    """NaN-safe inequality for data_editor cells."""
    return not (a == b or (pd.isna(a) and pd.isna(b)))


LIBRARY_EDITABLE = ("BPM", "Key", "Genre", "Length (s)", "Energy")


def library_changes(original: pd.DataFrame, edited: pd.DataFrame) -> tuple[list, list[dict], list[str]]:
    """Diff the Library editor (rows aligned by position) into
    (to_delete [(title, artist)], to_update [dicts for save_library_changes], errors).
    to_update is empty whenever there are errors, so nothing half-applies."""
    to_delete = [(r["Title"], r["Artist"]) for _, r in edited.iterrows() if r["Delete?"]]
    changed = [
        e for (_, o), (_, e) in zip(original.iterrows(), edited.iterrows())
        if not e["Delete?"] and any(_changed(o[c], e[c]) for c in LIBRARY_EDITABLE)
    ]
    errors = [
        f"'{r['Title']}' has invalid key '{r['Key']}' — use Camelot (8A) or musical (Am)."
        for r in changed if (k := to_camelot(r["Key"])) and parse_key(k)[0] is None
    ]
    to_update = [
        {
            "title": r["Title"], "artist": r["Artist"],
            "bpm": float(r["BPM"]),
            "key": to_camelot(r["Key"]),
            "genre": str(r["Genre"] or "").strip(),
            "duration": parse_duration(r["Length (s)"]),
            "energy": parse_energy(r["Energy"]),
        }
        for r in changed
    ]
    return to_delete, ([] if errors else to_update), errors


def import_tracks(adapted: pd.DataFrame, cues: list[dict] | None = None) -> dict:
    """Insert rows from adapt_uploaded_csv()/parse_rekordbox_xml() and save cues.
    Returns counts: inserted, skipped (already existed), invalid (no title/artist or bad key), cues."""
    _check_writable()
    counts = {"inserted": 0, "skipped": 0, "invalid": 0, "cues": len(cues or [])}
    for _, r in adapted.iterrows():
        if not r["name"] or not r["artist"] or (r["key"] and parse_key(r["key"])[0] is None):
            counts["invalid"] += 1
        elif insert_track(title=r["name"], artist=r["artist"], bpm=float(r["bpm"]), key=r["key"],
                          genre=r["genre"], duration=None if pd.isna(r["duration"]) else float(r["duration"]),
                          location=r["location"],
                          energy=r["energy"]):
            counts["inserted"] += 1
        else:
            counts["skipped"] += 1
    if cues:
        save_cues(cues)
    return counts
