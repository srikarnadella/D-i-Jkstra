"""Cluster page: KMeans clusters of the library, hand-off to Generate."""
import streamlit as st
from models import Song, map_genre
from setlist_engine import cluster_songs
from viz import cluster_figure
from ui.common import go_to


@st.cache_data(ttl=300)
def _cached_cluster_songs(songs_tuple: tuple, n_clusters: int):
    """Cache-friendly wrapper — Song namedtuples are hashable."""
    return cluster_songs(list(songs_tuple), n_clusters)


def render(songs: list[Song]) -> None:
    st.title("Clusters")
    st.markdown('<p class="lede">Tracks grouped by tempo and key (KMeans), so you can build a set from '
                'one group.</p>', unsafe_allow_html=True)

    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    with st.container(key="card_filters"):
        f1, f2, f3 = st.columns([2.4, 1.4, 1.2])
        selected_genres = f1.multiselect("Genres", all_mapped_genres, default=all_mapped_genres)
        bpm_range = f2.slider("BPM", 60, 200, (60, 200))
        n_clusters = f3.slider("Groups", 2, 10, 4)

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
        cluster_labels[int(cid)] = f"Group {int(cid) + 1} · {centroid_bpm} BPM · {genre_str}"

    fig = cluster_figure(df, cluster_labels=cluster_labels)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    st.subheader("Tracks by group")
    display_df = df[["name", "artist", "bpm", "key", "genre", "cluster"]].rename(columns={
        "name": "Title", "artist": "Artist", "bpm": "BPM",
        "key": "Key", "genre": "Raw Genre", "cluster": "Cluster",
    }).copy()
    display_df["Genre"] = display_df["Raw Genre"].apply(map_genre)
    display_df = display_df.sort_values("Cluster")
    display_df["Group"] = display_df["Cluster"].map(cluster_labels)
    display_df = display_df.drop(columns=["Raw Genre", "Cluster"])

    st.dataframe(display_df, width="stretch", hide_index=True,
                 column_config={"BPM": st.column_config.NumberColumn(format="%.1f")})

    st.subheader("Build a set from one group")
    st.caption("Pre-loads that cluster's songs into the Generate page, then lets you pick vibe and time.")
    items = sorted(cluster_labels.items())
    for row_start in range(0, len(items), 4):
        row_items = items[row_start:row_start + 4]
        btn_cols = st.columns(len(row_items))
        for col, (cid, label) in zip(btn_cols, row_items):
            if col.button(label, width="stretch", key=f"gen_cluster_{cid}"):
                sub = df[df["cluster"] == cid]
                st.session_state.cluster_filter_ids = set(zip(sub["name"], sub["artist"]))
                st.session_state.cluster_filter_label = label
                go_to("generate_setlist")

    st.download_button(
        "Download cluster CSV",
        display_df.to_csv(index=False).encode(),
        "clusters.csv",
        "text/csv",
    )
