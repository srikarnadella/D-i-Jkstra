import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from models import Song


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Fresh, empty DB per test (no demo seeding: demo CSV path pointed nowhere)."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(db, "DEMO_CSV", str(tmp_path / "none.csv"))
    db._ensure_schema.cache_clear()
    yield
    db._ensure_schema.cache_clear()


SONGS = [
    Song("Alpha", "A", "House", 126.0, "8A", 300.0, "file://localhost/m/alpha.mp3"),
    Song("Beta & Co", "B", "Techno", 128.5, "9A", 245.0, None),
    Song("Gamma", "C", "House", 124.0, "9B", 210.0, "file://localhost/m/gamma.mp3"),
]


def test_rekordbox_export_roundtrip():
    xml = db.setlist_to_rekordbox_xml("My Set", SONGS)
    back = db.parse_rekordbox_xml(xml)
    assert back["name"].tolist() == [s.name for s in SONGS]          # "&" survives escaping
    assert back["key"].tolist() == [s.key for s in SONGS]
    assert back["duration"].tolist() == [300.0, 245.0, 210.0]
    assert back["location"].tolist() == [SONGS[0].location, None, SONGS[2].location]


def test_rekordbox_playlist_order_matches_set():
    root = ET.fromstring(db.setlist_to_rekordbox_xml("My Set", SONGS))
    names = {t.get("TrackID"): t.get("Name") for t in root.find("COLLECTION")}
    playlist = root.find("PLAYLISTS//NODE[@Type='1']")
    assert playlist.get("Name") == "My Set" and playlist.get("Entries") == "3"
    assert [names[t.get("Key")] for t in playlist] == [s.name for s in SONGS]


CUE_XML = b"""<DJ_PLAYLISTS><COLLECTION>
 <TRACK Name="Alpha" Artist="A" AverageBpm="126" Tonality="8A" TotalTime="300">
  <POSITION_MARK Name="Drop" Type="0" Start="32.5" Num="0"/>
  <POSITION_MARK Name="" Type="0" Start="180.25" Num="-1"/>
  <POSITION_MARK Name="loop" Type="4" Start="10" End="14" Num="1"/>
 </TRACK></COLLECTION></DJ_PLAYLISTS>"""


def test_parse_cues_skips_loops():
    cues = db.parse_rekordbox_cues(CUE_XML)
    assert [(c["num"], c["start_seconds"]) for c in cues] == [(0, 32.5), (-1, 180.25)]


def test_save_cues_replaces_and_delete_cascades(tmp_db):
    db.insert_track("Alpha", "A", 126, "8A", "House")
    db.save_cues(db.parse_rekordbox_cues(CUE_XML))
    db.save_cues(db.parse_rekordbox_cues(CUE_XML))                      # re-import must not duplicate
    got = db.get_cues("Alpha", "A")
    assert [c["start_seconds"] for c in got] == [32.5, 180.25] and got[0]["name"] == "Drop"
    db.save_library_changes(to_delete=[("Alpha", "A")], to_update=[])
    assert db.get_cues("Alpha", "A") == []


def test_location_stored_and_loaded(tmp_db):
    db.insert_track("Alpha", "A", 126, "8A", "House", 300, "file://x.mp3")
    assert db.load_songs_from_db()[0].location == "file://x.mp3"


def test_fresh_db_seeded_from_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "fresh.db"))
    db._ensure_schema.cache_clear()
    songs = db.load_songs_from_db()
    db._ensure_schema.cache_clear()
    assert len(songs) == 150 and all(s.duration > 100 for s in songs)


def test_existing_db_not_reseeded(tmp_db):
    db.insert_track("Only", "One", 120, "8A", "House")
    db._ensure_schema.cache_clear()
    assert len(db.load_songs_from_db()) == 1


def test_energy_from_csv_and_mixed_in_key_comments():
    import pandas as pd
    df = db.adapt_uploaded_csv(pd.DataFrame({"Title": ["a", "b", "c"], "Artist": ["x"] * 3, "Genre": [""] * 3,
                                             "BPM": [120] * 3, "Key": ["8A"] * 3,
                                             "Comments": ["8A - Energy 6", "nice", None]}))
    assert df["energy"].tolist() == [6, None, None]


def test_energy_roundtrips_through_rekordbox_xml():
    song = SONGS[0]._replace(energy=7)
    assert db.parse_rekordbox_xml(db.setlist_to_rekordbox_xml("s", [song]))["energy"].tolist() == [7]


PLAYLIST_XML = b"""<DJ_PLAYLISTS><COLLECTION>
 <TRACK TrackID="1" Name="One" Artist="A"/><TRACK TrackID="2" Name="Two" Artist="B"/>
 <TRACK TrackID="3" Name="Three" Artist="C"/></COLLECTION>
 <PLAYLISTS><NODE Type="0" Name="ROOT">
  <NODE Type="0" Name="Gigs"><NODE Type="1" Name="Friday" Entries="3">
   <TRACK Key="1"/><TRACK Key="2"/><TRACK Key="3"/></NODE></NODE>
  <NODE Type="1" Name="Empty" Entries="0"/>
 </NODE></PLAYLISTS></DJ_PLAYLISTS>"""


def test_parse_playlists_keeps_order_and_folders():
    assert db.parse_rekordbox_playlists(PLAYLIST_XML) == {
        "Gigs/Friday": [("One", "A"), ("Two", "B"), ("Three", "C")]}


def test_record_transitions_counts_pairs(tmp_db):
    seq = db.parse_rekordbox_playlists(PLAYLIST_XML)["Gigs/Friday"]
    assert db.record_transitions([seq, seq]) == 4
    counts = db.get_transition_counts()
    assert counts[(("One", "A"), ("Two", "B"))] == 2 and len(counts) == 2
    db.clear_transitions()
    assert db.get_transition_counts() == {}


def test_energy_stored_and_loaded(tmp_db):
    db.insert_track("Alpha", "A", 126, "8A", "House", energy=8)
    assert db.load_songs_from_db()[0].energy == 8


def test_saved_setlist_reflects_library_edits_and_survives_deletion(tmp_db):
    db.insert_track("Alpha", "A", 126, "8A", "House")
    db.insert_track("Beta", "B", 128, "9A", "House")
    db.save_setlist("s", "house", db.load_songs_from_db())
    db.save_library_changes(to_delete=[("Beta", "B")],
                            to_update=[{"title": "Alpha", "artist": "A", "bpm": 120.0, "key": "7A",
                                        "genre": "House", "duration": None, "energy": 9}])
    songs = db.get_saved_setlists()[0]["songs"]
    assert (songs[0].bpm, songs[0].key, songs[0].energy) == (120.0, "7A", 9)   # refreshed
    assert songs[1].name == "Beta" and songs[1].bpm == 128                      # snapshot kept


# ── Library page logic + read-only mode ───────────────────────────────────────

def _lib_df():
    import pandas as pd
    return pd.DataFrame({"Title": ["A", "B", "C"], "Artist": ["x", "y", "z"], "BPM": [120.0, 124.0, 128.0],
                         "Key": ["8A", "9A", "10A"], "Genre": ["House"] * 3,
                         "Length (s)": [200.0, float("nan"), 300.0], "Energy": [5.0, float("nan"), 7.0]})


def test_library_changes_diff():
    orig = _lib_df()
    edited = orig.copy()
    edited.insert(0, "Delete?", [False, True, False])
    edited.loc[2, "Key"] = "am"            # musical key, lowercase → 8A
    edited.loc[2, "Energy"] = 9.0
    to_delete, to_update, errors = db.library_changes(orig, edited)
    assert to_delete == [("B", "y")] and errors == []
    assert len(to_update) == 1                 # NaN == NaN on row B must not count as a change
    assert to_update[0] == {"title": "C", "artist": "z", "bpm": 128.0, "key": "8A",
                            "genre": "House", "duration": 300.0, "energy": 9}


def test_library_changes_invalid_key_blocks_everything():
    orig = _lib_df()
    edited = orig.copy()
    edited.insert(0, "Delete?", [False] * 3)
    edited.loc[0, "Key"] = "zz"
    edited.loc[1, "BPM"] = 125.0
    _, to_update, errors = db.library_changes(orig, edited)
    assert len(errors) == 1 and "zz" in errors[0] and to_update == []


def test_import_tracks_counts(tmp_db):
    import pandas as pd
    df = db.adapt_uploaded_csv(pd.DataFrame({
        "Title": ["A", "A", "B", "", "C"], "Artist": ["x", "x", "y", "z", "w"], "Genre": [""] * 5,
        "BPM": [120] * 5, "Key": ["8A", "8A", "Am", "8A", "nonsense"]}))
    c = db.import_tracks(df, db.parse_rekordbox_cues(CUE_XML))
    assert c == {"inserted": 2, "skipped": 1, "invalid": 2, "cues": 2}
    assert {s.name for s in db.load_songs_from_db()} == {"A", "B"}


def test_read_only_blocks_every_write(tmp_db, monkeypatch):
    import models
    db.insert_track("Alpha", "A", 126, "8A", "House")
    monkeypatch.setattr(models, "READ_ONLY", True)
    writes = [
        lambda: db.insert_track("New", "N", 120, "8A", "House"),
        lambda: db.save_library_changes([("Alpha", "A")], []),
        lambda: db.save_setlist("s", "house", []),
        lambda: db.delete_setlist(1),
        lambda: db.save_cues([]),
        lambda: db.record_transitions([]),
        lambda: db.clear_transitions(),
        lambda: db.import_tracks(db.adapt_uploaded_csv(__import__("pandas").DataFrame(
            {"Title": ["a"], "Artist": ["b"], "Genre": [""], "BPM": [1], "Key": ["8A"]}))),
    ]
    for w in writes:
        with pytest.raises(db.ReadOnlyError):
            w()
    assert [s.name for s in db.load_songs_from_db()] == ["Alpha"]       # reads still work


def test_unknown_length_stays_unknown_on_import_but_fills_for_the_visualizer(tmp_db):
    import pandas as pd
    raw = pd.DataFrame({"Title": ["A", "B"], "Artist": ["x", "y"], "Genre": ["", ""], "BPM": [120, 124],
                        "Key": ["8A", "9A"], "Duration": ["3:45", None]})
    assert db.adapt_uploaded_csv(raw)["duration"].tolist() == [225.0, 210]            # a number for Song(...)
    kept = db.adapt_uploaded_csv(raw, fill_duration=False)
    assert kept["duration"].tolist() == [225.0, None]
    db.import_tracks(kept)
    with __import__("sqlite3").connect(db.DB_PATH) as conn:
        stored = dict(conn.execute("select track_title, duration from tracks"))
    assert stored == {"A": 225.0, "B": None}                                           # B is unknown, not 3:30
    assert {s.name: s.duration for s in db.load_songs_from_db()}["B"] == 210           # the app still assumes 3:30
