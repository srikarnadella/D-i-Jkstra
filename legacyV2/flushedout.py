import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import networkx as nx
import random
from sklearn.cluster import KMeans
import numpy as np

from dj_graph import DJSetlistGraph
from legacydata.load_songs import load_songs_from_excel

#load Songs
file_path = "music_with_engineered.xlsx"
songs = load_songs_from_excel(file_path)

#genre mapping
def map_genre(raw_genre):
    genre = str(raw_genre).lower() if raw_genre else "other"
    if any(keyword in genre for keyword in ["house", "deep tech", "techno"]):
        return "Dance/House"
    elif any(keyword in genre for keyword in ["garage", "bassline", "grime"]):
        return "Dance/EDM"
    elif any(keyword in genre for keyword in ["electronic", "organic"]):
        return "Electronic"
    elif "hip-hop" in genre or "rap" in genre or "travis scott" in genre:
        return "Hip-Hop/Rap"
    elif "r&b" in genre:
        return "R&B"
    elif "pop" in genre:
        return "Pop"
    elif "dance" in genre:
        return "Dance/EDM"
    else:
        return "Other"

GENRE_COLOR_MAP = {
    "Dance/House": "blue",
    "Dance/EDM": "lime",
    "Electronic": "purple",
    "Hip-Hop/Rap": "red",
    "R&B": "pink",
    "Pop": "orange",
    "Other": "gray"
}

#init streamlit session
if "page" not in st.session_state:
    st.session_state.page = "home"
if "generated_setlist" not in st.session_state:
    st.session_state.generated_setlist = []

def go_to(page):
    st.session_state.page = page
    st.rerun()


def key_compatibility(key1, key2):
    if not key1 or not key2:
        return 5
    if key1 == key2:
        return 0
    if key1.split(" ")[0] == key2.split(" ")[0]:
        return 1
    if key1[-1] == key2[-1]: #same minor/major
        return 2
    return 4

#homepage
if st.session_state.page == "home":
    st.set_page_config(page_title="DJ Setlist App", layout="centered")

    st.markdown(
        """
        <style>
        body { background-color: #0e0e0e; }
        .title {
            text-align: center;
            font-size: 60px;
            color: white;
            margin-top: 50px;
            margin-bottom: 50px;
        }
        .stButton button {
            width: 320px;
            height: 100px;
            font-size: 28px;
            font-weight: bold;
            background-color: #1f1f1f;
            color: white;
            border: 2px solid white;
            border-radius: 12px;
            transition: all 0.3s ease;
        }
        .stButton button:hover {
            background-color: white;
            color: black;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown("<div class='title'>DJ Setlist Builder</div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Visualizer"):
            go_to("visualizer")
    with col2:
        if st.button("Generate Setlist"):
            go_to("generate_setlist")
    with col3:
        if st.button("Cluster Songs"):
            go_to("cluster_songs")

#visualizer page
elif st.session_state.page == "visualizer":
    st.set_page_config(page_title="DJ Visualizer", layout="wide")

    if st.button("Back to Home", use_container_width=True):
        go_to("home")

    st.title("DJ Setlist Visualizer")

    view_mode = st.radio("View Mode:", ["2D", "3D"], horizontal=True)

    st.sidebar.title("Filters")
    main_genres = list(set(map_genre(song.genre) for song in songs))
    selected_genres = st.sidebar.multiselect("Select Genres:", options=main_genres, default=main_genres)
    min_energy = st.sidebar.slider("Minimum Energy", 1, 10, 1)
    min_danceability = st.sidebar.slider("Minimum Danceability", 1, 10, 1)
    bpm_range = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    max_songs = st.sidebar.number_input("Max number of songs to display:", min_value=5, max_value=100, value=30)

    filtered_songs = []
    for song in songs:
        main_genre = map_genre(song.genre)
        if main_genre in selected_genres:
            if song.energy >= min_energy and song.danceability >= min_danceability:
                if bpm_range[0] <= song.bpm <= bpm_range[1]:
                    filtered_songs.append(song)
    filtered_songs = filtered_songs[:max_songs]

    st.write(f"Showing {len(filtered_songs)} songs based on your filters.")

    dj_graph = DJSetlistGraph()
    dj_graph.build_graph(filtered_songs)
    G = dj_graph.graph
#generate setlist page
elif st.session_state.page == "generate_setlist":
    st.set_page_config(page_title="DJ Setlist Generator", layout="centered")

    if st.button("Back to Home", use_container_width=True):
        go_to("home")

    st.title("Smart DJ Setlist Generator")

    genre_pick = st.multiselect("Pick Genres:", options=list(set(map_genre(song.genre) for song in songs)), default=None)
    bpm_range = st.slider("Desired BPM Range", 60, 200, (120, 135))
    min_energy = st.slider("Minimum Energy Level", 1, 10, 5)
    max_setlist_songs = st.number_input("Max Songs in Setlist", min_value=5, max_value=50, value=15)

    if st.button("Generate Setlist", use_container_width=True):
        filtered = []
        for song in songs:
            main_genre = map_genre(song.genre)
            if genre_pick and main_genre not in genre_pick:
                continue
            if not (bpm_range[0] <= song.bpm <= bpm_range[1]):
                continue
            if song.energy < min_energy:
                continue
            filtered.append(song)

        filtered = sorted(filtered, key=lambda s: s.bpm)
        st.session_state.generated_setlist = filtered[:max_setlist_songs]

        st.success(f"Generated {len(st.session_state.generated_setlist)} song setlist!")

        for idx, song in enumerate(st.session_state.generated_setlist, start=1):
            st.markdown(f"**{idx}. {song.name}** by *{song.artist}* — {song.bpm} BPM — {song.key}")

    if st.session_state.generated_setlist and st.button("Smoothest Setlist (Dijkstra)", use_container_width=True):
        G = nx.DiGraph()

        for idx_a, song_a in enumerate(st.session_state.generated_setlist):
            for idx_b, song_b in enumerate(st.session_state.generated_setlist):
                if idx_a == idx_b:
                    continue
                bpm_diff = abs(song_a.bpm - song_b.bpm)
                key_penalty = key_compatibility(song_a.key, song_b.key)
                total_weight = bpm_diff + (key_penalty * 2)
                G.add_edge(idx_a, idx_b, weight=total_weight)

        # Find shortest path visiting all nodes
        start = 0
        path = [start]
        visited = set(path)

        while len(visited) < len(st.session_state.generated_setlist):
            last = path[-1]
            next_node = min(
                (n for n in G.neighbors(last) if n not in visited),
                key=lambda n: G[last][n]['weight'],
                default=None
            )
            if next_node is None:
                break
            path.append(next_node)
            visited.add(next_node)

        smooth_list = [st.session_state.generated_setlist[i] for i in path]

        st.success(f"Smooth setlist reordered!")
        for idx, song in enumerate(smooth_list, start=1):
            st.markdown(f"**{idx}. {song.name}** by *{song.artist}* — {song.bpm} BPM — {song.key}")

#cluster songs page
elif st.session_state.page == "cluster_songs":
    st.set_page_config(page_title="DJ Cluster Songs", layout="wide")

    if st.button("Back to Home", use_container_width=True):
        go_to("home")

    st.title("🎶 Cluster Songs (K-Means)")

    n_clusters = st.slider("Number of Clusters", 2, 10, 4)

    df = pd.DataFrame([{
        "name": s.name,
        "artist": s.artist,
        "bpm": s.bpm,
        "energy": s.energy,
        "danceability": s.danceability
    } for s in songs])

    X = df[["bpm", "energy", "danceability"]]
    kmeans = KMeans(n_clusters=n_clusters, random_state=42).fit(X)
    df["cluster"] = kmeans.labels_

    st.write(f"Songs grouped into {n_clusters} clusters.")

    cluster_colors = ['#FF5733', '#33FFCE', '#33A1FF', '#FF33E3', '#9DFF33', '#FFBD33', '#8D33FF', '#33FF57', '#FF3333', '#33FFF5']

    fig = go.Figure()

    for cluster_id in sorted(df["cluster"].unique()):
        cluster_data = df[df["cluster"] == cluster_id]
        fig.add_trace(go.Scatter(
            x=cluster_data["bpm"],
            y=cluster_data["energy"],
            mode="markers+text",
            marker=dict(size=12, color=cluster_colors[cluster_id % len(cluster_colors)], line=dict(width=0)),
            text=cluster_data["name"],
            name=f"Cluster {cluster_id}"
        ))

    fig.update_layout(
        paper_bgcolor="#0e0e0e",
        plot_bgcolor="#0e0e0e",
        xaxis=dict(title="BPM", showgrid=False, zeroline=False),
        yaxis=dict(title="Energy", showgrid=False, zeroline=False),
        showlegend=True,
        font=dict(color="white"),
        margin=dict(l=20, r=20, t=20, b=20)
    )

    st.plotly_chart(fig, use_container_width=True)
