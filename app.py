import streamlit as st
from pyvis.network import Network
import tempfile
import os
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

# Page State Management
if "page" not in st.session_state:
    st.session_state.page = "home"
    
def go_to(page):
    st.session_state.page = page
    st.rerun()


# ========= HOME PAGE =========
if st.session_state.page == "home":
    st.set_page_config(page_title="DJ Setlist App", layout="centered")
    
    # Custom CSS for modern styling
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
        .button-container {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 50px;
            margin-top: 50px;
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

# ========= VISUALIZER PAGE =========
elif st.session_state.page == "visualizer":
    st.set_page_config(page_title="DJ Visualizer", layout="wide")
    
    if st.button("Back to Home", use_container_width=True):
        go_to("home")

    st.title("DJ Setlist Visualizer")

    # Sidebar Filters
    st.sidebar.title("Filters")
    main_genres = list(set(map_genre(song.genre) for song in songs))
    selected_genres = st.sidebar.multiselect("Select Genres:", options=main_genres, default=main_genres)
    min_energy = st.sidebar.slider("Minimum Energy", 1, 10, 1)
    min_danceability = st.sidebar.slider("Minimum Danceability", 1, 10, 1)
    bpm_range = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    max_songs = st.sidebar.number_input("Max number of songs to display:", min_value=5, max_value=100, value=30)

    # Filter Songs
    filtered_songs = []
    for song in songs:
        main_genre = map_genre(song.genre)
        if main_genre in selected_genres:
            if song.energy >= min_energy and song.danceability >= min_danceability:
                if bpm_range[0] <= song.bpm <= bpm_range[1]:
                    filtered_songs.append(song)
    filtered_songs = filtered_songs[:max_songs]

    st.write(f"Showing {len(filtered_songs)} songs based on your filters.")

    # Build Graph
    dj_graph = DJSetlistGraph()
    dj_graph.build_graph(filtered_songs)
    G = dj_graph.graph

    # Build Network
    net = Network(height="100vh", width="100vw", bgcolor="#0e0e0e", font_color="white", directed=True)

    net.barnes_hut(
        gravity=-40000,
        central_gravity=0.001,
        spring_length=400,
        spring_strength=0.0008
    )

    for node, data in G.nodes(data=True):
        energy = data.get('energy', 5)
        raw_genre = map_genre(data.get('genre', ""))
        color = "white"

        net.add_node(
            node,
            label=data['name'],
            title=f"<b>{data['name']}</b><br>{data['artist']}<br>{data['bpm']} BPM<br>{data['key']} | {raw_genre}",
            color=color,
            size=18 + (energy * 3),
            font={"size": 50, "color": "white", "face": "arial"},
            shape="dot",
            shadow=True
        )

    for source, target, data in G.edges(data=True):
        weight = data.get('weight', 10)
        color = "#888888"
        if weight < 5:
            color = "blue"
        elif weight < 7:
            color = "lime"
        elif weight < 9:
            color = "orange"
        else:
            color = "lightgray"

        net.add_edge(
            source,
            target,
            value=max(1, 10 - weight),
            color=color,
            smooth={"type": "curvedCW", "roundness": 0.3}
        )

    temp_dir = tempfile.gettempdir()
    path = os.path.join(temp_dir, "graph.html")
    net.save_graph(path)
    st.components.v1.html(open(path, 'r', encoding='utf-8').read(), height=1000, scrolling=False)

# ========= GENERATE SETLIST PAGE =========
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
        # Filter songs
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

        # Sort filtered songs by BPM (ascending)
        filtered = sorted(filtered, key=lambda s: s.bpm)

        generated_setlist = filtered[:max_setlist_songs]

        st.success(f"Generated {len(generated_setlist)} song setlist!")

        for idx, song in enumerate(generated_setlist, start=1):
            st.markdown(f"**{idx}. {song.name}** by *{song.artist}* — {song.bpm} BPM — {song.key}")
