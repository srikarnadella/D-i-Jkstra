# D-i-Jkstra

[![tests](https://github.com/srikarnadella/D-i-Jkstra/actions/workflows/test.yml/badge.svg)](https://github.com/srikarnadella/D-i-Jkstra/actions/workflows/test.yml)

A graph-powered DJ setlist builder built by a DJ who wanted to bridge music and computer science. After taking DSA 2, I realized a song library is just a weighted directed graph — and setlist building is a shortest-path problem.

Every song is a node with attributes (title, artist, BPM, Camelot key, genre). Every edge between two songs represents a transition, weighted by BPM delta and harmonic compatibility. The app uses that structure to generate, visualize, and analyze sets.

## Features

### Generate Setlist
Specify a time window (e.g. 11 PM – 1 AM) and a vibe (Sunset, Kick Back, Rave, House, Poolside). The engine:
1. Scores each track using a vibe profile (BPM range bonuses, genre bonuses)
2. Builds a harmonic adjacency graph using Camelot wheel compatibility + BPM constraints (half/double-time mixing counts)
3. Builds the longest time-fitting path with a multi-start greedy search, using each track's real length
4. Optionally follows the vibe's **energy curve** — a target-energy shape (warm-up → peak → cool-down) the path is steered toward, using your 1–10 energy ratings (or an estimate from BPM)
5. Times tracks by their **blends** — mix-in to mix-out from your Rekordbox cue points (or a 32-bar blend), so the set fills the window the way you'd actually play it
6. Optionally **learns your style** — transitions you've actually played (imported from Rekordbox playlists) get cheaper, even across keys

Optional: pin an opener/closer (bridged in with Dijkstra, still fitting the time window), restrict to a cluster, or avoid songs from saved setlists so repeat crowds don't hear the same tracks.

After generation, you can **edit the set** (move or remove tracks, pick from the best replacement for any slot, insert Dijkstra bridge songs into a rough transition, or **lock** the tracks you love and regenerate everything around them), **export it as a Rekordbox playlist** (XML) or CSV, reorder with **Smoothest Path** (greedy nearest-neighbor minimizing BPM + key delta), download as CSV, and visualize the set.

A **Quality Score** (0–100), harmonic transition rate, and average BPM delta are shown for every setlist.

### Live mode
For the booth: pick what's playing, choose **cool down / hold / push**, and get five ranked next tracks with the reasons ("+1 key", "+4.0 BPM", "energy +0.5", "+7 energy boost"). Tap "Play this" to move on; what you played tonight can be saved as a setlist.

### Audio analysis
`python analyze.py ~/Music/DJ` analyzes your files and fills in missing BPM, key, length and energy (needs `pip install -r requirements-analysis.txt`).

### Dijkstra Path Finder
The app's namesake feature. Select any two songs from your library and the app finds the **shortest harmonic path** between them using Dijkstra's algorithm on the full harmonic adjacency graph. Edge weights are `effective_bpm_delta + key_compat_penalty` (half/double-time transitions count as their effective gap). Results show each transition step with key compatibility highlighted.

### Visualizer
Explore the full harmonic compatibility graph of your library in 3D or 2D. Unlike a simple linked list, the graph connects **every pair of songs** that are Camelot-compatible within the BPM threshold — revealing hub songs that can transition to many others. Edge count is shown in the sidebar.

- **3D view**: Plotly Scatter3d with stable seeded positions
- **2D view**: force-directed spring layout
- Edge color by BPM delta: green ≤2, yellow ≤5, red >5
- Node color by genre
- Hover tooltips: song name, artist, BPM, key

### Energy Timeline
After generating a setlist, a BPM line chart shows the energy arc across the set. Transition markers are colored by key compatibility (green = same key, yellow = harmonic neighbor, red = non-harmonic) so you can see where the rough transitions are at a glance.

### Library
Browse, search, filter and edit all ~1,000 tracks (BPM, key, genre, length). Keys accept Camelot (`8A`) or musical notation (`Am`, `F#`). Bulk import from CSV or a **Rekordbox collection XML** export (which also brings in file locations, for playlist export, and your cue points, shown per track). "Orphans only" shows tracks with no compatible partner; Home lists the thinnest Camelot keys in your library.

### Cluster Songs
KMeans + PCA on BPM + circular Camelot position (12 sits next to 1) + major/minor to find natural groupings in the library. Useful for seeing which songs cluster together and building sets around them.

## Tech Stack

- **Streamlit** — UI and routing
- **NetworkX** — graph construction, Dijkstra's algorithm
- **Plotly** — all visualizations (3D/2D graph, energy timeline, cluster scatter, genre bar)
- **scikit-learn** — KMeans + PCA for clustering
- **SQLite** — song library storage (~1,000 tracks)

## Running Locally

```bash
pip install -r requirements.txt
streamlit run 3dapp.py
pytest            # run tests
```

A fresh clone starts with a 150-track demo library (`demo_tracks.csv`, fictional tracks). Set `DJ_DB_PATH` to use a different database file. Set `DJ_READ_ONLY=1` for a public demo — browsing and generating work, every save/import/edit is switched off.

Libraries of 20,000+ tracks are fine: the harmonic graph is built with a key/BPM index rather than comparing every pair (`python scripts/bench_engine.py 120 --synthetic 20000`). See [docs/how-it-works.md](docs/how-it-works.md) for how sets are built.

## Architecture

The app is split into focused modules — no business logic in the Streamlit entry point:

| File | Responsibility |
|---|---|
| `3dapp.py` | Entry point: page config, session state, sidebar nav, router |
| `ui/` | One module per page (home, live, generate, visualizer, library, cluster) |
| `models.py` | `Song` namedtuple, all constants, `VIBE_CONFIG`, Camelot key helpers |
| `db.py` | SQLite I/O with `@st.cache_data` |
| `setlist_engine.py` | All algorithms: scoring, greedy segment path, Dijkstra, greedy reorder, clustering |
| `viz.py` | All Plotly figure builders |
| `dj_graph.py` | `DJSetlistGraph` wrapping NetworkX DiGraph |
