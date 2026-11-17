# D-i-Jkstra

[![tests](https://github.com/srikarnadella/D-i-Jkstra/actions/workflows/test.yml/badge.svg)](https://github.com/srikarnadella/D-i-Jkstra/actions/workflows/test.yml)

**A graph-powered DJ set builder.** Your music library is a map of which tracks can be mixed into which; D-i-Jkstra finds the smooth routes through it, builds a set that fits your time slot and follows the night's energy, and helps you pick the next track live from the booth.

Built by a DJ who wanted to bridge music and computer science: after a data-structures course it was clear that a song library is just a weighted directed graph, and building a set is a shortest-path problem.

| | |
|---|---|
| **[Part 1 — The tool](#part-1--the-tool)** | What it does, how to use it, how to get your music in. |
| **[Part 2 — The technicals](#part-2--the-technicals)** | Architecture, algorithms, data model, performance, testing. |

---

# Part 1 — The tool

## The idea

Two tracks mix well when their **keys are compatible** (on the Camelot wheel, the same key, its relative major/minor, or one step either way) and their **tempos are close** (or one is half or double the other). Treat every track as a node and every good mix as an edge, and the whole library becomes a graph. Everything in the app is a question about that graph:

- *Which tracks can I play after this one?*
- *What's the smoothest route from this track to that one?*
- *What 2-hour path through my crate warms up, peaks, and cools down?*

## What you can do

| Screen | What it's for |
|---|---|
| **Overview** | Your library at a glance: track count, tempo, how many of the 24 keys you cover, a Camelot wheel showing where your crate is thin, genre breakdown, and your saved sets. |
| **Build a set** | Pick a start and end time and a vibe (Sunset, Kick Back, Rave, House, Poolside). Get a full set where every transition is harmonic and the energy follows the vibe's curve, with a quality score and an energy-across-the-night chart. |
| **Live** | In the booth: pick what's playing, choose **cool down / hold / push**, and get the best next tracks with the reason for each ("+1 key · +4 BPM · energy +0.5"). Tap *Play next* and it moves on. Save the night as a set. |
| **Library** | Browse, search, edit and import tracks. Add energy ratings and lengths, see Rekordbox cue points, find "orphans" (tracks that can't mix into anything). |
| **Key graph** | Your library as a 3D/2D graph. Find the smoothest route between two tracks, or score how well any two mix. |
| **Clusters** | Groups your tracks by tempo and key, so you can build a set from one group. |

### Building a set

1. **Choose the window and the vibe.** Overnight sets work (11 PM → 1 AM).
2. **Optional controls:**
   - follow the vibe's **energy curve** (warm-up → peak → cool-down) using your 1–10 energy ratings, or an estimate from BPM when a track has none;
   - **account for blends**: each track is timed from its mix-in to its mix-out (your Rekordbox cue points, otherwise a 32-bar blend), so the set fills the window the way you'd really play it;
   - **use your mixing history**: transitions you've actually played become cheaper, even across keys;
   - **pin an opener and a closer**; the app bridges to them with the smoothest path and still fits the window;
   - avoid songs from earlier saved sets, or build only from one cluster.
3. **Edit the result.** Move or remove tracks, swap in the best replacement for any slot, insert bridge tracks into a rough transition, or **lock the tracks you love and regenerate everything around them**.
4. **Take it with you.** Download a CSV, or export a **Rekordbox playlist** (XML) to load straight into your decks.

## Getting your music in

- **From Rekordbox (best):** export your collection as XML and use *Library → Bulk Import*. You get BPM, key, length, file locations (needed for playlist export), your cue points, and any Mixed In Key energy comments. You can also import a played playlist to teach the app your style.
- **From a CSV:** columns `Title, Artist, BPM, Key, Genre` (optional `Duration`, `Energy`). Keys can be Camelot (`8A`) or musical (`Am`, `F#`). Duplicates are skipped.
- **From audio files:** `python analyze.py ~/Music/DJ` fills in missing BPM, key, length and energy by analysing the audio (optional, see below).
- **By hand:** *Library → Add Track*, or edit any cell in the table.

A fresh clone starts with a 150-track demo library of fictional tracks, so everything works immediately.

## Quick start

Python 3.10 or newer.

```bash
pip install -r requirements.txt
streamlit run 3dapp.py
```

Optional audio analysis (BPM / key / length / energy from your files):

```bash
pip install -r requirements-analysis.txt
python analyze.py ~/Music/DJ --dry-run        # preview; drop --dry-run to write
```

Optional settings (environment variables):

| Variable | Effect |
|---|---|
| `DJ_DB_PATH` | Use a different database file (default `dj_tracks.db`). |
| `DJ_READ_ONLY=1` | Public-demo mode: browsing and generating work, every save, import and edit is switched off. |

## Honest limits

- **Your data decides the quality.** The app trusts the BPM and key it's given. Half-time BPM labels (a 130 BPM track listed as 65) and wrong keys from a tagger will produce wrong mixes.
- **Rekordbox export follows Rekordbox's documented XML format.** It has been tested for round-tripping, not yet against a live Rekordbox install on every version; tracks only link if they carry a file location (import from Rekordbox to capture them).
- **Audio key detection is approximate,** especially on dense mixes. Use it to fill gaps, and prefer keys from Rekordbox or Mixed In Key when you have them.
- The vibe energy curves and the scoring weights are sensible first guesses; expect to tune them to your taste.

---

# Part 2 — The technicals

## Stack

| Layer | Tech |
|---|---|
| UI | **Streamlit** (multi-page via a small router), custom CSS theme |
| Charts | **Plotly** (all figures built in `viz.py`) |
| Engine | Pure Python + **NumPy**; own adjacency lists and heap-based Dijkstra |
| Analysis | **scikit-learn** (KMeans, PCA), **pandas** |
| Storage | **SQLite** (one file, additive migrations) |
| Parsing | **defusedxml** for uploaded Rekordbox XML |
| Optional | **librosa** + **mutagen** for audio analysis (`analyze.py`) |
| Graph drawing | **NetworkX** (only for the Visualizer's layouts; the engine doesn't use it) |

## Architecture

The engine has no Streamlit dependency and the UI has no business logic.

```
3dapp.py            entry point: page config, session state, sidebar, router (?page= URLs)
ui/                 one module per page, each render(songs): home, live, generate,
                    visualizer, library, cluster · theme.py (look) · common.py (helpers)
models.py           Song, constants, VIBE_CONFIG, Camelot/BPM/energy helpers (no deps)
db.py               SQLite I/O, Rekordbox import/export, library import logic
setlist_engine.py   scoring, graph, search, set editing, live suggestions, analysis
viz.py              Plotly figure builders in the app palette
dj_graph.py         NetworkX wrapper for the Visualizer
analyze.py          standalone CLI: audio → BPM / key / length / energy
scripts/            benchmark (greedy vs beam, 20k-track scale), demo-library generator
tests/              150 tests (engine, models, db, analysis, security)
docs/               how-it-works.md (the algorithms in depth)
```

## Data model

`dj_tracks.db`, SQLite. Tables are created and migrated additively on first use (`db._ensure_schema`); a brand-new file is seeded from `demo_tracks.csv`.

| Table | Contents |
|---|---|
| `tracks` | `track_title, artist, bpm, key, genre, duration, location, energy`; unique on `(track_title, artist)`. `duration`, `location` and `energy` are nullable; unknown means unknown (a 3:30 length is only *assumed* when timing a set). |
| `cues` | Rekordbox cue points per track (`num` −1 = memory cue, 0–7 = hot cue, `start_seconds`). |
| `transitions` | Counts of (from → to) pairs you have played; kept even if a track is later deleted. |
| `saved_setlists` | JSON snapshots, refreshed from the library when loaded (deleted tracks fall back to the snapshot). |

A song is identified by **`(name, artist)`**, never by title alone. Keys are stored as Camelot (`8A`, `12B`); anything user-typed goes through `to_camelot()` first.

## The engine

*(Full walkthrough with a diagram: [docs/how-it-works.md](docs/how-it-works.md).)*

**Transition cost** is the single function everything else uses:

```
cost = effective_bpm_delta + 2 × key_penalty − style_bonus      (floored at 0)
effective_bpm_delta = min(|a−b|, |2a−b|, |a−2b|)                 half/double-time aware
key_penalty: same key 0 · Camelot neighbor 1 · anything else 4
style_bonus = 3 × log(1 + times you've played this transition)
```

**Edges.** `A → B` exists when B's key is a Camelot neighbor of A's (same key, relative major/minor, ±1 step) and the tempos are compatible (within 25 BPM, or half/double-time within 8), plus any pair you've played.

**Indexed graph.** Comparing every pair is O(n²). Instead, tracks are bucketed by Camelot slot and sorted by BPM, so each track only inspects its 4 neighbor slots inside the direct, double-time and half-time BPM windows (`harmonic_neighbors`). The result is identical to the brute-force definition (verified in tests, including window-boundary and slow-tempo cases). Each track keeps its 60 cheapest partners plus all played pairs. `HarmonicGraph` stores adjacency lists and runs a `heapq` Dijkstra with an exclusion set.

**Set search** (`build_segment_graph`). Each step costs `transition_cost` + `|track energy − curve target| × ENERGY_WEIGHT`. The search is either multi-start **greedy** (every opener tried, up to 500) or **beam search** (width 40); `auto` picks greedy up to 500 tracks and beam above, where beam fits the energy curve about 5× better at equal quality. A **2-opt polish** then reverses any run whose reversal lowers total cost without breaking a transition. Tracks are timed by `mix_out − mix_in`, so a 2-hour window holds about 45% more tracks than full-length timing.

**Pipeline** (`generate_setlist`). Filter (cluster, excluded sets, BPM range, pins) → vibe-score → path search → stitch a pinned opener/closer with Dijkstra bridges that never reuse a song → trim the middle until the whole set fits the window.

**Lock and regenerate** (`regenerate_unlocked`). Locked positions stay; each gap keeps its time budget and is refilled with *new* tracks, anchored at both ends (it must start from the locked track before it and end where it can mix into the one after), on the right stretch of the energy curve. A backwards BFS from the right-hand anchor stops the search walking into dead ends.

**Live** (`next_track_suggestions`). Scores each compatible candidate on BPM gap, key move and distance from the wanted energy change (cool / hold / push = −0.5 / 0 / +0.5 per track). *Push* also allows the +7 and +2 "energy boost" key moves, and every suggestion carries human-readable reasons.

**Analysis.** Set quality = 60% harmonic-transition rate + 40% BPM smoothness. Clustering is KMeans on `[bpm, sin(key), cos(key), mode]` (the key is circular: 12A sits next to 1A) projected with PCA. `analyze.py` estimates BPM from the slope of beat times (librosa's own estimate snaps to a coarse grid), key by Krumhansl–Kessler correlation on a chroma vector, and energy as deciles of loudness, brightness and tempo across the batch.

## Performance

Measured with `python scripts/bench_engine.py 120 --synthetic 20000` on a laptop:

| Library | Build graph | Generate a 2 h set | Compare two tracks / insert a bridge |
|---|---|---|---|
| 500 tracks | ~0.01 s | 0.1–0.3 s | < 0.01 s |
| 20,000 tracks | ~0.7 s | 0.7–1.1 s | < 0.05 s (cached graph) |

The Streamlit layer builds the library graph once per library version (`st.cache_resource`) and reuses it across pages and reruns.

## UI and design system

A dark "true-black flat" style built for a dim booth: `#000` ground, `#111` cards with no borders or shadows, one amber data hue used only on data (never on chrome), green for compatible and red for a key clash, an inverted white primary button, Inter at 16px / weight 500, tabular figures everywhere, no emoji. Theme tokens live in `.streamlit/config.toml` (committed) and `ui/theme.py`; charts share one style helper in `viz.py`. Pages are addressable (`?page=live`).

## Security and safety

- **HTML escaping:** every library or user string rendered with `unsafe_allow_html` goes through `html.escape`. `tests/test_security.py` parses the UI source and fails the build on any unescaped interpolation.
- **XML:** uploaded Rekordbox files are parsed with `defusedxml` (entity-expansion bombs are rejected; covered by a test).
- **Read-only mode:** `DJ_READ_ONLY=1` disables write controls in the UI *and* makes every write function in `db.py` raise `ReadOnlyError`; a test asserts that all write paths refuse.

## Testing and CI

```bash
pytest                 # 150 tests, about 2 s
```

Covered: transition costs, the indexed graph against a brute-force oracle, search constraints (time budget, anchors, no repeats), energy-curve steering, lock-and-regenerate, live suggestions, key and duration parsing, Rekordbox round-trips (export → import), cue parsing, the read-only guard, the escaping guard, and key detection on synthetic tones. GitHub Actions runs the suite on every push and pull request (Python 3.12).

Streamlit's `AppTest` can't re-run a page that contains Plotly charts, so button logic lives in tested functions (`library_changes`, `import_tracks`, …) and pages are smoke-tested one fresh `AppTest` at a time.

## Developing

```bash
python scripts/bench_engine.py 120                       # greedy vs beam on your library
python scripts/bench_engine.py 120 --synthetic 20000     # scale check
python scripts/make_demo_csv.py                          # regenerate the demo library
```

- **Add a vibe:** add one entry to `VIBE_CONFIG` in `models.py` (excluded genres, BPM bonus, genre bonuses, `energy_curve`). Nothing else changes.
- **Add a page:** create `ui/<name>.py` with `render(songs)`, then register it in `PAGE_MODULES` (`3dapp.py`) and `PAGE_LABELS` (`ui/common.py`).
- **Add a write path:** guard it with `db._check_writable()`, disable its control with `READ_ONLY`, and add it to the read-only test.

## Status

Built and tested on synthetic data and a ~1,000-track library. Still to do: validate Rekordbox export/import and audio analysis against a real collection, publish a read-only demo, and tune the vibe curves after real use. Ideas on deck include transition audio previews, crowd-feedback scoring in Live and a printable booth sheet.
