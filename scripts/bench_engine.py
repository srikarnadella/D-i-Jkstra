"""Compare search strategies on the current library (DJ_DB_PATH or dj_tracks.db), or on a
synthetic one: python scripts/bench_engine.py [minutes] [--synthetic N]
Reports per vibe: tracks, quality, mean |energy − curve target|, total search cost, runtime."""
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import load_songs_from_db  # noqa: E402
from models import VIBE_CONFIG, track_energy  # noqa: E402
from setlist_engine import energy_target, generate_setlist, setlist_quality, start_offsets  # noqa: E402


def curve_error(setlist, curve):
    offsets, total = start_offsets(setlist), sum(s.duration for s in setlist)
    return sum(abs(track_energy(s.bpm, s.energy) - energy_target(curve, o / total))
               for s, o in zip(setlist, offsets)) / len(setlist)


def main(minutes: float = 120, synthetic: int | None = None):
    if synthetic:
        from make_demo_csv import fake_rows
        from models import Song
        songs = [Song(t, a, g, bpm, k, d) for t, a, bpm, k, g, d in fake_rows(synthetic)]
        scale_checks(songs)
    else:
        songs = load_songs_from_db()
    print(f"{len(songs)} tracks, {minutes:.0f}-minute sets")
    print(f"{'vibe':10} {'search':6} {'n':>3} {'quality':>7} {'curveErr':>8} {'secs':>5}")
    for vibe, cfg in VIBE_CONFIG.items():
        for search in ("greedy", "beam"):
            t = time.time()
            sl = generate_setlist(songs, vibe, minutes * 60, search=search, rng=random.Random(7))
            dt = time.time() - t
            q = setlist_quality(sl)
            print(f"{vibe:10} {search:6} {len(sl):3} {q['quality']:7.1f} "
                  f"{curve_error(sl, cfg['energy_curve']):8.2f} {dt:5.1f}")


def scale_checks(songs):
    """Library-wide operations the app runs, timed (P1 targets: generate < 3 s, compat < 0.5 s)."""
    from setlist_engine import compatibility, harmonic_graph, harmonic_orphans, insert_bridge
    t = time.time(); G = harmonic_graph(songs); tg = time.time() - t
    edges = sum(len(r) for r in G.adj)
    t = time.time(); harmonic_orphans(songs, G); to = time.time() - t
    t = time.time(); compatibility(songs, songs[0], songs[len(songs) // 2], G); tc = time.time() - t
    t = time.time(); insert_bridge(songs, [songs[1], songs[-1]], 1, graph=G); tb = time.time() - t
    print(f"graph build {tg:.2f}s ({edges} edges) · orphans {to:.2f}s · compat {tc:.2f}s · bridge {tb:.2f}s")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    syn = int(sys.argv[sys.argv.index("--synthetic") + 1]) if "--synthetic" in sys.argv else None
    if syn:
        args = [a for a in args if a != str(syn)]
    sys.path.insert(0, os.path.dirname(__file__))
    main(float(args[0]) if args else 120, syn)
