import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import networkx as nx
import random
import sqlite3
from collections import namedtuple

from dj_graph import DJSetlistGraph

import re
import random
from datetime import datetime, timedelta

def score_track(row, vibe):
    bpm = row['bpm']
    genre = str(row['genre']).strip().lower()
    score = 0

    exclusions = {
        "frat party": ["rock", "afro house"],
        "sunset": ["pop", "rap", "hip hop", "electronica", "pitbull", "jersey club", "tiesto"],
        "kick back": ["rock", "rap", "hip hop"],
        "rave": ["r&b", "indie pop", "latin pop", "pop", "demi lovato"],
        "house": ["rap", "hip hop", "rock", "pitbull"],
        "poolside": ["rock", "trap", "metal", "jersey club"]
    }

    excluded = exclusions.get(vibe.lower(), [])
    if any(g.lower() in genre for g in excluded):
        return 0

    if vibe.lower() == "frat party":
        if "pop" in genre:
            score += 3
        if 120 <= bpm <= 135:
            score += 2
    elif vibe.lower() == "sunset":
        if 95 <= bpm <= 118:
            score += 2
    elif vibe.lower() == "kick back":
        if 120 <= bpm <= 135:
            score += 2
    elif vibe.lower() == "rave":
        if 125 <= bpm <= 140:
            score += 2
        if "techno" in genre:
            score += 2
    elif vibe.lower() == "house":
        if "house" in genre:
            score += 2
    elif vibe.lower() == "poolside":
        if "chill" in genre or "tropical" in genre:
            score += 2

    score += random.uniform(0, 0.3)
    return score

def parse_key(k):
    match = re.match(r"^(\d{1,2})([AB])$", str(k).strip().upper())
    return (int(match.group(1)), match.group(2)) if match else (None, None)

def get_harmonic_neighbors(key):
    num, mode = parse_key(key)
    if num is None:
        return []
    neighbors = [f"{num}{mode}", f"{num}{'B' if mode == 'A' else 'A'}", f"{(num % 12) + 1}{mode}", f"{(num - 2) % 12 + 1}{mode}"]
    return neighbors

def estimate_track_duration(row, ratio=0.7):
    return 210

def build_segment_graph(tracks, total_duration_seconds, transitions=None):
    durations = [estimate_track_duration(t) for t in tracks]
    n = len(tracks)
    graph = [[] for _ in range(n)]

    for i in range(n):
        key1 = tracks[i]['key'].strip().upper()
        bpm1 = tracks[i]['bpm']
        for j in range(n):
            if i == j:
                continue
            key2 = tracks[j]['key'].strip().upper()
            bpm2 = tracks[j]['bpm']
            if key2 in get_harmonic_neighbors(key1) and abs(bpm1 - bpm2) <= 25:
                graph[i].append(j)

    dp = [(durations[i], [i]) for i in range(n)]
    for i in range(n):
        for j in graph[i]:
            new_time = dp[i][0] + durations[j]
            if new_time <= total_duration_seconds and new_time > dp[j][0]:
                dp[j] = (new_time, dp[i][1] + [j])

    best_path_indices = max(dp, key=lambda x: (x[0] <= total_duration_seconds, x[0], random.random()))[1]
    return [tracks[i] for i in best_path_indices]

def build_harmonic_graph_setlist(scored_tracks, total_duration_seconds, use_auto_segmentation=True, transitions=None):
    df = [t for t in scored_tracks if t['vibe_score'] > 0 and t['key']]
    if not df:
        return []

    build_time = total_duration_seconds if not use_auto_segmentation else 1800
    remaining_time = total_duration_seconds - build_time
    segments = [(df, build_time)] if not use_auto_segmentation else [
        ([t for t in df if parse_key(t['key'])[0] in range(1, 5)], build_time),
        ([t for t in df if parse_key(t['key'])[0] in range(5, 9)], remaining_time * 0.6),
        ([t for t in df if parse_key(t['key'])[0] in range(9, 13)], remaining_time * 0.4),
    ]

    result = []
    for segment_tracks, segment_time in segments:
        if not segment_tracks:
            continue
        segment_result = build_segment_graph(segment_tracks, segment_time, transitions)
        result.extend(segment_result)

    return result


# Load Songs from SQLite database
def load_songs_from_db(db_path="dj_tracks.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT track_title, artist, genre, bpm, key FROM tracks")
    rows = cursor.fetchall()
    conn.close()
    Song = namedtuple("Song", ["name", "artist", "genre", "bpm", "key"])
    return [Song(*row) for row in rows]

songs = load_songs_from_db()

# Adapt uploaded CSV to expected format
def adapt_uploaded_csv(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "track_title": "name",
        "Title": "name",
        "Artist": "artist",
        "Genre": "genre",
        "BPM": "bpm",
        "Key": "key"
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    required_cols = ["name", "artist", "genre", "bpm", "key"]
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns after adaptation: {', '.join(missing)}")
    return df[required_cols]

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

if "page" not in st.session_state:
    st.session_state.page = "home"
if "generated_setlist" not in st.session_state:
    st.session_state.generated_setlist = []

def go_to(page):
    st.session_state.page = page
    st.rerun()

# ---------------- Home Page ----------------
if st.session_state.page == "home":
    st.set_page_config(page_title="DJ Setlist App", layout="centered")
    st.markdown("""
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
            border: 2px solid white;
        }
        </style>
    """, unsafe_allow_html=True)
    st.markdown("<div class='title'>DJ Setlist Builder</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Visualizer"):
            go_to("visualizer")
    with col2:
        if st.button("Generate Setlist"):
            go_to("generate_setlist")

# ---------------- Visualizer Page ----------------
elif st.session_state.page == "visualizer":
    st.set_page_config(page_title="DJ Visualizer", layout="wide")
    if st.button("Back to Home", use_container_width=True):
        go_to("home")

    st.title("DJ Setlist Visualizer")
    st.sidebar.title("Filters")

    main_genres = list(set(map_genre(song.genre) for song in songs))
    selected_genres = st.sidebar.multiselect("Select Genres:", options=main_genres, default=main_genres)
    bpm_range = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    max_songs = st.sidebar.number_input("Max number of songs to display:", min_value=5, max_value=100, value=10)

    edge_color_mode = st.sidebar.radio("Transition Color Mode", ["BPM-Based Coloring", "Uniform Color (Cyan)"])

    uploaded_csv = st.sidebar.file_uploader("Upload CSV to visualize your own setlist", type=["csv"])
    if uploaded_csv:
        try:
            raw_df = pd.read_csv(uploaded_csv)
            df = adapt_uploaded_csv(raw_df)
            Song = namedtuple("Song", df.columns.tolist())
            filtered_songs = [Song(*row) for row in df.itertuples(index=False)]
            st.success(f"Using uploaded setlist with {len(filtered_songs)} songs.")
        except Exception as e:
            st.error(f"Error processing uploaded CSV: {e}")
            filtered_songs = []
    else:
        filtered_songs = [song for song in songs if map_genre(song.genre) in selected_genres and bpm_range[0] <= song.bpm <= bpm_range[1]]
        filtered_songs = filtered_songs[:max_songs]

    st.write(f"Showing {len(filtered_songs)} songs.")

    dj_graph = DJSetlistGraph()
    dj_graph.build_graph(filtered_songs)
    G = dj_graph.graph

    pos = {node: (random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)) for node in G.nodes}

    # --- Colored Edges ---
    edge_x, edge_y, edge_z = [], [], []
    edge_colors = []
    edge_text = []

    for edge in G.edges(data=True):
        x0, y0, z0 = pos[edge[0]]
        x1, y1, z1 = pos[edge[1]]
        bpm_diff = abs(edge[2].get("bpm_diff", 0))
        key_change = edge[2].get("key_change", "")

        # Color by BPM difference
        if edge_color_mode == "BPM-Based Coloring":
            if bpm_diff <= 2:
                color = "#00FF00"  # green
            elif bpm_diff <= 5:
                color = "#FFFF00"  # yellow
            else:
                color = "#FF0000"  # red
        else:
            color = "#00FFFF"  # cyan

        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
        edge_z += [z0, z1, None]
        edge_colors.append(color)
        edge_text.append(f"{edge[2]['bpm_diff']:+} BPM | {key_change}")

    edge_traces = []
    for i in range(0, len(edge_x), 3):
        trace = go.Scatter3d(
            x=edge_x[i:i+2],
            y=edge_y[i:i+2],
            z=edge_z[i:i+2],
            mode='lines',
            line=dict(width=3, color=edge_colors[i // 3]),
            hoverinfo='text',
            text=edge_text[i // 3]
        )
        edge_traces.append(trace)

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

    fig = go.Figure(data=edge_traces + [node_trace], layout=go.Layout(
        showlegend=False,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor='#0e0e0e',
        plot_bgcolor='#0e0e0e',
        scene=dict(
            xaxis=dict(showbackground=False),
            yaxis=dict(showbackground=False),
            zaxis=dict(showbackground=False)
        )
    ))

    st.plotly_chart(fig, use_container_width=True)

    # Legend
    if edge_color_mode == "BPM-Based Coloring":
        st.markdown("### Transition Color Legend")
        st.markdown("- 🟢 **Green**: Smooth transition (≤2 BPM)")
        st.markdown("- 🟡 **Yellow**: Moderate transition (≤5 BPM)")
        st.markdown("- 🔴 **Red**: Sharp transition (>5 BPM)")
# ---------------- Generate Setlist Page ----------------
elif st.session_state.page == "generate_setlist":
    st.set_page_config(page_title="DJ Setlist Generator", layout="centered")
    if st.button("Back to Home", use_container_width=True):
        go_to("home")

    st.title("Smart DJ Setlist Generator")

    start_time = st.time_input("Set Start Time", value=datetime.strptime("01:00", "%H:%M").time())
    end_time = st.time_input("Set End Time", value=datetime.strptime("03:00", "%H:%M").time())
    vibe = st.selectbox("Select Vibe", ["Sunset", "Kick back", "Rave", "House", "Poolside", "Frat Party"])
    auto_segment = st.checkbox("Auto Segment by Energy Curve", value=True)

    conn = sqlite3.connect("dj_tracks.db")
    df = pd.read_sql_query("SELECT * FROM tracks", conn)

    if st.button("Generate Setlist", use_container_width=True):
        start_dt = datetime.combine(datetime.today(), start_time)
        end_dt = datetime.combine(datetime.today(), end_time)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        total_duration = (end_dt - start_dt).total_seconds()
        df['vibe_score'] = df.apply(lambda row: score_track(row, vibe), axis=1)
        transitions = set()
        best_set = build_harmonic_graph_setlist(df.to_dict('records'), total_duration_seconds=total_duration, use_auto_segmentation=auto_segment, transitions=transitions)

        Song = namedtuple("Song", ["name", "artist", "genre", "bpm", "key"])
        st.session_state.generated_setlist = [Song(t['track_title'], t['artist'], t['genre'], t['bpm'], t['key']) for t in best_set]
        st.success(f"Generated {len(st.session_state.generated_setlist)} song setlist!")

    if st.session_state.generated_setlist and st.button("Visualize This Setlist", use_container_width=True):
        G = nx.DiGraph()
        for idx, song in enumerate(st.session_state.generated_setlist):
            G.add_node(idx, name=song.name, artist=song.artist, bpm=song.bpm, key=song.key)

        for idx in range(len(st.session_state.generated_setlist) - 1):
            a = st.session_state.generated_setlist[idx]
            b = st.session_state.generated_setlist[idx + 1]
            G.add_edge(idx, idx + 1, bpm_diff=round(b.bpm - a.bpm, 1), key_change=f"{a.key} → {b.key}")

        pos = {node: (idx, 0, 0) for idx, node in enumerate(G.nodes)}
        edge_x, edge_y, edge_z, edge_text = [], [], [], []
        for edge in G.edges(data=True):
            x0, y0, z0 = pos[edge[0]]
            x1, y1, z1 = pos[edge[1]]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]
            edge_z += [z0, z1, None]
            edge_text.append(f"{edge[2]['bpm_diff']:+} BPM | {edge[2]['key_change']}")

        edge_trace = go.Scatter3d(
            x=edge_x, y=edge_y, z=edge_z,
            line=dict(width=4, color='#00FFFF'),
            hoverinfo='text', text=edge_text,
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
            mode='markers+text', textposition="bottom center",
            marker=dict(size=12, color='white', line=dict(width=0)),
            text=node_text, hoverinfo='text'
        )

        fig = go.Figure(data=[edge_trace, node_trace], layout=go.Layout(
            showlegend=False,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor='#0e0e0e',
            plot_bgcolor='#0e0e0e',
            scene=dict(
                xaxis=dict(showbackground=False),
                yaxis=dict(showbackground=False),
                zaxis=dict(showbackground=False)
            )
        ))

        st.plotly_chart(fig, use_container_width=True)
