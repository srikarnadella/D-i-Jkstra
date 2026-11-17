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


# ── Opus backlog: identity, octave cost, time budget, energy curve, analysis ──

from models import TRACK_DURATION_SECONDS, effective_bpm_delta, song_id
from setlist_engine import (
    transition_cost, generate_setlist, energy_target, setlist_quality,
    harmonic_orphans, key_gaps, cluster_songs, start_offsets,
)


def _s(name, key, bpm, artist="Test", duration=TRACK_DURATION_SECONDS, genre="house"):
    return Song(name, artist, genre, bpm, key, duration)


class TestSongIdentity:
    def test_same_title_different_artists_are_distinct(self):
        a1 = _s("Intro", "8A", 128, artist="X")
        a2 = _s("Intro", "8B", 130, artist="Y")
        b = _s("Outro", "9B", 131)
        path = find_harmonic_path([a1, a2, b], song_id(a1), song_id(b))
        assert path is not None and path[0] == a1 and path[-1] == b
        assert a2 in path  # 8A → 9B is not harmonic, so it must route via the other "Intro"


class TestOctaveAwareCost:
    def test_half_time_is_free(self):
        assert effective_bpm_delta(70, 140) == 0
        assert transition_cost(70, "8A", 140, "8A") == 0

    def test_dijkstra_prefers_half_time_edge(self):
        src, dst = _s("A", "8A", 70), _s("B", "8A", 140)
        detour = _s("C", "8A", 92)  # direct-compatible with A (22 BPM) but costs more
        path = find_harmonic_path([src, dst, detour], song_id(src), song_id(dst))
        assert [s.name for s in path] == ["A", "B"]


class TestTimeBudget:
    LIB = [_s(f"T{i}", k, 124 + i % 5, duration=200) for i, k in
           enumerate(["8A", "8B", "9A", "9B", "7A", "7B", "8A", "9A", "10A", "6A", "8B", "9B"])]

    def test_respects_per_track_durations(self):
        tracks = [{"key": "8A", "bpm": 128, "duration": 100}, {"key": "8A", "bpm": 128, "duration": 300},
                  {"key": "8A", "bpm": 128, "duration": 100}]
        result = build_segment_graph(tracks, 250)
        assert sum(t["duration"] for t in result) <= 250

    def test_pins_and_bridges_fit_window(self):
        opener = _s("Open", "1A", 124, duration=200)   # far from the pool's keys → needs bridges
        closer = _s("Close", "3B", 126, duration=200)
        bridge = [_s(f"Br{i}", k, 125, duration=200) for i, k in enumerate(["2A", "3A", "4A", "5A", "6A", "4B"])]
        lib = self.LIB + bridge + [opener, closer]
        budget = 2000
        result = generate_setlist(lib, "house", budget, opener=opener, closer=closer, rng=random.Random(1))
        assert result[0] == opener and result[-1] == closer
        assert sum(s.duration for s in result) <= budget
        assert len({song_id(s) for s in result}) == len(result), "no song may repeat"

    def test_exclude_ids(self):
        banned = {song_id(s) for s in self.LIB[:6]}
        result = generate_setlist(self.LIB, "house", 3000, exclude_ids=banned, rng=random.Random(1))
        assert result and not banned & {song_id(s) for s in result}

    def test_start_offsets(self):
        assert start_offsets([_s("a", "8A", 1, duration=100), _s("b", "8A", 1, duration=50)]) == [0, 100]


class TestEnergyCurve:
    def test_interpolation(self):
        curve = [(0, 100), (0.5, 120), (1, 110)]
        assert energy_target(curve, 0) == 100
        assert energy_target(curve, 0.25) == 110
        assert energy_target(curve, 1.5) == 110

    def test_curve_steers_toward_targets(self):
        # Same key and BPM everywhere, so only energy vs the curve decides. Ramp 3 → 9.
        tracks = [{"key": "8A", "bpm": 128, "duration": 100, "energy": e} for e in (9, 3, 6, 8, 4)]
        result = build_segment_graph(tracks, 500, energy_curve=[(0, 3), (1, 9)])
        energies = [t["energy"] for t in result]
        assert energies == sorted(energies), energies

    def test_unrated_tracks_use_bpm_estimate(self):
        tracks = [{"key": "8A", "bpm": b, "duration": 100} for b in (135, 95, 115)]
        result = build_segment_graph(tracks, 300, energy_curve=[(0, 9), (1, 3)])
        assert [t["bpm"] for t in result] == [135, 115, 95]


class TestAnalysis:
    def test_quality_none_for_single(self):
        assert setlist_quality([_s("a", "8A", 128)]) is None

    def test_quality_perfect(self):
        q = setlist_quality([_s("a", "8A", 128), _s("b", "8A", 128)])
        assert q["quality"] == 100 and q["pct_harmonic"] == 1

    def test_orphans(self):
        lonely = _s("Lonely", "1A", 128)
        pair = [_s("P", "8A", 128), _s("Q", "8B", 128)]
        assert harmonic_orphans(pair + [lonely]) == {song_id(lonely)}

    def test_key_gaps_emptiest_first(self):
        gaps = key_gaps([_s("a", "8A", 128)] * 3, top=24)
        assert gaps[-1] == ("8A", 3) and gaps[0][1] == 0

    def test_cluster_key_wheel_wraps(self):
        # 12A and 1A are neighbors on the wheel — they must cluster together, apart from 6A.
        songs = ([_s(f"w{i}", "12A", 128) for i in range(5)] + [_s(f"x{i}", "1A", 128) for i in range(5)]
                 + [_s(f"y{i}", "6A", 128) for i in range(5)])
        df = cluster_songs(songs, 2)
        c = dict(zip(df["name"], df["cluster"]))
        assert c["w0"] == c["x0"] != c["y0"]


# ── Editing helpers ───────────────────────────────────────────────────────────

from setlist_engine import move_track, swap_candidates, insert_bridge


class TestEditing:
    SET = [_s("A", "8A", 126), _s("B", "8B", 127), _s("C", "9B", 128)]

    def test_move_track(self):
        assert [s.name for s in move_track(self.SET, 0, 1)] == ["B", "A", "C"]
        assert [s.name for s in move_track(self.SET, 2, -2)] == ["C", "A", "B"]

    def test_move_track_clamps(self):
        assert move_track(self.SET, 0, -5) == self.SET
        assert move_track(self.SET, 2, 5) == self.SET

    def test_swap_candidates_best_first_and_excludes_set(self):
        good = _s("Good", "8B", 127)      # fits between A and C... 
        bad = _s("Bad", "3A", 160)
        ranked = swap_candidates(self.SET + [good, bad], self.SET, 1, n=2)
        assert [s.name for s, _ in ranked] == ["Good", "Bad"]
        assert ranked[0][1] < ranked[1][1]
        assert all(s.name not in "ABC" for s, _ in ranked)

    def test_swap_candidates_follows_curve(self):
        lo, hi = _s("Lo", "8A", 120), _s("Hi", "8A", 130)
        ranked = swap_candidates([lo, hi], [_s("X", "8A", 125)], 0, n=2,
                                 energy_curve=[(0, 130), (1, 130)])
        assert ranked[0][0].name == "Hi"

    def test_insert_bridge(self):
        a, b = _s("A", "8A", 126), _s("B", "10A", 128)       # two steps apart on the wheel
        mid = _s("Mid", "9A", 127)
        out = insert_bridge([a, b, mid], [a, b], 1)
        assert [s.name for s in out] == ["A", "Mid", "B"]

    def test_insert_bridge_none_when_already_compatible(self):
        a, b = _s("A", "8A", 126), _s("B", "8B", 127)
        assert insert_bridge([a, b], [a, b], 1) is None
        assert insert_bridge([a, b], [a, b], 0) is None



# ── Opus round 2: search, mix timing, style, live, regenerate ────────────────

from models import key_compat_label
from setlist_engine import (
    mix_points, play_times, style_bonuses, regenerate_unlocked, next_track_suggestions,
    harmonic_graph, _key_move,
)


def _valid(setlist):
    return all(key_compat_label(a.key, b.key) in ("Same", "Harmonic") for a, b in zip(setlist, setlist[1:]))


WHEEL = [_s(f"W{i}{m}", f"{i}{m}", 120 + (i % 4), duration=180) for i in range(1, 13) for m in "AB"]


class TestSearch:
    @pytest.mark.parametrize("search", ["greedy", "beam"])
    def test_both_searches_fill_time_harmonically(self, search):
        result = generate_setlist(WHEEL, "house", 180 * 10, rng=random.Random(3), search=search)
        assert len(result) == 10 and _valid(result)
        assert len({song_id(s) for s in result}) == 10

    def test_anchored_segment_starts_and_ends_on_anchors(self):
        rows = [s._asdict() for s in WHEEL]
        left, right = _s("L", "1A", 121)._asdict(), _s("R", "5A", 121)._asdict()
        out = build_segment_graph(rows, 180 * 3, start_after=left, end_before=right)
        keys = ["1A"] + [r["key"] for r in out] + ["5A"]
        assert len(out) == 3 and _valid([_s(k, k, 121) for k in keys]), keys


class TestMixPoints:
    def test_default_blend_is_32_bars(self):
        s = _s("a", "8A", 120, duration=300)
        assert mix_points(s) == (0.0, 300 - 32 * 4 * 60 / 120)

    def test_cues_set_mix_points(self):
        s = _s("a", "8A", 120, duration=300)
        cues = [{"num": 0, "start_seconds": 15.0}, {"num": -1, "start_seconds": 100.0},
                {"num": -1, "start_seconds": 250.0}]
        assert mix_points(s, cues) == (15.0, 250.0)   # 100 s memory cue is before 60% → ignored

    def test_play_time_fits_more_tracks(self):
        full = generate_setlist(WHEEL, "house", 1800, rng=random.Random(1))
        pt = play_times(WHEEL)
        blended = generate_setlist(WHEEL, "house", 1800, rng=random.Random(1), play_time=pt)
        assert len(blended) > len(full)
        assert sum(pt[song_id(s)] for s in blended) <= 1800


class TestStyle:
    def test_played_non_harmonic_pair_becomes_reachable_and_cheap(self):
        a, b = _s("A", "1A", 128), _s("B", "7B", 128)      # clash on the wheel
        style = style_bonuses({(song_id(a), song_id(b)): 5})
        assert find_harmonic_path([a, b], song_id(a), song_id(b)) is None
        assert [s.name for s in find_harmonic_path([a, b], song_id(a), song_id(b), style)] == ["A", "B"]
        assert harmonic_graph([a, b], style).cost(song_id(a), song_id(b)) < transition_cost(128, "1A", 128, "7B")

    def test_bonus_has_diminishing_returns(self):
        b = style_bonuses({("x", "y"): 1, ("x", "z"): 100})
        assert b[("x", "z")] < 100 * b[("x", "y")]


class TestRegenerate:
    def test_locked_tracks_keep_position_and_set_stays_harmonic(self):
        base = generate_setlist(WHEEL, "house", 180 * 8, rng=random.Random(5))
        out = regenerate_unlocked(WHEEL, base, {0, 4}, "house", rng=random.Random(9))
        assert out[0] == base[0]
        assert base[4] in out
        assert len({song_id(s) for s in out}) == len(out)
        assert sum(s.duration for s in out) <= sum(s.duration for s in base)

    def test_no_locks_refills_everything_within_time(self):
        base = WHEEL[:5]
        out = regenerate_unlocked(WHEEL, base, set(), "house", rng=random.Random(2))
        assert out and sum(s.duration for s in out) <= sum(s.duration for s in base) and _valid(out)


class TestLive:
    LIB = [_s("Same", "8A", 124), _s("Up", "8A", 128), _s("Down", "8A", 120),
           _s("Boost", "3A", 124), _s("Clash", "2B", 124), _s("Played", "8A", 124)]
    NOW = _s("Now", "8A", 124)

    def _names(self, direction):
        return [s.name for s, _, _ in next_track_suggestions(
            self.LIB, self.NOW, {song_id(self.LIB[-1])}, direction)]

    def test_hold_prefers_same_energy(self):
        assert self._names("hold")[0] == "Same"

    def test_push_and_cool_follow_direction(self):
        assert self._names("push")[0] == "Up"
        assert self._names("cool")[0] == "Down"

    def test_boost_only_when_pushing_and_never_played_or_clashing(self):
        assert "Boost" in self._names("push") and "Boost" not in self._names("hold")
        for d in ("cool", "hold", "push"):
            assert "Clash" not in self._names(d) and "Played" not in self._names(d)

    def test_reasons(self):
        top = next_track_suggestions(self.LIB, self.NOW, direction="push")
        reasons = dict((s.name, r) for s, _, r in top)
        assert "+7 energy boost" in reasons["Boost"] and "+4.0 BPM" in reasons["Up"]

    def test_rated_energy_beats_bpm_estimate(self):
        # Faster BPM but rated slightly calmer → it's the gentle cool-down pick.
        now = self.NOW._replace(energy=7)
        calm = _s("CalmFast", "8A", 126)._replace(energy=6.5)
        mid = _s("Mid", "8A", 124)._replace(energy=7)
        top = next_track_suggestions([calm, mid], now, direction="cool")
        assert top[0][0].name == "CalmFast"

    def test_cool_down_is_gradual(self):
        now = self.NOW._replace(energy=7)
        crash, gentle = _s("Crash", "8A", 124)._replace(energy=2), _s("Gentle", "8A", 124)._replace(energy=6.5)
        assert next_track_suggestions([crash, gentle], now, direction="cool")[0][0].name == "Gentle"

    def test_key_moves(self):
        assert _key_move("8A", "3A") == "+7 energy boost" and _key_move("8A", "7A") == "−1 key"
        assert _key_move("8A", "8B") == "relative key" and _key_move("8A", "2B") is None


def test_regenerate_brings_new_songs():
    base = generate_setlist(WHEEL, "house", 180 * 6, rng=random.Random(5))
    out = regenerate_unlocked(WHEEL, base, {0}, "house", rng=random.Random(9))
    old_unlocked = {song_id(s) for s in base[1:]}
    assert out[0] == base[0] and not old_unlocked & {song_id(s) for s in out[1:]}



# ── Indexed neighbors must equal the brute-force definition ───────────────────

from setlist_engine import harmonic_neighbors, _compatible, HarmonicGraph


def _brute(bpm, key):
    return [{j: transition_cost(bpm[i], key[i], bpm[j], key[j])
             for j in range(len(bpm)) if j != i and _compatible(bpm[i], key[i], bpm[j], key[j])}
            for i in range(len(bpm))]


@pytest.mark.parametrize("seed,lo,hi", [(0, 60, 175), (1, 60, 175), (2, 60, 175), (3, 20, 70)])
def test_indexed_neighbors_equal_brute_force(seed, lo, hi):
    rng = random.Random(seed)
    slots = [f"{n}{m}" for n in range(1, 13) for m in "AB"] + ["", "bad"]
    # one-decimal BPMs hit the exact window boundaries often; 20–70 BPM makes the direct and
    # half/double-time windows overlap (the dedupe path)
    bpm = [round(rng.uniform(lo, hi), 1) for _ in range(400)]
    key = [rng.choice(slots) for _ in range(400)]
    fast = harmonic_neighbors(bpm, key, k=None)
    slow = _brute(bpm, key)
    assert [set(r) for r in fast] == [set(r) for r in slow]
    assert all(abs(fast[i][j] - slow[i][j]) < 1e-9 for i in range(400) for j in slow[i])


def test_k_keeps_cheapest_and_played():
    bpm, key = [128] + [128 + d for d in range(1, 21)], ["8A"] * 21
    ids = [(str(i), "x") for i in range(21)]
    row = harmonic_neighbors(bpm, key, ids, style={(ids[0], ids[20]): 1.0}, k=5)[0]
    assert set(row) == {1, 2, 3, 4, 5, 20}


def test_dijkstra_matches_hand_computed_route():
    s = [_s("A", "8A", 120), _s("B", "9A", 121), _s("C", "10A", 122), _s("D", "10A", 140)]
    G = HarmonicGraph(s)
    assert [x.name for x in G.shortest_path(song_id(s[0]), song_id(s[2]))] == ["A", "B", "C"]
    assert G.shortest_path(song_id(s[0]), song_id(s[2]), exclude={song_id(s[1])}) is None
    assert G.shortest_path(song_id(s[0]), ("nope", "x")) is None
