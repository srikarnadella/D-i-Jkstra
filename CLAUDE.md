# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
streamlit run 3dapp.py
```

Install dependencies:
```bash
pip install -r requirements.txt
```

## Architecture

The app is split into five Python modules plus the Streamlit entry point:

| File | Responsibility |
|---|---|
| `3dapp.py` | Entry point only — routing, `render_*_page()` functions, UI widgets. No business logic. `st.set_page_config` is called once at the top; do not move it or add a second call. |
| `models.py` | `Song` namedtuple, all constants, `VIBE_CONFIG`, `ARTIST_GENRE_OVERRIDES`, `GENRE_COLOR_MAP`, `map_genre()`, `parse_key()`, `get_harmonic_neighbors()`, `key_compat_label()`. No external deps — import freely from any module. |
| `db.py` | SQLite I/O: `get_songs()` (cached), `get_tracks_df()`, `get_library_df()`, `insert_track()`, `adapt_uploaded_csv()`. Has one Streamlit import for `@st.cache_data`. After any write, call `st.cache_data.clear()` then `st.rerun()`. |
| `setlist_engine.py` | All algorithms: `score_track()`, `build_segment_graph()`, `build_harmonic_graph_setlist()`, `smoothest_setlist()`, `cluster_songs()`, `find_harmonic_path()`. No Streamlit dependency. |
| `viz.py` | All Plotly figure builders: `build_3d_figure()`, `build_2d_figure()`, `cluster_figure()`, `energy_timeline_figure()`, layout helpers (`stable_3d_positions`, `spring_layout_2d`, `circular_layout_3d`), `bpm_edge_color()`, `setlist_to_csv_bytes()`. |
| `dj_graph.py` | `DJSetlistGraph` — wraps `networkx.DiGraph`. Nodes keyed as `"{name}_{artist}"`. Edges store `bpm_diff` and `key_change`. Used by the Visualizer page. |

### Data

Song data is stored in **`dj_tracks.db`** (SQLite). The `tracks` table columns: `track_title`, `artist`, `bpm`, `key`, `genre`. The app loads songs at startup via `get_songs()` which is `@st.cache_data(ttl=60)` wrapped.

The DB has ~430 tracks with 50+ genre string variants and some artist names used as genre ("Pitbull", "tiesto"). `map_genre()` in `models.py` normalizes all of these. `ARTIST_GENRE_OVERRIDES` handles the artist-as-genre cases specifically.

Keys are in Camelot wheel notation (`"8A"`, `"12B"`). All key operations go through `parse_key()` / `get_harmonic_neighbors()` / `key_compat_label()` in `models.py`.

### Setlist Generation (`setlist_engine.py`)

1. **Vibe scoring** (`score_track`) — uses `VIBE_CONFIG` dict in `models.py`. To add a new vibe, add one entry to `VIBE_CONFIG`; no other code needs to change.
2. **DP graph path** (`build_segment_graph`) — builds harmonic adjacency (Camelot neighbors + ≤`MAX_HARMONIC_BPM_DELTA` BPM delta), then DP to find the longest time-fitting path. Each track is assumed `TRACK_DURATION_SECONDS = 210`.
3. **Auto-segmentation** (`build_harmonic_graph_setlist`) — splits the set into three Camelot key range segments (1–4, 5–8, 9–12) to build an energy arc.
4. **Greedy reorder** (`smoothest_setlist`) — nearest-neighbor path minimizing `abs(bpm_diff) + key_compat_score * 2`. Run after generation to smooth transitions.
5. **Dijkstra path finder** (`find_harmonic_path`) — builds a full harmonic adjacency graph then uses `nx.dijkstra_path()` with cost = `abs(bpm_diff) + key_compat_score * 2` to find the shortest harmonic route between any two songs.
6. **Clustering** (`cluster_songs`) — KMeans + PCA on `[bpm, camelot_key_num]`. Returns a DataFrame with `pc1`, `pc2`, `cluster` columns for `cluster_figure()` in `viz.py`.

### Visualization (`viz.py`)

- **Visualizer page**: `build_3d_figure()` or `build_2d_figure()`. Uses `DJSetlistGraph.build_harmonic_graph()` — connects every harmonically compatible pair, not just consecutive songs. Positions seeded by `frozenset(G.nodes())` for stability. Sidebar shows edge count. Includes Dijkstra path finder below the graph.
- **Setlist viz**: `circular_layout_3d` — songs arranged around a circle in set order.
- **Energy timeline**: `energy_timeline_figure()` — BPM line chart with markers colored by key transition quality (green=Same, yellow=Harmonic, red=Non-harmonic).
- **Cluster page**: `cluster_figure()` — one Plotly scatter trace per cluster using `px.colors.qualitative.Bold`.
- Edge color via `bpm_edge_color()`: green ≤2 BPM, yellow ≤5, red >5.

## Legacy Code

- `legacyV1/` — Original prototype using an Excel file and custom node/edge classes.
- `legacyV2/` — Intermediate version using `pyvis` for 2D network visualization and Excel data. `smoothest_setlist` and clustering from `setlist_builder.py` have been ported into the active `setlist_engine.py`.
- `legacydata/` — Excel/CSV music library files used by legacy versions.
- `lib/` — Static JS/CSS (tom-select, vis-network) from an earlier web-only prototype.

The legacy directories are kept for reference but are not imported by the active app.
