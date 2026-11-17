import heapq
import math
import random
from itertools import accumulate

import numpy as np
import pandas as pd

from models import (
    Song,
    TRACK_DURATION_SECONDS,
    MAX_HARMONIC_BPM_DELTA,
    BPM_OCTAVE_DELTA,
    SCORE_JITTER,
    VIBE_CONFIG,
    parse_key,
    get_harmonic_neighbors,
    key_compat_label,
    effective_bpm_delta,
    song_id,
    track_energy,
    ENERGY_WEIGHT,
    STYLE_WEIGHT,
    BLEND_BARS,
)

BEAM_WIDTH = 40
# ponytail: per track keep only the MAX_NEIGHBORS cheapest compatible transitions (+ all played
# ones). Exact while a track has ≤ that many partners (true for ~500-track libraries); at 20k
# tracks it keeps the graph ~1M edges instead of ~50M. Raise if bridges start looking odd.
MAX_NEIGHBORS = 60
MAX_STARTS = 500        # openers tried by the greedy search (all of them for libraries ≤ 500)


# ── Transition primitives ─────────────────────────────────────────────────────

def _bpm_compatible(bpm1: float, bpm2: float) -> bool:
    """True if two BPMs are within MAX_HARMONIC_BPM_DELTA, or within BPM_OCTAVE_DELTA
    of each other when one is doubled (handles half-time / double-time mixing)."""
    direct = abs(bpm1 - bpm2) <= MAX_HARMONIC_BPM_DELTA
    octave_up = abs(bpm1 * 2 - bpm2) <= BPM_OCTAVE_DELTA
    octave_down = abs(bpm1 - bpm2 * 2) <= BPM_OCTAVE_DELTA
    return direct or octave_up or octave_down


def _key_compat_score(k1: str, k2: str) -> int:
    return {"Same": 0, "Harmonic": 1}.get(key_compat_label(k1, k2), 4)


def transition_cost(bpm1: float, key1: str, bpm2: float, key2: str, style_bonus: float = 0.0) -> float:
    """Single source of truth for how rough a transition is (lower = smoother).
    style_bonus (from style_bonuses()) lowers the cost of transitions you've actually played."""
    return max(0.0, effective_bpm_delta(bpm1, bpm2) + _key_compat_score(key1, key2) * 2 - style_bonus)


def _compatible(bpm1: float, key1: str, bpm2: float, key2: str) -> bool:
    return _norm_key(key2) in get_harmonic_neighbors(key1) and _bpm_compatible(bpm1, bpm2)


def style_bonuses(counts: dict, weight: float = STYLE_WEIGHT) -> dict:
    """{(from_id, to_id): play count} → {(from_id, to_id): cost bonus}. Diminishing returns via log."""
    return {pair: weight * math.log1p(c) for pair, c in counts.items() if c > 0}


def _norm_key(k) -> str:
    return str(k or "").strip().upper()


# ── Vibe scoring / energy curve ───────────────────────────────────────────────

def score_track(row: dict, vibe: str, rng: random.Random | None = None) -> float:
    bpm = row.get("bpm", 0) or 0
    genre = str(row.get("genre") or "").strip().lower()
    cfg = VIBE_CONFIG.get(vibe.lower(), {})

    if any(g in genre for g in cfg.get("excluded_genres", [])):
        return 0

    score = 0.0
    bpm_range = cfg.get("bpm_range")
    if bpm_range and bpm_range[0] <= bpm <= bpm_range[1]:
        score += cfg.get("bpm_bonus", 0)

    for keyword, bonus in cfg.get("genre_bonuses", {}).items():
        if keyword in genre:
            score += bonus

    _rng = rng or random
    score += _rng.uniform(0, SCORE_JITTER)
    return score


def energy_target(curve: list[tuple[float, float]], t: float) -> float:
    """Target energy (1–10) at position t (0→1) through the set, linearly interpolated."""
    t = min(max(t, 0.0), 1.0)
    for (t0, b0), (t1, b1) in zip(curve, curve[1:]):
        if t <= t1:
            return b0 + (b1 - b0) * ((t - t0) / (t1 - t0) if t1 > t0 else 0)
    return curve[-1][1]


# ── Neighbor index ────────────────────────────────────────────────────────────

def harmonic_neighbors(
    bpm: list[float], key: list[str], ids: list | None = None,
    style: dict | None = None, k: int | None = MAX_NEIGHBORS,
) -> list[dict[int, float]]:
    """For each track i: {j: transition_cost(i → j)} over compatible tracks (Camelot neighbor
    + _bpm_compatible), plus pairs in `style` (played transitions, any key, cost lowered).

    Indexed, not O(n²): tracks are bucketed by Camelot slot and sorted by BPM, so each track
    only looks at its 4 neighbor slots inside the direct and half/double-time BPM windows.
    Keeps the `k` cheapest harmonic partners per track (None = all); played pairs always kept.
    """
    n = len(bpm)
    b = np.asarray([float(x or 0) for x in bpm])
    keys = [_norm_key(x) for x in key]
    buckets: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for slot in {kk for kk in keys if parse_key(kk)[0] is not None}:
        idx = np.array([i for i in range(n) if keys[i] == slot])
        idx = idx[np.argsort(b[idx], kind="stable")]
        buckets[slot] = (idx, b[idx])

    played: dict[int, list[tuple[int, float]]] = {}
    if style and ids is not None:
        pos = {sid: i for i, sid in enumerate(ids)}
        for (fa, fb), bonus in style.items():
            if fa in pos and fb in pos and pos[fa] != pos[fb]:
                played.setdefault(pos[fa], []).append((pos[fb], bonus))

    # Vectorized pass: for every (source slot → target slot) pair, the BPM windows of all
    # sources at once (3 windows: direct, double-time, half-time) as index ranges into the target.
    eps = 1e-6
    ranges: list[list[tuple[np.ndarray, np.ndarray, float, int, int]]] = [[] for _ in range(n)]
    for src_slot, (src_idx, src_b) in buckets.items():
        for tgt_slot in get_harmonic_neighbors(src_slot):
            if tgt_slot not in buckets:
                continue
            tgt_idx, tgt_b = buckets[tgt_slot]
            pen = 0.0 if tgt_slot == src_slot else 2.0
            windows = ((src_b - MAX_HARMONIC_BPM_DELTA, src_b + MAX_HARMONIC_BPM_DELTA),
                       (2 * src_b - BPM_OCTAVE_DELTA, 2 * src_b + BPM_OCTAVE_DELTA),
                       ((src_b - BPM_OCTAVE_DELTA) / 2, (src_b + BPM_OCTAVE_DELTA) / 2))
            bounds = [(np.searchsorted(tgt_b, lo - eps), np.searchsorted(tgt_b, hi + eps, "right"))
                      for lo, hi in windows]
            for w, (los, his) in enumerate(bounds):
                for i, lo, hi in zip(src_idx.tolist(), los.tolist(), his.tolist()):
                    if hi > lo:
                        ranges[i].append((tgt_idx, tgt_b, pen, lo, hi))

    out: list[dict[int, float]] = []
    for i in range(n):
        row: dict[int, float] = {}
        if ranges[i]:
            bi = b[i]
            js = np.concatenate([t[lo:hi] for t, _, _, lo, hi in ranges[i]])
            xs = np.concatenate([tb[lo:hi] for _, tb, _, lo, hi in ranges[i]])
            pens = np.concatenate([np.full(hi - lo, p) for _, _, p, lo, hi in ranges[i]])
            # exact same predicate as _bpm_compatible (the windows above only narrow the search)
            ok = ((js != i) & ((np.abs(bi - xs) <= MAX_HARMONIC_BPM_DELTA)
                               | (np.abs(bi * 2 - xs) <= BPM_OCTAVE_DELTA)
                               | (np.abs(bi - xs * 2) <= BPM_OCTAVE_DELTA)))
            js, xs, pens = js[ok], xs[ok], pens[ok]
            costs = np.minimum(np.minimum(np.abs(bi - xs), np.abs(bi * 2 - xs)), np.abs(bi - xs * 2)) + pens
            # The direct and half/double-time windows only overlap (→ duplicate targets) for
            # tempos ≤ 2·MAX_HARMONIC_BPM_DELTA + BPM_OCTAVE_DELTA (58 BPM); skip the sort otherwise.
            if bi <= 2 * MAX_HARMONIC_BPM_DELTA + BPM_OCTAVE_DELTA and len(js) > 1:
                js, first = np.unique(js, return_index=True)
                costs = costs[first]
            if k is not None and len(js) > k:
                keep = np.argpartition(costs, k)[:k]
                js, costs = js[keep], costs[keep]
            row = dict(zip(js.tolist(), costs.tolist()))
        for j, bonus in played.get(i, ()):
            row[j] = transition_cost(bi if ranges[i] else b[i], keys[i], b[j], keys[j], bonus)
        out.append(row)
    return out


class HarmonicGraph:
    """Adjacency-list harmonic graph over songs (nodes = song_id), with Dijkstra."""

    def __init__(self, songs: list[Song], style: dict | None = None, k: int | None = MAX_NEIGHBORS):
        self.songs = list(songs)
        self.ids = [song_id(s) for s in self.songs]
        self.pos = {sid: i for i, sid in enumerate(self.ids)}
        self.adj = harmonic_neighbors([s.bpm for s in self.songs], [s.key for s in self.songs],
                                      self.ids, style, k)

    def __contains__(self, sid) -> bool:
        return sid in self.pos

    def cost(self, a, b) -> float | None:
        return self.adj[self.pos[a]].get(self.pos[b]) if a in self.pos and b in self.pos else None

    def out_degree(self, sid) -> int:
        return len(self.adj[self.pos[sid]])

    def shortest_path(self, source_id, target_id, exclude=frozenset()) -> list[Song] | None:
        """Dijkstra by transition cost, skipping `exclude` ids (endpoints always allowed)."""
        if source_id not in self.pos or target_id not in self.pos:
            return None
        src, dst = self.pos[source_id], self.pos[target_id]
        blocked = {self.pos[x] for x in exclude if x in self.pos} - {src, dst}
        dist, prev, heap = {src: 0.0}, {}, [(0.0, src)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == dst:
                path = [u]
                while u in prev:
                    u = prev[u]
                    path.append(u)
                return [self.songs[i] for i in reversed(path)]
            if d > dist.get(u, math.inf):
                continue
            for v, c in self.adj[u].items():
                if v in blocked:
                    continue
                nd = d + c
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(heap, (nd, v))
        return None


# ── Mix points / play time ────────────────────────────────────────────────────

def mix_points(song: Song, cues: list[dict] | None = None) -> tuple[float, float]:
    """(mix_in, mix_out) in seconds. mix_in = first cue in the first 40% of the track (else 0);
    mix_out = last memory cue past 60% (else BLEND_BARS bars before the end at the track's BPM)."""
    dur = float(song.duration)
    cues = sorted(cues or [], key=lambda c: c["start_seconds"])
    early = [c["start_seconds"] for c in cues if c["start_seconds"] <= 0.4 * dur]
    late = [c["start_seconds"] for c in cues if c["num"] < 0 and c["start_seconds"] >= 0.6 * dur]
    mix_in = early[0] if early else 0.0
    if late:
        mix_out = late[-1]
    else:
        mix_out = dur - BLEND_BARS * 4 * 60 / song.bpm if song.bpm else dur
    if mix_out <= mix_in:
        mix_out = dur
    return mix_in, min(mix_out, dur)


def play_times(songs: list[Song], cues_by_id: dict | None = None) -> dict:
    """{song_id: seconds from this track's mix-in until the next track takes over}."""
    cues_by_id = cues_by_id or {}
    return {song_id(s): max(1.0, (lambda io: io[1] - io[0])(mix_points(s, cues_by_id.get(song_id(s)))))
            for s in songs}


def _pt(s: Song, play_time: dict | None) -> float:
    return (play_time or {}).get(song_id(s), s.duration)


# ── Setlist building ──────────────────────────────────────────────────────────

def _row(s: Song, play_time: dict | None = None, **extra) -> dict:
    return {**s._asdict(), "play_time": _pt(s, play_time), **extra}


def _song(r: dict) -> Song:
    return Song(**{f: r[f] for f in Song._fields})


def build_segment_graph(
    tracks: list[dict],
    total_duration_seconds: float,
    energy_curve: list[tuple[float, float]] | None = None,
    *,
    style: dict | None = None,
    start_after: dict | None = None,
    end_before: dict | None = None,
    curve_window: tuple[float, float] | None = None,
    search: str = "auto",
    beam_width: int = BEAM_WIDTH,
) -> list[dict]:
    """Longest time-fitting harmonic path through `tracks`.

    Each step costs transition_cost (minus style bonus) + |energy − curve target| × ENERGY_WEIGHT.
    Time used per track = `play_time` (mix-in → mix-out), else `duration`.
    search="greedy": up to MAX_STARTS fitting tracks tried as opener, extend by cheapest neighbor.
    search="beam": keep the `beam_width` cheapest partial paths per step.
    search="auto": greedy while every track can be tried as an opener (≤ MAX_STARTS), else beam —
    on a 20k-track library beam fits the energy curve ~5× better at the same quality.
    Both finish with a 2-opt pass. Best = (joins `end_before`, most time filled, lowest cost).

    start_after / end_before: fixed tracks on either side (lock-and-regenerate gaps);
    curve_window=(offset, whole_set_seconds) places this segment on the set's energy curve.
    """
    n = len(tracks)
    if n == 0:
        return []
    if search == "auto":
        search = "greedy" if n <= MAX_STARTS else "beam"
    total = float(total_duration_seconds)
    style = style or {}
    rows = list(tracks) + [r for r in (start_after, end_before) if r is not None]
    bpm = [float(t.get("bpm") or 0) for t in rows]
    key = [_norm_key(t.get("key")) for t in rows]
    dur = [float(t.get("play_time") or t.get("duration") or TRACK_DURATION_SECONDS) for t in rows]
    energy = [track_energy(t.get("bpm"), t.get("energy")) for t in rows]
    ids = [(t.get("name"), t.get("artist")) for t in rows]
    S = n if start_after is not None else None                     # anchor indices
    E = (n + (start_after is not None)) if end_before is not None else None

    def edge_cost(i: int, j: int) -> float | None:
        bonus = style.get((ids[i], ids[j]), 0.0)
        if not bonus and not _compatible(bpm[i], key[i], bpm[j], key[j]):
            return None
        return transition_cost(bpm[i], key[i], bpm[j], key[j], bonus)

    neighbors = [list(row.items()) for row in harmonic_neighbors(bpm[:n], key[:n], ids[:n], style)]
    edges = {(i, j): c for i in range(n) for j, c in neighbors[i]}

    offset, whole = curve_window or (0.0, total)

    def curve_err(j: int, elapsed: float) -> float:
        if not energy_curve or whole <= 0:
            return 0.0
        return abs(energy[j] - energy_target(energy_curve, (offset + elapsed) / whole)) * ENERGY_WEIGHT

    start_cost = {}
    for j in range(n):
        if dur[j] > total:
            continue
        if S is None:
            start_cost[j] = curve_err(j, 0)
        elif (c := edge_cost(S, j)) is not None:
            start_cost[j] = c + curve_err(j, 0)
    end_cost = {j: edge_cost(j, E) for j in range(n)} if E is not None else {}

    # Goal awareness for an anchored end: hops from each track to the end anchor (BFS
    # backwards), and a penalty for moves that leave too few slots to still get there.
    hops: dict[int, int] = {}
    if E is not None:
        incoming: dict[int, list[int]] = {}
        for (a, b) in edges:
            incoming.setdefault(b, []).append(a)
        frontier = [j for j, c in end_cost.items() if c is not None]
        hops = {j: 1 for j in frontier}
        while frontier:
            nxt_frontier = []
            for b in frontier:
                for a in incoming.get(b, []):
                    if a not in hops:
                        hops[a] = hops[b] + 1
                        nxt_frontier.append(a)
            frontier = nxt_frontier
    avg_dur = sum(dur[:n]) / n

    def goal_penalty(j: int, elapsed_after: float) -> float:
        if E is None:
            return 0.0
        slots_left = int((total - elapsed_after) // avg_dur)
        return 1000.0 * max(0, hops.get(j, 10**6) - 1 - slots_left)

    for j in start_cost:
        start_cost[j] += goal_penalty(j, dur[j])

    def rank(path: list[int], elapsed: float, cost: float) -> tuple:
        if E is None:
            return (True, elapsed, -cost)
        tail = end_cost[path[-1]]
        return (tail is not None, elapsed, -(cost + (tail or 0)))

    def path_cost(path: list[int]) -> float | None:
        """Full cost of a path, or None if any transition isn't an edge."""
        cost, elapsed = 0.0, 0.0
        if S is not None:
            c = edge_cost(S, path[0])
            if c is None:
                return None
            cost += c
        for a, b in zip(path, path[1:]):
            c = edges.get((a, b))
            if c is None:
                return None
            cost += c
        for j in path:
            cost += curve_err(j, elapsed)
            elapsed += dur[j]
        if E is not None and end_cost[path[-1]] is not None:
            cost += end_cost[path[-1]]
        return cost

    best_path: list[int] = []
    best_rank: tuple | None = None

    def consider(path, elapsed, cost):
        nonlocal best_path, best_rank
        r = rank(path, elapsed, cost)
        if best_rank is None or r > best_rank:
            best_path, best_rank = list(path), r

    if search == "beam":
        beam = sorted((c, dur[j], [j]) for j, c in start_cost.items())[:beam_width * 4]
        while beam:
            nxt = []
            for cost, elapsed, path in beam:
                consider(path, elapsed, cost)
                seen = set(path)
                for j, c in neighbors[path[-1]]:
                    if j not in seen and elapsed + dur[j] <= total:
                        nxt.append((cost + c + curve_err(j, elapsed) + goal_penalty(j, elapsed + dur[j]),
                                    elapsed + dur[j], path + [j]))
            nxt.sort(key=lambda st: st[0])
            beam = nxt[:beam_width]
    else:
        # ponytail: multi-start greedy is O(n · set_len · degree) and myopic; beam search is the upgrade
        starts = sorted(start_cost.items(), key=lambda kv: kv[1])[:MAX_STARTS]
        for start, c0 in starts:
            path, visited = [start], {start}
            elapsed, cost = dur[start], c0
            consider(path, elapsed, cost)
            while True:
                options = [
                    (c + curve_err(j, elapsed) + goal_penalty(j, elapsed + dur[j]), j)
                    for j, c in neighbors[path[-1]]
                    if j not in visited and elapsed + dur[j] <= total
                ]
                if not options:
                    break
                step_cost, j = min(options)
                path.append(j)
                visited.add(j)
                elapsed += dur[j]
                cost += step_cost
                if E is not None:            # anchored end: any prefix may be the best place to stop
                    consider(path, elapsed, cost)
            consider(path, elapsed, cost)

    # 2-opt polish: reverse sub-runs when that lowers total cost and every transition stays valid.
    if len(best_path) > 3:
        cur = path_cost(best_path)
        improved = cur is not None
        while improved:
            improved = False
            for i in range(len(best_path) - 1):
                for k in range(i + 1, len(best_path)):
                    cand = best_path[:i] + best_path[i:k + 1][::-1] + best_path[k + 1:]
                    c = path_cost(cand)
                    if c is not None and c < cur - 1e-9 and (E is None or end_cost[cand[-1]] is not None
                                                            or end_cost[best_path[-1]] is None):
                        best_path, cur, improved = cand, c, True

    return [rows[i] for i in best_path]


def harmonic_graph(songs: list[Song], style: dict | None = None) -> HarmonicGraph:
    """Harmonic graph of `songs` (plus pairs you've played, if `style` is given)."""
    return HarmonicGraph(songs, style)


def shortest_harmonic_path(G: HarmonicGraph, source_id, target_id, exclude=frozenset()) -> list[Song] | None:
    """Dijkstra over a prebuilt harmonic_graph, skipping `exclude` ids (endpoints always allowed)."""
    return G.shortest_path(source_id, target_id, exclude)


def find_harmonic_path(songs: list[Song], source_id, target_id, style: dict | None = None) -> list[Song] | None:
    """Shortest harmonic path between two songs (ids = (name, artist)), or None if unreachable."""
    return shortest_harmonic_path(harmonic_graph(songs, style), source_id, target_id)


def _stitch(G: HarmonicGraph, opener: Song | None, middle: list[Song], closer: Song | None,
            blocked=frozenset()) -> list[Song]:
    """Wrap pinned opener/closer around the middle with Dijkstra bridges that never reuse a
    song (or use a `blocked` one)."""
    used = {song_id(s) for s in [opener, *middle, closer] if s} | set(blocked)
    seq = list(middle)
    if opener:
        if seq:
            bridge = shortest_harmonic_path(G, song_id(opener), song_id(seq[0]), exclude=used) or []
            inner = bridge[1:-1]
            used |= {song_id(s) for s in inner}
            seq = [opener, *inner, *seq]
        else:
            seq = [opener]
    if closer:
        if seq:
            bridge = shortest_harmonic_path(G, song_id(seq[-1]), song_id(closer), exclude=used) or []
            seq.extend(bridge[1:-1])
        seq.append(closer)
    return seq


def _scored_rows(library, vibe, *, skip=frozenset(), candidate_ids=None, bpm_range=None,
                 rng=None, play_time=None) -> list[dict]:
    """Vibe-scored rows (score > 0) for every eligible library song."""
    rows = []
    for s in library:
        sid = song_id(s)
        if (sid in skip or not s.key
                or (candidate_ids is not None and sid not in candidate_ids)
                or (bpm_range and not bpm_range[0] <= (s.bpm or 0) <= bpm_range[1])):
            continue
        score = score_track({"bpm": s.bpm, "genre": s.genre}, vibe, rng=rng)
        if score > 0:
            rows.append(_row(s, play_time, vibe_score=score))
    return rows


def _curve(vibe: str, use_energy_curve: bool):
    return VIBE_CONFIG.get(vibe.lower(), {}).get("energy_curve") if use_energy_curve else None


def generate_setlist(
    library: list[Song],
    vibe: str,
    total_duration_seconds: float,
    *,
    candidate_ids: set | None = None,
    exclude_ids: set = frozenset(),
    opener: Song | None = None,
    closer: Song | None = None,
    use_energy_curve: bool = True,
    bpm_range: tuple[float, float] | None = None,
    rng: random.Random | None = None,
    play_time: dict | None = None,
    style: dict | None = None,
    search: str = "auto",
    graph: HarmonicGraph | None = None,
) -> list[Song]:
    """Full pipeline: vibe-score → harmonic path (optionally following the vibe's energy
    curve) → stitch pinned opener/closer with bridges → trim to fit time.
    play_time: {song_id: seconds} from play_times() (mix-point timing); default = duration.
    style: from style_bonuses() — favors transitions you've played.
    graph: prebuilt harmonic_graph(library, style) to reuse for bridges (built if omitted)."""
    if opener and closer and song_id(opener) == song_id(closer):
        closer = None
    pinned = {song_id(s) for s in (opener, closer) if s}
    rows = _scored_rows(library, vibe, skip=pinned | set(exclude_ids), candidate_ids=candidate_ids,
                        bpm_range=bpm_range, rng=rng, play_time=play_time)
    pin_time = sum(_pt(s, play_time) for s in (opener, closer) if s)
    middle = [_song(r) for r in build_segment_graph(
        rows, max(0.0, total_duration_seconds - pin_time), _curve(vibe, use_energy_curve),
        style=style, search=search)]
    if not pinned:
        return middle

    # Bridges add time the middle didn't budget for — drop middle tracks from the end until it fits.
    G = graph or harmonic_graph(library, style)
    blocked = set(exclude_ids) - pinned
    while True:
        seq = _stitch(G, opener, middle, closer, blocked)
        if not middle or sum(_pt(s, play_time) for s in seq) <= total_duration_seconds:
            return seq
        middle = middle[:-1]


def regenerate_unlocked(
    library: list[Song],
    setlist: list[Song],
    locked: set[int],
    vibe: str,
    *,
    use_energy_curve: bool = True,
    exclude_ids: set = frozenset(),
    rng: random.Random | None = None,
    play_time: dict | None = None,
    style: dict | None = None,
    search: str = "auto",
) -> list[Song]:
    """Keep tracks at `locked` positions, refill every gap between them with *different*
    songs (the old unlocked ones are only reused if a gap can't be filled otherwise). Each
    gap gets the time its old tracks used, starts harmonically from the locked track before
    it, ends into the locked track after it, and follows its stretch of the energy curve."""
    whole = sum(_pt(s, play_time) for s in setlist)
    locked = {i for i in locked if 0 <= i < len(setlist)}
    used = {song_id(setlist[i]) for i in locked}
    rows = _scored_rows(library, vibe, skip=used | set(exclude_ids), rng=rng, play_time=play_time)
    curve = _curve(vibe, use_energy_curve)
    replaced = {song_id(s) for k, s in enumerate(setlist) if k not in locked}

    out: list[Song] = []
    offset, i = 0.0, 0
    while i < len(setlist):
        if i in locked:
            out.append(setlist[i])
            offset += _pt(setlist[i], play_time)
            i += 1
            continue
        j = i
        while j < len(setlist) and j not in locked:
            j += 1
        budget = sum(_pt(s, play_time) for s in setlist[i:j])
        left = _row(out[-1], play_time) if out else None
        right = _row(setlist[j], play_time) if j < len(setlist) else None
        def fill_gap(avoid):
            return build_segment_graph(
                [r for r in rows if (r["name"], r["artist"]) not in used | avoid], budget, curve,
                style=style, start_after=left, end_before=right, curve_window=(offset, whole), search=search)
        fill = fill_gap(replaced) or fill_gap(set())
        fill_songs = [_song(r) for r in fill]
        used |= {song_id(s) for s in fill_songs}
        out.extend(fill_songs)
        offset += budget
        i = j
    return out


def smoothest_setlist(songs: list[Song], style: dict | None = None) -> list[Song]:
    """Greedy nearest-neighbor reordering from the first song, minimizing transition_cost."""
    if len(songs) < 2:
        return songs
    style = style or {}
    path, remaining = [songs[0]], list(songs[1:])
    while remaining:
        cur = path[-1]
        nxt = min(remaining, key=lambda s: transition_cost(
            cur.bpm, cur.key, s.bpm, s.key, style.get((song_id(cur), song_id(s)), 0.0)))
        path.append(nxt)
        remaining.remove(nxt)
    return path


# ── Editing a generated set ───────────────────────────────────────────────────

def move_track(setlist: list[Song], i: int, delta: int) -> list[Song]:
    """Move track i by delta positions (clamped to the set); returns a new list."""
    j = min(max(i + delta, 0), len(setlist) - 1)
    out = list(setlist)
    out.insert(j, out.pop(i))
    return out


def swap_candidates(
    library: list[Song],
    setlist: list[Song],
    i: int,
    n: int = 3,
    energy_curve: list[tuple[float, float]] | None = None,
    play_time: dict | None = None,
) -> list[tuple[Song, float]]:
    """Best replacements for slot i as (song, cost), lowest first. Cost = transition cost
    from the previous track + into the next one (+ energy distance from the curve target at
    that slot's position, if given). Songs already in the set are excluded."""
    used = {song_id(s) for s in setlist}
    prev = setlist[i - 1] if i > 0 else None
    nxt = setlist[i + 1] if i + 1 < len(setlist) else None
    times = [_pt(s, play_time) for s in setlist]
    pos = sum(times[:i]) / sum(times) if sum(times) else 0.0
    target = energy_target(energy_curve, pos) if energy_curve else None

    def cost(c: Song) -> float:
        v = 0.0
        if prev:
            v += transition_cost(prev.bpm, prev.key, c.bpm, c.key)
        if nxt:
            v += transition_cost(c.bpm, c.key, nxt.bpm, nxt.key)
        if target is not None:
            v += abs(track_energy(c.bpm, c.energy) - target) * ENERGY_WEIGHT
        return v

    ranked = sorted(((c, cost(c)) for c in library if song_id(c) not in used and c.key), key=lambda t: t[1])
    return ranked[:n]


def insert_bridge(library: list[Song], setlist: list[Song], i: int, style: dict | None = None,
                  graph: HarmonicGraph | None = None) -> list[Song] | None:
    """Insert Dijkstra bridge songs between track i-1 and i (the transition into slot i).
    None if there is no bridge to add (no path, or already directly compatible)."""
    if i < 1 or i >= len(setlist):
        return None
    a, b = setlist[i - 1], setlist[i]
    G = graph or harmonic_graph(library, style)
    path = shortest_harmonic_path(G, song_id(a), song_id(b), exclude={song_id(s) for s in setlist})
    if not path or len(path) <= 2:
        return None
    return setlist[:i] + path[1:-1] + setlist[i:]


# ── Live mode ─────────────────────────────────────────────────────────────────

LIVE_DIRECTIONS = {"cool": -0.5, "hold": 0.0, "push": 0.5}   # wanted energy change per track
LIVE_ENERGY_WEIGHT = 2 * ENERGY_WEIGHT  # direction must outweigh the BPM change it implies


def _key_move(k1: str, k2: str) -> str | None:
    """Human name for a Camelot move, or None if it isn't a recognized mixing move."""
    (n1, m1), (n2, m2) = parse_key(k1), parse_key(k2)
    if n1 is None or n2 is None:
        return None
    if n1 == n2:
        return "same key" if m1 == m2 else "relative key"
    if m1 != m2:
        return None
    step = (n2 - n1) % 12
    return {1: "+1 key", 11: "−1 key", 7: "+7 energy boost", 2: "+2 key boost"}.get(step)


def next_track_suggestions(
    library: list[Song],
    current: Song,
    played_ids: set = frozenset(),
    direction: str = "hold",
    n: int = 5,
    style: dict | None = None,
) -> list[tuple[Song, float, list[str]]]:
    """Ranked next tracks for live mode as (song, score, reasons), lowest score first.
    direction: "cool" / "hold" / "push" the energy. Pushing also allows the +7 / +2
    energy-boost key moves, which aren't Camelot neighbors."""
    want = LIVE_DIRECTIONS[direction]
    style = style or {}
    e0 = track_energy(current.bpm, current.energy)
    out = []
    for c in library:
        sid = song_id(c)
        if sid in played_ids or sid == song_id(current) or not c.key:
            continue
        move = _key_move(current.key, c.key)
        bonus = style.get((song_id(current), sid), 0.0)
        boost = direction == "push" and move in ("+7 energy boost", "+2 key boost")
        harmonic = move in ("same key", "relative key", "+1 key", "−1 key")
        if not _bpm_compatible(current.bpm, c.bpm) or not (harmonic or boost or bonus):
            continue
        de = track_energy(c.bpm, c.energy) - e0
        key_part = 0 if move == "same key" else 2 if (harmonic or boost) else 8
        delta = effective_bpm_delta(current.bpm, c.bpm)
        score = max(0.0, delta + key_part + abs(de - want) * LIVE_ENERGY_WEIGHT - bonus)

        reasons = [move] if move else []
        raw = (c.bpm or 0) - (current.bpm or 0)
        reasons.append("half/double-time" if delta < abs(raw) else f"{raw:+.1f} BPM")
        reasons.append(f"energy {de:+.1f}")
        if bonus:
            reasons.append("you've played this transition")
        out.append((c, score, reasons))
    out.sort(key=lambda t: t[1])
    return out[:n]


# ── Analysis ──────────────────────────────────────────────────────────────────

def start_offsets(setlist: list[Song], play_time: dict | None = None) -> list[float]:
    """Seconds from set start at which each track comes in."""
    return list(accumulate((_pt(s, play_time) for s in setlist), initial=0))[:-1]


def setlist_quality(setlist: list[Song], play_time: dict | None = None) -> dict | None:
    """Quality 0–100: 60% harmonic-transition rate + 40% BPM smoothness. None for < 2 tracks."""
    if len(setlist) < 2:
        return None
    pairs = list(zip(setlist, setlist[1:]))
    pct_harmonic = sum(key_compat_label(a.key, b.key) in ("Same", "Harmonic") for a, b in pairs) / len(pairs)
    avg_delta = sum(effective_bpm_delta(a.bpm, b.bpm) for a, b in pairs) / len(pairs)
    quality = pct_harmonic * 60 + (1 - min(avg_delta / 50, 1.0)) * 40
    return {
        "quality": max(0.0, min(100.0, quality)),
        "pct_harmonic": pct_harmonic,
        "avg_bpm_delta": avg_delta,
        "total_seconds": sum(_pt(s, play_time) for s in setlist),
    }


def compatibility(songs: list[Song], a: Song, b: Song, graph: HarmonicGraph | None = None) -> dict:
    """0–100 mixability of two songs: key (40) + BPM (30) + graph distance (30)."""
    label = key_compat_label(a.key, b.key)
    delta = effective_bpm_delta(a.bpm, b.bpm)
    path = shortest_harmonic_path(graph or harmonic_graph(songs), song_id(a), song_id(b))
    hops = len(path) - 1 if path else None
    key_score = {"Same": 40, "Harmonic": 25, "?": 5}.get(label, 0)
    bpm_score = max(0.0, 30 - delta)
    graph_score = 30 if hops == 1 else 20 if hops == 2 else 10 if hops and hops <= 4 else 0
    return {
        "score": round(min(100, key_score + bpm_score + graph_score)),
        "key_label": label,
        "bpm_delta": delta,
        "octave": delta < abs((a.bpm or 0) - (b.bpm or 0)),
        "hops": hops,
        "path": path,
    }


def harmonic_orphans(songs: list[Song], graph: HarmonicGraph | None = None) -> set:
    """Ids of songs with no harmonic + BPM-compatible partner — they can never be mixed into a set."""
    G = graph or harmonic_graph(songs)
    return {sid for sid in G.ids if G.out_degree(sid) == 0}


def key_gaps(songs: list[Song], top: int = 5) -> list[tuple[str, int]]:
    """The `top` thinnest Camelot slots in the library as (slot, track_count), emptiest first."""
    counts = {f"{n}{m}": 0 for n in range(1, 13) for m in "AB"}
    for s in songs:
        num, mode = parse_key(s.key)
        if f"{num}{mode}" in counts:
            counts[f"{num}{mode}"] += 1
    return sorted(counts.items(), key=lambda kv: kv[1])[:top]


def cluster_songs(songs: list[Song], n_clusters: int) -> pd.DataFrame:
    """KMeans on BPM + circular Camelot position + mode, projected to 2D with PCA.

    The wheel is circular (12 sits next to 1), so the key number is encoded as
    sin/cos; each is scaled by 1/√2 so the key counts as one feature, not two.
    """
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA

    rows = []
    for s in songs:
        num, mode = parse_key(s.key)
        if num is not None and s.bpm:
            angle = 2 * math.pi * (num - 1) / 12
            rows.append({
                "name": s.name, "artist": s.artist,
                "bpm": s.bpm, "key": s.key, "genre": s.genre,
                "key_sin": math.sin(angle), "key_cos": math.cos(angle),
                "key_major": 1.0 if mode == "B" else 0.0,
            })

    df = pd.DataFrame(rows)
    if df.empty or len(df) < n_clusters:
        df["pc1"] = 0.0
        df["pc2"] = 0.0
        df["cluster"] = 0
        return df

    scaled = StandardScaler().fit_transform(df[["bpm", "key_sin", "key_cos", "key_major"]].values)
    scaled[:, 1:3] /= math.sqrt(2)
    pcs = PCA(n_components=2).fit_transform(scaled)
    df["pc1"] = pcs[:, 0]
    df["pc2"] = pcs[:, 1]
    df["cluster"] = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(scaled)
    return df.drop(columns=["key_sin", "key_cos", "key_major"])
