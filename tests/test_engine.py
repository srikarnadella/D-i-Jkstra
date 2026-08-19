import random
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Song, SCORE_JITTER
from setlist_engine import (
    score_track, smoothest_setlist, find_harmonic_path,
    _bpm_compatible, build_segment_graph,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _song(name, key, bpm, genre="house"):
    return Song(name=name, artist="Test", genre=genre, bpm=bpm, key=key)


HARMONIC_CHAIN = [
    _song("A", "8A", 128),
    _song("B", "8B", 130),   # relative of 8A — harmonic
    _song("C", "9A", 126),   # +1 from 8A — harmonic
    _song("D", "7A", 124),   # -1 from 8A — harmonic
    _song("E", "1B", 140),   # non-harmonic with 8A
]


# ── score_track ───────────────────────────────────────────────────────────────

class TestScoreTrack:
    def test_excluded_genre_scores_zero(self):
        # rave excludes "pop"; verify the exclusion actually zeroes the score
        row = {"bpm": 128, "genre": "pop"}
        assert score_track(row, "rave") == 0.0

    def test_bpm_bonus_applied(self):
        row = {"bpm": 130, "genre": "house"}
        rng = random.Random(0)
        score = score_track(row, "kick back", rng=rng)
        assert score >= 2.0  # bpm_bonus=2 for kick back range 120-135

    def test_genre_bonus_applied(self):
        row = {"bpm": 132, "genre": "techno"}
        rng = random.Random(0)
        score = score_track(row, "rave", rng=rng)
        assert score >= 4.0  # bpm_bonus=2 + genre_bonus techno=2

    def test_seed_reproducibility(self):
        row = {"bpm": 128, "genre": "house"}
        score1 = score_track(row, "house", rng=random.Random(42))
        score2 = score_track(row, "house", rng=random.Random(42))
        assert score1 == score2

    def test_no_seed_adds_jitter(self):
        row = {"bpm": 128, "genre": "house"}
        scores = [score_track(row, "house") for _ in range(50)]
        assert len(set(scores)) > 1, "Without seed, scores should vary"

    def test_score_bounded_by_jitter(self):
        row = {"bpm": 130, "genre": "house"}
        rng = random.Random(0)
        # With rng.uniform(0, SCORE_JITTER) ≤ SCORE_JITTER always
        score = score_track(row, "house", rng=rng)
        assert score <= 2 + SCORE_JITTER + 1e-9  # genre_bonus house=2 + jitter


# ── smoothest_setlist ─────────────────────────────────────────────────────────

class TestSmoothestSetlist:
    def test_single_song_unchanged(self):
        songs = [_song("A", "8A", 128)]
        assert smoothest_setlist(songs) == songs

    def test_returns_same_songs(self):
        result = smoothest_setlist(list(HARMONIC_CHAIN))
        assert set(s.name for s in result) == set(s.name for s in HARMONIC_CHAIN)

    def test_length_preserved(self):
        result = smoothest_setlist(list(HARMONIC_CHAIN))
        assert len(result) == len(HARMONIC_CHAIN)

    def test_no_duplicates(self):
        result = smoothest_setlist(list(HARMONIC_CHAIN))
        names = [s.name for s in result]
        assert len(names) == len(set(names))

    def test_empty_list(self):
        assert smoothest_setlist([]) == []

    def test_starts_from_first_song(self):
        # smoothest_setlist always starts from index 0 (greedy from first song)
        songs = [_song("X", "8A", 128), _song("Y", "9A", 130)]
        result = smoothest_setlist(songs)
        assert result[0].name == "X"


# ── _bpm_compatible ───────────────────────────────────────────────────────────

class TestBpmCompatible:
    def test_direct_match(self):
        assert _bpm_compatible(128, 130) is True

    def test_direct_too_far(self):
        assert _bpm_compatible(128, 160) is False

    def test_octave_up(self):
        # 65 * 2 = 130, within BPM_OCTAVE_DELTA=8
        assert _bpm_compatible(65, 130) is True

    def test_octave_down(self):
        assert _bpm_compatible(130, 65) is True

    def test_octave_out_of_tolerance(self):
        # 60 * 2 = 120, but 128 is 8 away — exactly BPM_OCTAVE_DELTA boundary
        from models import BPM_OCTAVE_DELTA
        assert _bpm_compatible(60, 128) == (abs(60 * 2 - 128) <= BPM_OCTAVE_DELTA)


# ── build_segment_graph ───────────────────────────────────────────────────────

class TestBuildSegmentGraph:
    def _track(self, name, key, bpm):
        return {"track_title": name, "artist": "Test", "genre": "house",
                "bpm": bpm, "key": key, "vibe_score": 1.0}

    def test_returns_list_of_dicts(self):
        tracks = [self._track("A", "8A", 128), self._track("B", "8B", 130)]
        result = build_segment_graph(tracks, 600)
        assert isinstance(result, list)
        assert all(isinstance(t, dict) for t in result)

    def test_empty_input(self):
        assert build_segment_graph([], 600) == []

    def test_respects_duration(self):
        from models import TRACK_DURATION_SECONDS
        tracks = [self._track(f"T{i}", "8A", 128) for i in range(20)]
        max_tracks = 3
        result = build_segment_graph(tracks, max_tracks * TRACK_DURATION_SECONDS)
        assert len(result) <= max_tracks

    def test_no_duplicate_tracks(self):
        tracks = [self._track(n, k, b) for n, k, b in [
            ("A", "8A", 128), ("B", "8B", 130), ("C", "9A", 126)
        ]]
        result = build_segment_graph(tracks, 3600)
        titles = [t["track_title"] for t in result]
        assert len(titles) == len(set(titles)), "build_segment_graph should not repeat tracks"
