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

    if view_mode == "2D":
        pos = nx.spring_layout(G, k=0.5, iterations=50)

        edge_x = []
        edge_y = []
        for edge in G.edges(data=True):
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]

        edge_trace = go.Scatter(
            x=edge_x,
            y=edge_y,
            line=dict(width=1, color='#00FFFF'),
            hoverinfo='none',
            mode='lines'
        )

        node_x = []
        node_y = []
        node_text = []
        node_color = []

        for node, data in G.nodes(data=True):
            x, y = pos[node]
            genre = map_genre(data.get('genre', 'Other'))
            node_x.append(x)
            node_y.append(y)
            node_color.append(GENRE_COLOR_MAP.get(genre, 'gray'))
            node_text.append(f"{data['name']}<br>{data['artist']}<br>{data['bpm']} BPM<br>{data['key']}")

        node_trace = go.Scatter(
            x=node_x,
            y=node_y,
            mode='markers+text',
            textposition="bottom center",
            marker=dict(size=12, color=node_color, line=dict(width=0)),
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
                xaxis=dict(showgrid=False, zeroline=False, visible=False),
                yaxis=dict(showgrid=False, zeroline=False, visible=False)
            )
        )
        st.plotly_chart(fig, use_container_width=True)

    else:  # 3D Mode
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
