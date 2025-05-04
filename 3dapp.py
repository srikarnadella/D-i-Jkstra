import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import networkx as nx
import random

from dj_graph import DJSetlistGraph
from load_songs import load_songs_from_excel

# Load Songs
file_path = "music_with_engineered.xlsx"
songs = load_songs_from_excel(file_path)

# Genre Mapping
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

# Streamlit page control
if "page" not in st.session_state:
    st.session_state.page = "home"
if "generated_setlist" not in st.session_state:
    st.session_state.generated_setlist = []

def go_to(page):
    st.session_state.page = page
    st.rerun()

# ========= HOME PAGE ==========
if st.session_state.page == "home":
    st.set_page_config(page_title="DJ Setlist App", layout="centered")

    st.markdown(
        """
        <style>
        body {
            background-color: #0e0e0e;
        }
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
            border: 2px solid white;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown("<div class='title'>DJ Setlist Builder</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Visualizer"):
            go_to("visualizer")

    with col2:
        if st.button("Generate Setlist"):
            go_to("generate_setlist")

# ========= VISUALIZER PAGE ==========
elif st.session_state.page == "visualizer":
    st.set_page_config(page_title="DJ Visualizer", layout="wide")

    if st.button("Back to Home", use_container_width=True):
        go_to("home")

    st.title("DJ Setlist Visualizer")

    st.sidebar.title("Filters")
    main_genres = list(set(map_genre(song.genre) for song in songs))
    selected_genres = st.sidebar.multiselect("Select Genres:", options=main_genres, default=main_genres)
    min_energy = st.sidebar.slider("Minimum Energy", 1, 10, 1)
    min_danceability = st.sidebar.slider("Minimum Danceability", 1, 10, 1)
    bpm_range = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    max_songs = st.sidebar.number_input("Max number of songs to display:", min_value=5, max_value=100, value=10)

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

    pos = {node: (random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)) for node in G.nodes}

    edge_x, edge_y, edge_z = [], [], []
    for edge in G.edges(data=True):
        x0, y0, z0 = pos[edge[0]]
        x1, y1, z1 = pos[edge[1]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
        edge_z += [z0, z1, None]

    edge_trace = go.Scatter3d(
        x=edge_x, y=edge_y, z=edge_z,
        line=dict(width=2, color='#00FFFF'),
        hoverinfo='none',
        mode='lines'
    )

    node_x, node_y, node_z, node_text, node_color = [], [], [], [], []
    for node, data in G.nodes(data=True):
        x, y, z = pos[node]
        genre = map_genre(data.get('genre', 'Other'))
        node_x.append(x)
        node_y.append(y)
        node_z.append(z)
        node_color.append(GENRE_COLOR_MAP.get(genre, 'gray'))
        node_text.append(f"{data['name']}<br>{data['artist']}<br>{data['bpm']} BPM<br>{data['key']}")

    node_trace = go.Scatter3d(
        x=node_x, y=node_y, z=node_z,
        mode='markers+text',
        textposition="bottom center",
        marker=dict(size=10, color=node_color, line=dict(width=0)),
        text=node_text,
        hoverinfo='text'
    )

    fig = go.Figure(data=[edge_trace, node_trace],
        layout=go.Layout(
            title='',
            showlegend=False,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor='#0e0e0e',
            plot_bgcolor='#0e0e0e',
            scene=dict(
                xaxis=dict(showbackground=False),
                yaxis=dict(showbackground=False),
                zaxis=dict(showbackground=False)
            )
        )
    )

    st.plotly_chart(fig, use_container_width=True)

# ========= GENERATE SETLIST PAGE ==========
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

    if st.session_state.generated_setlist and st.button("Visualize This Setlist", use_container_width=True):
        G = nx.DiGraph()
        for idx, song in enumerate(st.session_state.generated_setlist):
            G.add_node(idx, name=song.name, artist=song.artist, bpm=song.bpm, key=song.key)

        for idx in range(len(st.session_state.generated_setlist) - 1):
            a = st.session_state.generated_setlist[idx]
            b = st.session_state.generated_setlist[idx + 1]
            G.add_edge(idx, idx + 1, bpm_diff=round(b.bpm - a.bpm, 1), key_change=f"{a.key} ➔ {b.key}")

        pos = {node: (idx, 0, 0) for idx, node in enumerate(G.nodes)}

        edge_x, edge_y, edge_z = [], [], []
        edge_text = []
        for edge in G.edges(data=True):
            x0, y0, z0 = pos[edge[0]]
            x1, y1, z1 = pos[edge[1]]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]
            edge_z += [z0, z1, None]
            bpm_diff = edge[2]['bpm_diff']
            key_change = edge[2]['key_change']
            edge_text.append(f"{bpm_diff:+} BPM | {key_change}")

        edge_trace = go.Scatter3d(
            x=edge_x, y=edge_y, z=edge_z,
            line=dict(width=4, color='#00FFFF'),
            hoverinfo='text',
            text=edge_text,
            mode='lines'
        )

        node_x, node_y, node_z, node_text = [], [], [], []
        for node, data in G.nodes(data=True):
            x, y, z = pos[node]
            node_x.append(x)
            node_y.append(y)
            node_z.append(z)
            node_text.append(f"{data['name']}<br>{data['artist']}<br>{data['bpm']} BPM<br>{data['key']}")

        node_trace = go.Scatter3d(
            x=node_x, y=node_y, z=node_z,
            mode='markers+text',
            textposition="bottom center",
            marker=dict(size=12, color='white', line=dict(width=0)),
            text=node_text,
            hoverinfo='text'
        )

        fig = go.Figure(data=[edge_trace, node_trace],
            layout=go.Layout(
                showlegend=False,
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor='#0e0e0e',
                plot_bgcolor='#0e0e0e',
                scene=dict(
                    xaxis=dict(showbackground=False),
                    yaxis=dict(showbackground=False),
                    zaxis=dict(showbackground=False)
                )
            )
        )

        st.plotly_chart(fig, use_container_width=True)
