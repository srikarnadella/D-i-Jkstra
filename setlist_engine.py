import random
import networkx as nx
import pandas as pd

from models import (
    Song,
    TRACK_DURATION_SECONDS,
    FIRST_SEGMENT_CAP_SECONDS,
    MID_SEGMENT_FRACTION,
    LATE_SEGMENT_FRACTION,
    MAX_HARMONIC_BPM_DELTA,
    SCORE_JITTER,
    VIBE_CONFIG,
    parse_key,
    get_harmonic_neighbors,
    key_compat_label,
)


def score_track(row: dict, vibe: str) -> float:
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

    score += random.uniform(0, SCORE_JITTER)
    return score


def build_segment_graph(tracks: list[dict], total_duration_seconds: float) -> list[dict]:
    n = len(tracks)
    graph: list[list[int]] = [[] for _ in range(n)]

    for i in range(n):
        key1 = str(tracks[i].get("key") or "").strip().upper()
        bpm1 = tracks[i].get("bpm", 0) or 0
        for j in range(n):
            if i == j:
                continue
            key2 = str(tracks[j].get("key") or "").strip().upper()
            bpm2 = tracks[j].get("bpm", 0) or 0
            if key2 in get_harmonic_neighbors(key1) and abs(bpm1 - bpm2) <= MAX_HARMONIC_BPM_DELTA:
                graph[i].append(j)

    dp: list[tuple[float, list[int]]] = [(TRACK_DURATION_SECONDS, [i]) for i in range(n)]
    for i in range(n):
        for j in graph[i]:
            new_time = dp[i][0] + TRACK_DURATION_SECONDS
            if new_time <= total_duration_seconds and new_time > dp[j][0]:
                dp[j] = (new_time, dp[i][1] + [j])

    best = max(dp, key=lambda x: (x[0] <= total_duration_seconds, x[0], random.random()))
    return [tracks[i] for i in best[1]]


def build_harmonic_graph_setlist(
    scored_tracks: list[dict],
    total_duration_seconds: float,
    use_auto_segmentation: bool = True,
) -> list[dict]:
    eligible_tracks = [
        t for t in scored_tracks if t.get("vibe_score", 0) > 0 and t.get("key")
    ]
    if not eligible_tracks:
        return []
    if not use_auto_segmentation:
        return build_segment_graph(eligible_tracks, total_duration_seconds)

    seg_duration = min(FIRST_SEGMENT_CAP_SECONDS, total_duration_seconds)
    remaining = total_duration_seconds - seg_duration
    segments = [
        ([t for t in eligible_tracks if parse_key(t["key"])[0] in range(1, 5)], seg_duration),
        ([t for t in eligible_tracks if parse_key(t["key"])[0] in range(5, 9)], remaining * MID_SEGMENT_FRACTION),
        ([t for t in eligible_tracks if parse_key(t["key"])[0] in range(9, 13)], remaining * LATE_SEGMENT_FRACTION),
    ]
    result: list[dict] = []
    for seg_tracks, seg_time in segments:
        if seg_tracks:
            result.extend(build_segment_graph(seg_tracks, seg_time))
    return result


def _key_compat_score(k1: str, k2: str) -> int:
    return {"Same": 0, "Harmonic": 1}.get(key_compat_label(k1, k2), 4)


def smoothest_setlist(songs: list[Song]) -> list[Song]:
    """Greedy nearest-neighbor reordering minimizing BPM delta + key distance."""
    if len(songs) < 2:
        return songs

    G = nx.DiGraph()
    for i, a in enumerate(songs):
        for j, b in enumerate(songs):
            if i == j:
                continue
            w = abs((a.bpm or 0) - (b.bpm or 0)) + _key_compat_score(a.key, b.key) * 2
            G.add_edge(i, j, weight=w)

    path = [0]
    visited = {0}
    while len(visited) < len(songs):
        cur = path[-1]
        nbr = min(
            (n for n in G.neighbors(cur) if n not in visited),
            key=lambda n: G[cur][n]["weight"],
            default=None,
        )
        if nbr is None:
            break
        path.append(nbr)
        visited.add(nbr)
    return [songs[i] for i in path]


def find_harmonic_path(songs: list[Song], source_name: str, target_name: str) -> list[Song] | None:
    """Return the shortest harmonic path between two songs using Dijkstra, or None if unreachable."""
    name_to_song = {s.name: s for s in songs}
    G = nx.DiGraph()
    for s in songs:
        G.add_node(s.name)
    for a in songs:
        for b in songs:
            if a.name == b.name:
                continue
            if b.key in get_harmonic_neighbors(a.key) and abs(a.bpm - b.bpm) <= MAX_HARMONIC_BPM_DELTA:
                cost = abs(a.bpm - b.bpm) + _key_compat_score(a.key, b.key) * 2
                G.add_edge(a.name, b.name, cost=cost)
    try:
        path_names = nx.dijkstra_path(G, source_name, target_name, weight="cost")
        return [name_to_song[n] for n in path_names if n in name_to_song]
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def cluster_songs(songs: list[Song], n_clusters: int) -> pd.DataFrame:
    """Cluster songs by BPM and Camelot key number using KMeans + PCA."""
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA

    rows = []
    for s in songs:
        num, _ = parse_key(s.key)
        if num is not None and s.bpm:
            rows.append({
                "name": s.name, "artist": s.artist,
                "bpm": s.bpm, "key": s.key, "genre": s.genre,
                "key_num": num,
            })

    df = pd.DataFrame(rows)
    if df.empty or len(df) < n_clusters:
        df["pc1"] = 0.0
        df["pc2"] = 0.0
        df["cluster"] = 0
        return df

    features = df[["bpm", "key_num"]].values
    scaled = StandardScaler().fit_transform(features)
    pcs = PCA(n_components=2).fit_transform(scaled)
    clusters = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(scaled)

    df["pc1"] = pcs[:, 0]
    df["pc2"] = pcs[:, 1]
    df["cluster"] = clusters
    return df
