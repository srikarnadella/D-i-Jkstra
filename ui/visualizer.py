"""Visualizer page: harmonic graph (3D/2D), Dijkstra path finder, compatibility score."""
import random
import pandas as pd
import streamlit as st
from models import (
    Song, map_genre, key_compat_label, parse_key, song_id, song_label,
)
from db import adapt_uploaded_csv
from setlist_engine import find_harmonic_path, compatibility
from viz import (
    stable_3d_positions, spring_layout_2d, build_3d_figure, build_2d_figure, bpm_edge_color,
)
from dj_graph import DJSetlistGraph
from ui.common import _highlight_compat, _sequence_figure


def render(songs: list[Song]) -> None:
    st.title("Key graph")
    st.markdown('<p class="lede">Every pair of tracks you can mix between, as a graph. Find the smoothest '
                'route from one track to another, or score how well two tracks mix.</p>',
                unsafe_allow_html=True)

    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    with st.container(key="card_filters"):
        f1, f2, f3, f4 = st.columns([2.2, 1.4, 1.4, 1])
        selected_genres = f1.multiselect("Genres", all_mapped_genres, default=all_mapped_genres)
        bpm_range = f2.slider("BPM", 60, 200, (60, 200))
        key_range = f3.slider("Camelot keys", 1, 12, (1, 12))
        view_mode = f4.segmented_control("View", ["3D", "2D"], default="3D") or "3D"
        with st.expander("More filters"):
            m1, m2, m3 = st.columns([1.4, 1, 2])
            artist_search = m1.text_input("Artist contains")
            max_songs = m2.number_input("Max tracks", min_value=5, max_value=200, value=30)
            uploaded_csv = m3.file_uploader("Or graph a CSV setlist", type=["csv"])
    edge_mode = "BPM-based"

    if uploaded_csv:
        try:
            raw_df = pd.read_csv(uploaded_csv)
            df_up = adapt_uploaded_csv(raw_df)
            filtered_songs = [Song(*row) for row in df_up.itertuples(index=False)]
            st.caption(f"Graphing {len(filtered_songs):,} tracks from the CSV; the filters above are ignored.")
        except Exception as e:
            st.error(str(e))
            filtered_songs = []
    else:
        filtered_songs = [
            s for s in songs
            if map_genre(s.genre) in selected_genres
            and s.bpm is not None and bpm_range[0] <= s.bpm <= bpm_range[1]
            and (not artist_search or artist_search.lower() in s.artist.lower())
            and ((kn := parse_key(s.key)[0]) is None or key_range[0] <= kn <= key_range[1])
        ]
        if len(filtered_songs) > max_songs:
            # Seeded sample (not first-N alphabetical) so the graph spans the library
            filtered_songs = random.Random(42).sample(filtered_songs, int(max_songs))


    if not filtered_songs:
        st.info("No songs match the current filters.")
        return

    dj_graph = DJSetlistGraph()
    dj_graph.build_harmonic_graph(filtered_songs)
    G = dj_graph.graph
    st.markdown(f'<p class="card-sub">{G.number_of_nodes():,} tracks · {G.number_of_edges():,} mixable '
                'transitions</p>', unsafe_allow_html=True)
    color_fn = bpm_edge_color if edge_mode == "BPM-based" else None

    if view_mode == "3D":
        pos = stable_3d_positions(G)
        fig = build_3d_figure(G, pos, edge_color_fn=color_fn)
    else:
        pos = spring_layout_2d(G)
        fig = build_2d_figure(G, pos, edge_color_fn=color_fn)

    tab_graph, tab_path, tab_compat = st.tabs(["Graph", "Find a path", "Compare two tracks"])

    with tab_graph:
        st.plotly_chart(fig, width="stretch")
        st.caption("Brighter amber dots are higher-energy tracks. Brighter lines are smaller BPM changes: "
                   "2 BPM or less, then 5 or less, then more. Hover for titles and keys.")

    with tab_path:
        st.subheader("Smoothest route between two tracks")
        st.caption("Dijkstra's shortest path, where a step costs its BPM change plus its key distance.")

        if len(filtered_songs) >= 2:
            col_a, col_b = st.columns(2)
            source = col_a.selectbox("From song", filtered_songs, format_func=song_label, key="path_source")
            target_options = [s for s in filtered_songs if song_id(s) != song_id(source)]
            target = col_b.selectbox("To song", target_options, format_func=song_label, key="path_target")

            current_path_key = (song_id(source), song_id(target),
                                frozenset(song_id(s) for s in filtered_songs))

            if st.button("Find Shortest Path", type="primary"):
                st.session_state.viz_path_result = find_harmonic_path(
                    filtered_songs, song_id(source), song_id(target))
                st.session_state.viz_path_key = current_path_key

            if st.session_state.viz_path_key == current_path_key:
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
                    styled_path = pd.DataFrame(path_rows).style.map(_highlight_compat, subset=["Key Compat"])
                    st.dataframe(styled_path, width="stretch", hide_index=True)
                    st.plotly_chart(_sequence_figure(path), width="stretch")
                else:
                    st.warning("No harmonic path found — these songs aren't connected through compatible keys.")
        else:
            st.info("Load at least 2 songs to use the path finder.")

    with tab_compat:
        st.subheader("How well do two tracks mix?")
        st.caption("Instant read on how well any two songs mix — key, BPM, and graph distance all factor in.")

        if len(filtered_songs) >= 2:
            cc1, cc2 = st.columns(2)
            song_a = cc1.selectbox("Song A", filtered_songs, format_func=song_label, key="compat_a")
            b_opts = [s for s in filtered_songs if song_id(s) != song_id(song_a)]
            song_b = cc2.selectbox("Song B", b_opts, format_func=song_label, key="compat_b")

            c = compatibility(filtered_songs, song_a, song_b)
            hops, path = c["hops"], c["path"]

            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Compatibility", f"{c['score']}/100")
            sc2.metric("Key", c["key_label"])
            sc3.metric("BPM Δ", f"{c['bpm_delta']:.1f}" + (" (half/double-time)" if c["octave"] else ""))
            sc4.metric("Graph hops", hops if hops is not None else "∞")

            if c["key_label"] == "Same":
                st.success("Perfect key match — can mix at any point.")
            elif c["key_label"] == "Harmonic":
                st.success("Harmonically compatible — smooth key transition.")
            elif hops and hops <= 3:
                st.info(f"Not directly compatible, but reachable in {hops} hop(s) via bridge songs.")
            else:
                st.warning("These songs don't share a harmonic path — mixing them directly will clash.")

            if path and len(path) > 2:
                st.caption("Shortest bridge: " + " → ".join(f"**{s.name}**" for s in path))
        else:
            st.info("Load at least 2 songs to use the compatibility scorer.")
