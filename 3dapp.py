import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, timedelta

from models import (
    Song, map_genre, GENRE_COLOR_MAP, key_compat_label, parse_key,
    get_harmonic_neighbors, TRACK_DURATION_SECONDS, VIBE_CONFIG,
)
from db import (
    get_songs, get_tracks_df, get_library_df,
    insert_track, save_library_changes, adapt_uploaded_csv,
    save_setlist, get_saved_setlists, delete_setlist,
)
from setlist_engine import (
    score_track, build_harmonic_graph_setlist,
    smoothest_setlist, cluster_songs, find_harmonic_path, _bpm_compatible,
)
from viz import (
    stable_3d_positions, circular_layout_3d, spring_layout_2d,
    build_3d_figure, build_2d_figure, bpm_edge_color,
    setlist_to_csv_bytes, cluster_figure, energy_timeline_figure,
    camelot_wheel_figure,
)
from dj_graph import DJSetlistGraph


@st.cache_data(ttl=300)
def _cached_cluster_songs(songs_tuple: tuple, n_clusters: int):
    """Cache-friendly wrapper — Song namedtuples are hashable."""
    return cluster_songs(list(songs_tuple), n_clusters)


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
if "setlist_start_time" not in st.session_state:
    st.session_state.setlist_start_time = None
if "show_setlist_viz" not in st.session_state:
    st.session_state.show_setlist_viz = False
if "viz_path_result" not in st.session_state:
    st.session_state.viz_path_result = None
if "viz_path_key" not in st.session_state:
    st.session_state.viz_path_key = None
if "cluster_filter_names" not in st.session_state:
    st.session_state.cluster_filter_names = None
if "cluster_filter_label" not in st.session_state:
    st.session_state.cluster_filter_label = None
if "pinned_opener" not in st.session_state:
    st.session_state.pinned_opener = None
if "pinned_closer" not in st.session_state:
    st.session_state.pinned_closer = None
if "loaded_setlist_name" not in st.session_state:
    st.session_state.loaded_setlist_name = None

PAGES = ["home", "visualizer", "generate_setlist", "library", "cluster"]
PAGE_LABELS = {
    "home": "Home", "visualizer": "Visualizer",
    "generate_setlist": "Generate Setlist", "library": "Library",
    "cluster": "Cluster Songs",
}


def go_to(page: str) -> None:
    st.session_state.page = page
    st.rerun()


# ── Shared helpers ────────────────────────────────────────────────────────────

def _highlight_compat(val: str) -> str:
    if val == "Non-harmonic":
        return "background-color: #3d0000; color: #ff6b6b"
    if val == "Same":
        return "background-color: #003d00; color: #6bff6b"
    return ""


def _build_path_graph(path_songs: list[Song]) -> nx.DiGraph:
    """Build a directed path graph (node per song, edge per consecutive pair)."""
    G = nx.DiGraph()
    for idx, song in enumerate(path_songs):
        G.add_node(idx, name=song.name, artist=song.artist,
                   bpm=song.bpm, key=song.key, genre=song.genre)
    for idx in range(len(path_songs) - 1):
        a, b = path_songs[idx], path_songs[idx + 1]
        G.add_edge(idx, idx + 1,
                   bpm_diff=round(b.bpm - a.bpm, 1),
                   key_change=f"{a.key}→{b.key}")
    return G


def _fmt_clock(base_time: datetime, offset_seconds: int) -> str:
    t = (base_time + timedelta(seconds=offset_seconds)).time()
    return t.strftime("%H:%M")


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
        <div style='font-size:14px; color:#555; margin-top:8px;'>
            Generate harmonic setlists via Dijkstra's algorithm &nbsp;·&nbsp;
            Visualize transitions as a 3D graph &nbsp;·&nbsp;
            Cluster songs by BPM &amp; key
        </div>
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
    bpms = [s.bpm for s in songs if s.bpm]
    genre_counts: dict[str, int] = {}
    for s in songs:
        g = map_genre(s.genre)
        genre_counts[g] = genre_counts.get(g, 0) + 1
    unique_keys = len({s.key for s in songs if s.key})

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Library Size", f"{len(songs)} tracks")
    m2.metric("Top Genre", max(genre_counts, key=genre_counts.get) if genre_counts else "—")
    m3.metric("Avg BPM", f"{sum(bpms)/len(bpms):.0f}" if bpms else "—")
    m4.metric("Unique Keys", unique_keys)

    st.markdown("<br>", unsafe_allow_html=True)

    home_left, home_right = st.columns([3, 2])

    with home_left:
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

    with home_right:
        st.subheader("Camelot key distribution")
        st.plotly_chart(camelot_wheel_figure(songs), use_container_width=True)

    # ── Saved setlists panel ─────────────────────────────────────────────────
    saved = get_saved_setlists()
    if saved:
        st.subheader("Saved setlists")
        for sl in saved[:5]:
            with st.container():
                sl_col1, sl_col2, sl_col3 = st.columns([4, 1, 1])
                sl_col1.markdown(
                    f"**{sl['name']}** &nbsp; <span style='color:#888;font-size:13px'>"
                    f"{sl['vibe']} · {len(sl['songs'])} tracks · {sl['created_at']}</span>",
                    unsafe_allow_html=True,
                )
                if sl_col2.button("Load", key=f"load_sl_{sl['id']}"):
                    st.session_state.generated_setlist = sl["songs"]
                    st.session_state.loaded_setlist_name = sl["name"]
                    st.session_state.setlist_start_time = None
                    go_to("generate_setlist")
                if sl_col3.button("Delete", key=f"del_sl_{sl['id']}"):
                    delete_setlist(sl["id"])
                    st.rerun()
        if len(saved) > 5:
            st.caption(f"…and {len(saved) - 5} more. Go to Generate page to manage.")


# ════════════════════════════════════════════════════════════════════════════
def render_visualizer_page() -> None:
    st.title("Visualizer")

    st.sidebar.title("Filters")
    view_mode = st.sidebar.radio("View mode", ["3D", "2D"], horizontal=True)
    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    selected_genres = st.sidebar.multiselect("Genres", all_mapped_genres, default=all_mapped_genres)
    artist_search = st.sidebar.text_input("Artist contains")
    bpm_range = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    key_range = st.sidebar.slider("Camelot key range", 1, 12, (1, 12))
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
            and ((kn := parse_key(s.key)[0]) is None or key_range[0] <= kn <= key_range[1])
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

    tab_graph, tab_path, tab_compat = st.tabs(["Harmonic Graph", "Find Path (Dijkstra)", "Song Compatibility"])

    with tab_graph:
        st.plotly_chart(fig, use_container_width=True)
        with st.expander("Legend"):
            genre_cols = st.columns(len(GENRE_COLOR_MAP))
            for col, (genre, color) in zip(genre_cols, GENRE_COLOR_MAP.items()):
                col.markdown(f"<span style='color:{color}'>■</span> {genre}", unsafe_allow_html=True)
            if edge_mode == "BPM-based":
                st.caption("Edge color: 🟢 ≤2 BPM &nbsp;&nbsp; 🟡 ≤5 BPM &nbsp;&nbsp; 🔴 >5 BPM")

    with tab_path:
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

                    G_path = _build_path_graph(path)
                    pos_path = circular_layout_3d(list(G_path.nodes))
                    fig_path = build_3d_figure(G_path, pos_path, edge_color_fn=bpm_edge_color)
                    st.plotly_chart(fig_path, use_container_width=True)
                else:
                    st.warning("No harmonic path found — these songs aren't connected through compatible keys.")
        else:
            st.info("Load at least 2 songs to use the path finder.")

    with tab_compat:
        st.subheader("Song Compatibility Score")
        st.caption("Instant read on how well any two songs mix — key, BPM, and graph distance all factor in.")

        if len(filtered_songs) >= 2:
            song_names = [s.name for s in filtered_songs]
            cc1, cc2 = st.columns(2)
            compat_a = cc1.selectbox("Song A", song_names, key="compat_a")
            compat_b_opts = [n for n in song_names if n != compat_a]
            compat_b = cc2.selectbox("Song B", compat_b_opts, key="compat_b") if compat_b_opts else None

            if compat_b:
                song_a = next(s for s in filtered_songs if s.name == compat_a)
                song_b = next(s for s in filtered_songs if s.name == compat_b)

                compat_label = key_compat_label(song_a.key, song_b.key)
                bpm_diff = abs(song_a.bpm - song_b.bpm)
                bpm_octave = _bpm_compatible(song_a.bpm, song_b.bpm) and bpm_diff > 25

                # Path length via Dijkstra (None = unreachable)
                path = find_harmonic_path(filtered_songs, compat_a, compat_b)
                path_len = len(path) - 1 if path else None

                # Composite score: 0–100
                key_score = {"Same": 40, "Harmonic": 25, "?": 5}.get(compat_label, 0)
                bpm_score = max(0, 30 - bpm_diff)
                graph_score = 30 if path_len == 1 else (20 if path_len == 2 else (10 if path_len and path_len <= 4 else 0))
                total_score = min(100, key_score + bpm_score + graph_score)

                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("Compatibility", f"{total_score}/100")
                sc2.metric("Key", compat_label)
                sc3.metric("BPM Δ", f"{bpm_diff:.1f}" + (" (octave)" if bpm_octave else ""))
                sc4.metric("Graph hops", path_len if path_len is not None else "∞")

                if compat_label == "Same":
                    st.success("Perfect key match — can mix at any point.")
                elif compat_label == "Harmonic":
                    st.success("Harmonically compatible — smooth key transition.")
                elif path_len and path_len <= 3:
                    st.info(f"Not directly compatible, but reachable in {path_len} hop(s) via bridge songs.")
                else:
                    st.warning("These songs don't share a harmonic path — mixing them directly will clash.")

                if path and len(path) > 2:
                    st.caption("Shortest bridge: " + " → ".join(f"**{s.name}**" for s in path))
        else:
            st.info("Load at least 2 songs to use the compatibility scorer.")


# ════════════════════════════════════════════════════════════════════════════
def render_generate_page() -> None:
    st.title("Generate Setlist")

    cluster_filter = st.session_state.get("cluster_filter_names")
    cluster_label = st.session_state.get("cluster_filter_label")
    if cluster_filter:
        col_info, col_clear = st.columns([5, 1])
        col_info.info(f"Generating from **{cluster_label}** — {len(cluster_filter)} songs pre-selected.")
        if col_clear.button("Clear", help="Remove cluster filter"):
            st.session_state.cluster_filter_names = None
            st.session_state.cluster_filter_label = None
            st.rerun()

    # ── Time window ──────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        start_time = st.time_input("Start time", value=datetime.strptime("23:00", "%H:%M").time())
    with c2:
        end_time = st.time_input("End time", value=datetime.strptime("01:00", "%H:%M").time())
    overnight = st.checkbox("Overnight set (ends next day)", value=(end_time <= start_time))

    # ── Vibe + generation options ─────────────────────────────────────────────
    col_vibe, col_seed = st.columns([3, 1])
    vibe = col_vibe.selectbox("Vibe", [v.title() for v in VIBE_CONFIG])
    reproducible = col_seed.checkbox("Reproducible", value=False,
                                     help="Fixed seed — same inputs always produce the same setlist")

    bpm_target = st.slider("BPM range filter", 60, 220, (60, 220),
                           help="Only tracks within this BPM range are eligible for the set")
    auto_segment = st.checkbox("Auto-segment by energy curve", value=True)

    # ── Track pinning ─────────────────────────────────────────────────────────
    with st.expander("Pin opener / closer (optional)"):
        song_names_all = ["— None —"] + [s.name for s in songs]
        pin_col1, pin_col2 = st.columns(2)
        opener_choice = pin_col1.selectbox("Opener (first track)", song_names_all, key="pin_opener")
        closer_choice = pin_col2.selectbox("Closer (last track)", song_names_all, key="pin_closer")
        pinned_opener = None if opener_choice == "— None —" else next(
            (s for s in songs if s.name == opener_choice), None)
        pinned_closer = None if closer_choice == "— None —" else next(
            (s for s in songs if s.name == closer_choice), None)

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
        rng = __import__("random").Random(42) if reproducible else None

        tracks_df = get_tracks_df()
        if cluster_filter:
            tracks_df = tracks_df[tracks_df["track_title"].isin(cluster_filter)]

        # Remove pinned songs from the pool so they don't appear twice
        pinned_names = {s.name for s in [pinned_opener, pinned_closer] if s}
        pool_df = tracks_df[~tracks_df["track_title"].isin(pinned_names)].copy()

        pool_df["vibe_score"] = pool_df.apply(
            lambda row: score_track(row, vibe, rng=rng), axis=1
        )

        # Reserve time for pinned songs
        pin_budget = sum(1 for s in [pinned_opener, pinned_closer] if s) * TRACK_DURATION_SECONDS
        middle_duration = max(0, total_duration - pin_budget)

        best_set = build_harmonic_graph_setlist(
            pool_df.to_dict("records"),
            total_duration_seconds=middle_duration,
            use_auto_segmentation=auto_segment,
            bpm_range=(bpm_target[0], bpm_target[1]) if bpm_target != (60, 220) else None,
        )

        middle_songs = [
            Song(t["track_title"], t["artist"], t["genre"], t["bpm"], t["key"])
            for t in best_set
        ]

        # Stitch pinned songs around the middle using Dijkstra bridges
        final_songs: list[Song] = []
        if pinned_opener:
            final_songs.append(pinned_opener)
            if middle_songs:
                bridge = find_harmonic_path(songs, pinned_opener.name, middle_songs[0].name)
                bridge_middle = (bridge[1:-1] if bridge and len(bridge) > 2 else [])
                final_songs.extend(bridge_middle)
        final_songs.extend(middle_songs)
        if pinned_closer:
            if final_songs:
                bridge = find_harmonic_path(songs, final_songs[-1].name, pinned_closer.name)
                bridge_middle = (bridge[1:-1] if bridge and len(bridge) > 2 else [])
                final_songs.extend(bridge_middle)
            final_songs.append(pinned_closer)

        if not final_songs:
            st.warning(
                "No tracks matched this vibe and time window. "
                "Try a different vibe or a wider time range."
            )
            st.session_state.generated_setlist = []
            st.session_state.setlist_start_time = None
            st.stop()

        st.session_state.generated_setlist = final_songs
        st.session_state.setlist_start_time = start_dt
        st.session_state.loaded_setlist_name = None
        total_min = len(final_songs) * TRACK_DURATION_SECONDS
        st.success(
            f"Generated {len(final_songs)} tracks "
            f"(~{total_min // 3600}h {(total_min % 3600) // 60}m)"
        )

    setlist: list[Song] = st.session_state.get("generated_setlist", [])
    if not setlist:
        return

    start_dt: datetime | None = st.session_state.get("setlist_start_time")

    # ── Quality metrics ───────────────────────────────────────────────────────
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
        total_sec = len(setlist) * TRACK_DURATION_SECONDS

        qm1, qm2, qm3, qm4, qm5 = st.columns(5)
        qm1.metric("Quality Score", f"{quality:.0f}/100")
        qm2.metric("Tracks", len(setlist))
        qm3.metric("Duration", f"{total_sec // 3600}h {(total_sec % 3600) // 60}m")
        qm4.metric("Harmonic Transitions", f"{pct_harmonic:.0%}")
        qm5.metric("Avg BPM Δ", f"{avg_bpm_delta:.1f}")

    # ── Setlist table ─────────────────────────────────────────────────────────
    rows = []
    for i, song in enumerate(setlist):
        prev = setlist[i - 1] if i > 0 else None
        row = {
            "#": i + 1,
            "Title": song.name,
            "Artist": song.artist,
            "BPM": song.bpm,
            "Key": song.key,
            "Genre": map_genre(song.genre),
            "BPM Δ": f"{song.bpm - prev.bpm:+.1f}" if prev else "—",
            "Key Compat": key_compat_label(prev.key, song.key) if prev else "—",
        }
        if start_dt:
            row["Time"] = _fmt_clock(start_dt, i * TRACK_DURATION_SECONDS)
        rows.append(row)

    setlist_df = pd.DataFrame(rows)
    if start_dt:
        cols = ["#", "Time", "Title", "Artist", "BPM", "Key", "Genre", "BPM Δ", "Key Compat"]
        setlist_df = setlist_df[cols]
    styled = setlist_df.style.map(_highlight_compat, subset=["Key Compat"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Actions ───────────────────────────────────────────────────────────────
    act1, act2, act3, act4 = st.columns(4)
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
        st.caption("Greedy nearest-neighbor reorder — minimizes BPM jumps and key changes between consecutive tracks.")
    with act3:
        if st.button("Visualize Setlist", use_container_width=True):
            st.session_state.show_setlist_viz = True
    with act4:
        default_name = st.session_state.get("loaded_setlist_name") or f"{vibe} set"
        save_name = st.text_input("Save as", value=default_name, label_visibility="collapsed",
                                  placeholder="Name this setlist…")
        if st.button("Save Setlist", use_container_width=True):
            sid = save_setlist(save_name or "Untitled", vibe, setlist)
            st.session_state.loaded_setlist_name = save_name
            st.success(f"Saved as **{save_name}** (#{sid})")

    # ── Energy Timeline ───────────────────────────────────────────────────────
    st.subheader("Energy Timeline")
    timeline_x = None
    if start_dt:
        timeline_x = [_fmt_clock(start_dt, i * TRACK_DURATION_SECONDS) for i in range(len(setlist))]
    st.plotly_chart(energy_timeline_figure(setlist, x_labels=timeline_x), use_container_width=True)
    st.caption("Marker color: first track (gray) | Same key (green) | Harmonic (yellow) | Non-harmonic (red)")

    if st.session_state.show_setlist_viz:
        G = _build_path_graph(setlist)
        pos = circular_layout_3d(list(G.nodes))
        fig = build_3d_figure(G, pos, edge_color_fn=bpm_edge_color)
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Songs arranged in set order. Edge: 🟢 ≤2 BPM   🟡 ≤5 BPM   🔴 >5 BPM")


# ════════════════════════════════════════════════════════════════════════════
def render_library_page() -> None:
    st.title("Song Library")

    search = st.text_input("Search by title or artist")
    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    filter_col1, filter_col2 = st.columns([3, 1])
    genre_filter = filter_col1.multiselect("Filter by genre", all_mapped_genres, default=[])
    show_orphans = filter_col2.checkbox(
        "Orphans only",
        help="Show only songs with zero harmonic neighbors — these will never appear in a generated setlist",
    )

    df_lib = get_library_df(search=search, genre_filter=genre_filter)

    if show_orphans:
        # Compute which songs have no harmonic neighbors in the full library
        all_keys = {s.key.strip().upper() for s in songs if s.key}
        orphan_titles = {
            s.name for s in songs
            if not any(
                nb in all_keys and nb != s.key.strip().upper()
                for nb in get_harmonic_neighbors(s.key)
            )
        }
        df_lib = df_lib[df_lib["Title"].isin(orphan_titles)]
        st.warning(f"{len(df_lib)} harmonic orphan(s) — these songs have no compatible keys in the library.")

    st.caption(f"{len(df_lib)} tracks — check 'Delete?' and click **Save Changes** to remove rows, or edit BPM/Key/Genre inline.")

    editor_df = df_lib.copy()
    editor_df.insert(0, "Delete?", False)

    # Key includes filter state so any filter change resets edit state,
    # preventing stale edits from being applied to wrong rows.
    editor_key = f"library_editor_{hash(search)}_{hash(tuple(sorted(genre_filter)))}"
    edited = st.data_editor(
        editor_df,
        column_config={
            "Delete?": st.column_config.CheckboxColumn(help="Mark row for deletion"),
            "Title": st.column_config.TextColumn(disabled=True),
            "Artist": st.column_config.TextColumn(disabled=True),
            "BPM": st.column_config.NumberColumn(min_value=60.0, max_value=220.0, step=0.5),
            "Key": st.column_config.TextColumn(help="Camelot format: e.g. 8A, 12B"),
            "Genre": st.column_config.TextColumn(),
        },
        hide_index=True,
        use_container_width=True,
        key=editor_key,
    )

    if st.button("Save Changes", type="primary"):
        to_delete = [
            (row["Title"], row["Artist"])
            for _, row in edited.iterrows()
            if row["Delete?"]
        ]
        to_update = []
        for (_, orig_row), (_, edit_row) in zip(df_lib.iterrows(), edited.iterrows()):
            if edit_row["Delete?"]:
                continue
            if (orig_row["BPM"] != edit_row["BPM"]
                    or orig_row["Key"] != edit_row["Key"]
                    or orig_row["Genre"] != edit_row["Genre"]):
                to_update.append(edit_row)

        errors = []
        for row in to_update:
            key_val = str(row["Key"] or "").strip().upper()
            if key_val and parse_key(key_val)[0] is None:
                errors.append(f"'{row['Title']}' has invalid key '{row['Key']}' — must be Camelot format (e.g. 8A).")

        if errors:
            for e in errors:
                st.error(e)
        else:
            if to_delete or to_update:
                save_library_changes(
                    to_delete=to_delete,
                    to_update=[
                        {
                            "title": row["Title"], "artist": row["Artist"],
                            "bpm": float(row["BPM"]),
                            "key": str(row["Key"] or "").strip().upper(),
                            "genre": str(row["Genre"] or "").strip(),
                        }
                        for row in to_update
                    ],
                )
                n_del = len(to_delete)
                n_upd = len(to_update)
                parts = []
                if n_del:
                    parts.append(f"Deleted {n_del} track{'s' if n_del != 1 else ''}")
                if n_upd:
                    parts.append(f"Updated {n_upd} track{'s' if n_upd != 1 else ''}")
                st.success(". ".join(parts) + ".")
                st.cache_data.clear()
                st.rerun()
            else:
                st.info("No changes detected.")

    st.divider()
    imp_col, add_col = st.columns([1, 1])

    with imp_col:
        st.subheader("Bulk Import CSV")
        st.caption("CSV must have columns: Title (or track_title), Artist, BPM, Key, Genre.")
        import_file = st.file_uploader("Upload CSV", type=["csv"], key="lib_csv_import")
        if import_file:
            try:
                raw_df = pd.read_csv(import_file)
                adapted = adapt_uploaded_csv(raw_df)
                n_inserted = 0
                n_skipped = 0
                for _, row in adapted.iterrows():
                    ok = insert_track(
                        title=str(row["name"]).strip(),
                        artist=str(row["artist"]).strip(),
                        bpm=float(row["bpm"]),
                        key=str(row["key"] or "").strip().upper(),
                        genre=str(row["genre"] or "").strip(),
                    )
                    if ok:
                        n_inserted += 1
                    else:
                        n_skipped += 1
                parts = []
                if n_inserted:
                    parts.append(f"Imported {n_inserted} new track{'s' if n_inserted != 1 else ''}")
                if n_skipped:
                    parts.append(f"{n_skipped} already existed")
                st.success(". ".join(parts) + ".")
                if n_inserted > 0:
                    st.cache_data.clear()
                    st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

    with add_col:
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
            elif key_input and parse_key(key_input.strip().upper())[0] is None:
                st.error("Key must be Camelot format: number + A or B (e.g. 8A, 12B).")
            else:
                try:
                    inserted = insert_track(
                        title=title.strip(),
                        artist=artist.strip(),
                        bpm=bpm,
                        key=key_input.strip().upper() if key_input else "",
                        genre=genre_input.strip(),
                    )
                    if inserted:
                        st.success(f"Added '{title.strip()}' by {artist.strip()}.")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.warning(
                            f"'{title.strip()}' by {artist.strip()} already exists in the library."
                        )
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

    df = _cached_cluster_songs(tuple(filtered), n_clusters)

    # Build cluster summary labels: centroid BPM + dominant mapped genre
    cluster_labels: dict[int, str] = {}
    for cid in sorted(df["cluster"].unique()):
        sub = df[df["cluster"] == cid]
        centroid_bpm = int(round(sub["bpm"].mean()))
        dominant_genre = sub["genre"].apply(map_genre).mode()
        genre_str = dominant_genre.iloc[0] if not dominant_genre.empty else "Mixed"
        cluster_labels[int(cid)] = f"Cluster {cid} — {centroid_bpm} BPM / {genre_str}"

    fig = cluster_figure(df, cluster_labels=cluster_labels)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Cluster assignments")
    display_df = df[["name", "artist", "bpm", "key", "genre", "cluster"]].rename(columns={
        "name": "Title", "artist": "Artist", "bpm": "BPM",
        "key": "Key", "genre": "Raw Genre", "cluster": "Cluster",
    }).copy()
    display_df["Genre"] = display_df["Raw Genre"].apply(map_genre)
    display_df["Cluster Name"] = display_df["Cluster"].map(cluster_labels)
    display_df = display_df.drop(columns=["Raw Genre"]).sort_values("Cluster")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    st.subheader("Generate setlist from a cluster")
    st.caption("Pre-loads that cluster's songs into the Generate page, then lets you pick vibe and time.")
    items = sorted(cluster_labels.items())
    for row_start in range(0, len(items), 4):
        row_items = items[row_start:row_start + 4]
        btn_cols = st.columns(len(row_items))
        for col, (cid, label) in zip(btn_cols, row_items):
            if col.button(label, use_container_width=True, key=f"gen_cluster_{cid}"):
                names = df[df["cluster"] == cid]["name"].tolist()
                st.session_state.cluster_filter_names = set(names)
                st.session_state.cluster_filter_label = label
                go_to("generate_setlist")

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
