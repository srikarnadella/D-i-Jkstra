# D-i-Jkstra

A graph-powered DJ setlist builder built by a DJ who wanted to bridge music and computer science. After taking DSA 2, I realized a song library is just a weighted directed graph — and setlist building is a shortest-path problem.

Every song is a node with attributes (title, artist, BPM, Camelot key, genre). Every edge between two songs represents a transition, weighted by BPM delta and harmonic compatibility. The app uses that structure to generate, visualize, and analyze sets.

## Features

### Generate Setlist
Specify a time window (e.g. 11 PM – 1 AM) and a vibe (Frat Party, Sunset, Rave, etc.). The engine:
1. Scores each track using a vibe profile (BPM range bonuses, genre bonuses)
2. Builds a harmonic adjacency graph using Camelot wheel compatibility + BPM delta constraints
3. Runs a DP longest-path algorithm to fill the time budget
4. Optionally auto-segments the set into three energy phases (keys 1–4 → 5–8 → 9–12) for a natural arc

After generation, you can reorder with **Smoothest Path** (greedy nearest-neighbor minimizing BPM + key delta), download as CSV, and visualize the set.

A **Quality Score** (0–100), harmonic transition rate, and average BPM delta are shown for every setlist.

### Dijkstra Path Finder
The app's namesake feature. Select any two songs from your library and the app finds the **shortest harmonic path** between them using Dijkstra's algorithm on the full harmonic adjacency graph. Edge weights are `abs(bpm_diff) + key_compat_penalty`. Results show each transition step with key compatibility highlighted.

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
Browse, search, and filter all ~430 tracks. Add tracks manually with Camelot key validation.

### Cluster Songs
KMeans + PCA on `[BPM, Camelot key number]` to find natural groupings in the library. Useful for seeing which songs cluster together and building sets around them.

## Tech Stack

- **Streamlit** — UI and routing
- **NetworkX** — graph construction, Dijkstra's algorithm
- **Plotly** — all visualizations (3D/2D graph, energy timeline, cluster scatter, genre bar)
- **scikit-learn** — KMeans + PCA for clustering
- **SQLite** — song library storage (~430 tracks)

## Running Locally

```bash
pip install -r requirements.txt
streamlit run 3dapp.py
```

## Architecture

The app is split into focused modules — no business logic in the Streamlit entry point:

| File | Responsibility |
|---|---|
| `3dapp.py` | UI routing and page render functions only |
| `models.py` | `Song` namedtuple, all constants, `VIBE_CONFIG`, Camelot key helpers |
| `db.py` | SQLite I/O with `@st.cache_data` |
| `setlist_engine.py` | All algorithms: scoring, DP path, Dijkstra, greedy reorder, clustering |
| `viz.py` | All Plotly figure builders |
| `dj_graph.py` | `DJSetlistGraph` wrapping NetworkX DiGraph |
