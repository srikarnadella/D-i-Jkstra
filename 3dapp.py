import re
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta

from models import (
    Song, map_genre, GENRE_COLOR_MAP, key_compat_label,
    TRACK_DURATION_SECONDS, VIBE_CONFIG,
)
from db import get_songs, get_tracks_df, get_library_df, insert_track, adapt_uploaded_csv
from setlist_engine import (
    score_track, build_harmonic_graph_setlist,
    smoothest_setlist, cluster_songs, find_harmonic_path,
)
from viz import (
    stable_3d_positions, circular_layout_3d, spring_layout_2d,
    build_3d_figure, build_2d_figure, bpm_edge_color,
    setlist_to_csv_bytes, cluster_figure, energy_timeline_figure,
)
from dj_graph import DJSetlistGraph

# ── Must be the first Streamlit call ─────────────────────────────────────────
st.set_page_config(page_title="D-i-Jkstra", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0e0e0e; }
.stButton > button {
    background-color: #1f1f1f;
    color: white;
    border: 2px solid white;
    border-radius: 10px;
    transition: all 0.2s ease;
}
.stButton > button:hover { background-color: white; color: black; }
</style>
""", unsafe_allow_html=True)

# ── Load song library ─────────────────────────────────────────────────────────
songs = get_songs()

# ── Session state ─────────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "home"
if "generated_setlist" not in st.session_state:
    st.session_state.generated_setlist = []
if "show_setlist_viz" not in st.session_state:
    st.session_state.show_setlist_viz = False
if "viz_path_result" not in st.session_state:
    st.session_state.viz_path_result = None
if "viz_path_key" not in st.session_state:
    st.session_state.viz_path_key = None

PAGES = ["home", "visualizer", "generate_setlist", "library", "cluster"]
PAGE_LABELS = {
    "home": "Home", "visualizer": "Visualizer",
    "generate_setlist": "Generate Setlist", "library": "Library",
    "cluster": "Cluster Songs",
}


def go_to(page: str) -> None:
    st.session_state.page = page
    st.rerun()


# ── Persistent sidebar nav ────────────────────────────────────────────────────
if st.session_state.page != "home":
    with st.sidebar:
        st.markdown("## D-i-Jkstra")
        for page_id, label in PAGE_LABELS.items():
            if page_id == "home":
                continue
            is_active = st.session_state.page == page_id
            if st.button(label, use_container_width=True,
                         type="primary" if is_active else "secondary"):
                go_to(page_id)
        if st.button("← Home", use_container_width=True):
            go_to("home")
        st.divider()


# ════════════════════════════════════════════════════════════════════════════
def render_home_page() -> None:
    st.markdown("""
    <div style='text-align:center; padding-top:60px;'>
        <div style='font-size:72px; color:white; font-weight:800; letter-spacing:6px;'>D-i-Jkstra</div>
        <div style='font-size:18px; color:#888; margin-top:10px;'>Graph-powered DJ setlist builder</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    for col, page_id in zip([c1, c2, c3, c4],
                             ["visualizer", "generate_setlist", "library", "cluster"]):
        with col:
            if st.button(PAGE_LABELS[page_id], use_container_width=True):
                go_to(page_id)

    st.markdown("<br>", unsafe_allow_html=True)
    m1, m2, m3 = st.columns(3)
    bpms = [s.bpm for s in songs if s.bpm]
    genre_counts: dict[str, int] = {}
    for s in songs:
        g = map_genre(s.genre)
        genre_counts[g] = genre_counts.get(g, 0) + 1

    m1.metric("Library Size", f"{len(songs)} tracks")
    m2.metric("Top Genre", max(genre_counts, key=genre_counts.get) if genre_counts else "—")
    m3.metric("Avg BPM", f"{sum(bpms)/len(bpms):.0f}" if bpms else "—")

    st.markdown("<br>", unsafe_allow_html=True)
    st.subheader("Genre breakdown")
    gc_sorted = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)
    genres_list, counts_list = zip(*gc_sorted) if gc_sorted else ([], [])
    colors_list = [GENRE_COLOR_MAP.get(g, "gray") for g in genres_list]
    bar_fig = go.Figure(
        go.Bar(x=list(genres_list), y=list(counts_list),
                marker_color=colors_list, text=list(counts_list),
                textposition="outside")
    )
    bar_fig.update_layout(
        paper_bgcolor="#0e0e0e", plot_bgcolor="#0e0e0e",
        font_color="white", margin=dict(l=0, r=0, t=10, b=0),
        yaxis=dict(showgrid=False), xaxis=dict(showgrid=False),
    )
    st.plotly_chart(bar_fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
def render_visualizer_page() -> None:
    st.title("Visualizer")

    st.sidebar.title("Filters")
    view_mode = st.sidebar.radio("View mode", ["3D", "2D"], horizontal=True)
    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    selected_genres = st.sidebar.multiselect("Genres", all_mapped_genres, default=all_mapped_genres)
    artist_search = st.sidebar.text_input("Artist contains")
    bpm_range = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    max_songs = st.sidebar.number_input("Max songs", min_value=5, max_value=200, value=30)
    edge_mode = st.sidebar.radio("Edge color", ["BPM-based", "Uniform cyan"])
    uploaded_csv = st.sidebar.file_uploader("Upload CSV setlist", type=["csv"])

    if uploaded_csv:
        st.sidebar.info("Sidebar filters ignored — using uploaded CSV.")
        try:
            raw_df = pd.read_csv(uploaded_csv)
            df_up = adapt_uploaded_csv(raw_df)
            filtered_songs = [Song(*row) for row in df_up.itertuples(index=False)]
            st.sidebar.success(f"{len(filtered_songs)} songs loaded from CSV.")
        except Exception as e:
            st.sidebar.error(str(e))
            filtered_songs = []
    else:
        filtered_songs = [
            s for s in songs
            if map_genre(s.genre) in selected_genres
            and s.bpm is not None and bpm_range[0] <= s.bpm <= bpm_range[1]
            and (not artist_search or artist_search.lower() in s.artist.lower())
        ][:max_songs]

    st.caption(f"Showing {len(filtered_songs)} songs")

    if not filtered_songs:
        st.info("No songs match the current filters.")
        return

    dj_graph = DJSetlistGraph()
    dj_graph.build_harmonic_graph(filtered_songs)
    G = dj_graph.graph
    st.sidebar.metric("Harmonic connections", G.number_of_edges(),
                      f"across {G.number_of_nodes()} songs")
    color_fn = bpm_edge_color if edge_mode == "BPM-based" else None

    if view_mode == "3D":
        pos = stable_3d_positions(G)
        fig = build_3d_figure(G, pos, edge_color_fn=color_fn)
    else:
        pos = spring_layout_2d(G)
        fig = build_2d_figure(G, pos, edge_color_fn=color_fn)

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Legend"):
        genre_cols = st.columns(len(GENRE_COLOR_MAP))
        for col, (genre, color) in zip(genre_cols, GENRE_COLOR_MAP.items()):
            col.markdown(f"<span style='color:{color}'>■</span> {genre}", unsafe_allow_html=True)
        if edge_mode == "BPM-based":
            st.caption("Edge color: 🟢 ≤2 BPM &nbsp;&nbsp; 🟡 ≤5 BPM &nbsp;&nbsp; 🔴 >5 BPM")

    st.divider()
    st.subheader("Find Harmonic Path")
    st.caption("Dijkstra's algorithm finds the smoothest key-compatible route between two songs.")

    if len(filtered_songs) >= 2:
        song_names = [s.name for s in filtered_songs]
        col_a, col_b = st.columns(2)
        source_name = col_a.selectbox("From song", song_names, key="path_source")
        target_options = [n for n in song_names if n != source_name]
        target_name = col_b.selectbox("To song", target_options, key="path_target") if target_options else None

        current_path_key = (source_name, target_name, frozenset(s.name for s in filtered_songs))

        if target_name and st.button("Find Shortest Path", type="primary"):
            path = find_harmonic_path(filtered_songs, source_name, target_name)
            st.session_state.viz_path_result = path
            st.session_state.viz_path_key = current_path_key

        if (st.session_state.viz_path_key == current_path_key
                and st.session_state.viz_path_result is not None):
            path = st.session_state.viz_path_result
            if path:
                st.success(f"Shortest path: {len(path)} songs, {len(path) - 1} transitions")
                path_rows = []
                for i, song in enumerate(path):
                    prev = path[i - 1] if i > 0 else None
                    path_rows.append({
                        "Step": i + 1,
                        "Title": song.name,
                        "Artist": song.artist,
                        "BPM": song.bpm,
                        "Key": song.key,
                        "BPM Δ": f"{song.bpm - prev.bpm:+.1f}" if prev else "—",
                        "Key Compat": key_compat_label(prev.key, song.key) if prev else "—",
                    })
                path_df = pd.DataFrame(path_rows)
                styled_path = path_df.style.map(_highlight_compat, subset=["Key Compat"])
                st.dataframe(styled_path, use_container_width=True, hide_index=True)

                G_path = nx.DiGraph()
                for idx, song in enumerate(path):
                    G_path.add_node(idx, name=song.name, artist=song.artist,
                                    bpm=song.bpm, key=song.key, genre=song.genre)
                for idx in range(len(path) - 1):
                    a, b = path[idx], path[idx + 1]
                    G_path.add_edge(idx, idx + 1,
                                    bpm_diff=round(b.bpm - a.bpm, 1),
                                    key_change=f"{a.key}→{b.key}")
                pos_path = circular_layout_3d(list(G_path.nodes))
                fig_path = build_3d_figure(G_path, pos_path, edge_color_fn=bpm_edge_color)
                st.plotly_chart(fig_path, use_container_width=True)
            else:
                st.warning("No harmonic path found — these songs aren't connected through compatible keys.")
    else:
        st.info("Load at least 2 songs to use the path finder.")


# ════════════════════════════════════════════════════════════════════════════
def _highlight_compat(val: str) -> str:
    if val == "Non-harmonic":
        return "background-color: #3d0000; color: #ff6b6b"
    if val == "Same":
        return "background-color: #003d00; color: #6bff6b"
    return ""


def render_generate_page() -> None:
    st.title("Generate Setlist")

    c1, c2 = st.columns(2)
    with c1:
        start_time = st.time_input("Start time", value=datetime.strptime("23:00", "%H:%M").time())
    with c2:
        end_time = st.time_input("End time", value=datetime.strptime("01:00", "%H:%M").time())

    overnight = st.checkbox("Overnight set (ends next day)", value=(end_time <= start_time))
    vibe = st.selectbox("Vibe", [v.title() for v in VIBE_CONFIG])
    auto_segment = st.checkbox("Auto-segment by energy curve", value=True)

    if st.button("Generate", use_container_width=True, type="primary"):
        st.session_state.show_setlist_viz = False

        start_dt = datetime.combine(datetime.today(), start_time)
        end_dt = datetime.combine(
            datetime.today() + timedelta(days=1 if overnight else 0), end_time
        )
        if not overnight and end_dt <= start_dt:
            st.error("End time must be after start time for a same-day set.")
            st.stop()

        total_duration = (end_dt - start_dt).total_seconds()
        tracks_df = get_tracks_df()
        tracks_df["vibe_score"] = tracks_df.apply(lambda row: score_track(row, vibe), axis=1)
        best_set = build_harmonic_graph_setlist(
            tracks_df.to_dict("records"),
            total_duration_seconds=total_duration,
            use_auto_segmentation=auto_segment,
        )

        if not best_set:
            st.warning(
                "No tracks matched this vibe and time window. "
                "Try a different vibe or a wider time range."
            )
            st.session_state.generated_setlist = []
            st.stop()

        st.session_state.generated_setlist = [
            Song(t["track_title"], t["artist"], t["genre"], t["bpm"], t["key"])
            for t in best_set
        ]
        approx_min = len(st.session_state.generated_setlist) * TRACK_DURATION_SECONDS // 60
        st.success(
            f"Generated {len(st.session_state.generated_setlist)} tracks "
            f"(~{approx_min} min)"
        )

    setlist: list[Song] = st.session_state.get("generated_setlist", [])
    if not setlist:
        return

    st.subheader("Setlist")
    if len(setlist) > 1:
        harmonic_count = sum(
            1 for i in range(1, len(setlist))
            if key_compat_label(setlist[i - 1].key, setlist[i].key) in ("Same", "Harmonic")
        )
        pct_harmonic = harmonic_count / (len(setlist) - 1)
        bpm_deltas = [abs(setlist[i].bpm - setlist[i - 1].bpm) for i in range(1, len(setlist))]
        avg_bpm_delta = sum(bpm_deltas) / len(bpm_deltas) if bpm_deltas else 0
        normalized_delta = min(avg_bpm_delta / 50, 1.0)
        quality = max(0, min(100, pct_harmonic * 60 + (1 - normalized_delta) * 40))

        qm1, qm2, qm3, qm4 = st.columns(4)
        qm1.metric("Quality Score", f"{quality:.0f}/100")
        qm2.metric("Tracks", len(setlist))
        qm3.metric("Harmonic Transitions", f"{pct_harmonic:.0%}")
        qm4.metric("Avg BPM Δ", f"{avg_bpm_delta:.1f}")

    rows = []
    for i, song in enumerate(setlist):
        prev = setlist[i - 1] if i > 0 else None
        rows.append({
            "#": i + 1,
            "Title": song.name,
            "Artist": song.artist,
            "BPM": song.bpm,
            "Key": song.key,
            "Genre": map_genre(song.genre),
            "BPM Δ": f"{song.bpm - prev.bpm:+.1f}" if prev else "—",
            "Key Compat": key_compat_label(prev.key, song.key) if prev else "—",
        })
    setlist_df = pd.DataFrame(rows)
    styled = setlist_df.style.map(_highlight_compat, subset=["Key Compat"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    act1, act2, act3 = st.columns(3)
    with act1:
        st.download_button(
            "Download CSV",
            setlist_to_csv_bytes(setlist),
            "setlist.csv",
            "text/csv",
            use_container_width=True,
        )
    with act2:
        if st.button("Reorder: Smoothest Path", use_container_width=True):
            st.session_state.generated_setlist = smoothest_setlist(setlist)
            st.session_state.show_setlist_viz = False
            st.rerun()
    with act3:
        if st.button("Visualize Setlist", use_container_width=True):
            st.session_state.show_setlist_viz = True

    st.subheader("Energy Timeline")
    st.plotly_chart(energy_timeline_figure(setlist), use_container_width=True)
    st.caption("Marker color: first track (gray) | Same key (green) | Harmonic (yellow) | Non-harmonic (red)")

    if st.session_state.show_setlist_viz:
        G = nx.DiGraph()
        for idx, song in enumerate(setlist):
            G.add_node(idx, name=song.name, artist=song.artist,
                       bpm=song.bpm, key=song.key, genre=song.genre)
        for idx in range(len(setlist) - 1):
            a, b = setlist[idx], setlist[idx + 1]
            G.add_edge(idx, idx + 1,
                       bpm_diff=round(b.bpm - a.bpm, 1),
                       key_change=f"{a.key}→{b.key}")

        pos = circular_layout_3d(list(G.nodes))
        fig = build_3d_figure(G, pos, edge_color_fn=bpm_edge_color)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Songs arranged in set order. Edge: 🟢 ≤2 BPM   🟡 ≤5 BPM   🔴 >5 BPM")


# ════════════════════════════════════════════════════════════════════════════
def render_library_page() -> None:
    st.title("Song Library")

    search = st.text_input("Search by title or artist")
    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    genre_filter = st.multiselect("Filter by genre", all_mapped_genres, default=[])

    df_lib = get_library_df(search=search, genre_filter=genre_filter)
    st.caption(f"{len(df_lib)} tracks")
    st.dataframe(df_lib, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Add Track")
    with st.form("add_track", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        title = fc1.text_input("Title *")
        artist = fc2.text_input("Artist *")
        fc3, fc4, fc5 = st.columns(3)
        bpm = fc3.number_input("BPM", min_value=60.0, max_value=220.0, step=0.5, value=120.0)
        key_input = fc4.text_input("Key (Camelot, e.g. 8A)")
        genre_input = fc5.text_input("Genre")
        submitted = st.form_submit_button("Add Track", type="primary")

    if submitted:
        if not title.strip() or not artist.strip():
            st.error("Title and Artist are required.")
        elif key_input and not re.match(r"^\d{1,2}[AB]$", key_input.strip().upper()):
            st.error("Key must be Camelot format: number + A or B (e.g. 8A, 12B).")
        else:
            try:
                insert_track(
                    title=title.strip(),
                    artist=artist.strip(),
                    bpm=bpm,
                    key=key_input.strip().upper() if key_input else "",
                    genre=genre_input.strip(),
                )
                st.success(f"Added '{title.strip()}' by {artist.strip()}.")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Failed to add track: {e}")


# ════════════════════════════════════════════════════════════════════════════
def render_cluster_page() -> None:
    st.title("Cluster Songs")
    st.caption("Groups songs by BPM and Camelot key similarity using KMeans + PCA.")

    st.sidebar.title("Cluster Options")
    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    selected_genres = st.sidebar.multiselect("Genres", all_mapped_genres, default=all_mapped_genres)
    bpm_range = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    n_clusters = st.sidebar.slider("Number of clusters (k)", 2, 10, 4)

    filtered = [
        s for s in songs
        if map_genre(s.genre) in selected_genres
        and s.bpm and bpm_range[0] <= s.bpm <= bpm_range[1]
    ]

    if len(filtered) < n_clusters:
        st.warning(f"Not enough songs ({len(filtered)}) for {n_clusters} clusters. Adjust filters or reduce k.")
        return

    df = cluster_songs(filtered, n_clusters)
    fig = cluster_figure(df)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Cluster assignments")
    display_df = df[["name", "artist", "bpm", "key", "genre", "cluster"]].rename(columns={
        "name": "Title", "artist": "Artist", "bpm": "BPM",
        "key": "Key", "genre": "Raw Genre", "cluster": "Cluster",
    }).copy()
    display_df["Genre"] = display_df["Raw Genre"].apply(map_genre)
    display_df = display_df.drop(columns=["Raw Genre"]).sort_values("Cluster")

    st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.download_button(
        "Download cluster CSV",
        display_df.to_csv(index=False).encode(),
        "clusters.csv",
        "text/csv",
    )


# ════════════════════════════════════════════════════════════════════════════
# Router
# ════════════════════════════════════════════════════════════════════════════
page = st.session_state.page
if page == "home":
    render_home_page()
elif page == "visualizer":
    render_visualizer_page()
elif page == "generate_setlist":
    render_generate_page()
elif page == "library":
    render_library_page()
elif page == "cluster":
    render_cluster_page()
