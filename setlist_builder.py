# setlist_builder.py

import streamlit as st

# ─── Page Config must be first ─────────────────────────────────────────────────
st.set_page_config(page_title="DJ Setlist Builder", layout="wide")
st.markdown("<style>body{background-color:#0e0e0e;color:white;}</style>", unsafe_allow_html=True)

# ─── Imports ─────────────────────────────────────────────────────────────────────
import networkx as nx
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import random
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

from dj_graph import DJSetlistGraph
from load_songs import load_songs_from_excel

# ─── Load & Cache Songs ─────────────────────────────────────────────────────────
@st.cache_data
def load_songs_cached(path: str):
    return load_songs_from_excel(path)

songs = load_songs_cached("music_with_engineered.xlsx")

# ─── Genre Mapping & Color Map ──────────────────────────────────────────────────
def map_genre(raw_genre):
    g = str(raw_genre or "").lower()
    if any(k in g for k in ["house", "deep tech", "techno"]): return "Dance/House"
    if any(k in g for k in ["garage", "bassline", "grime"]):   return "Dance/EDM"
    if any(k in g for k in ["electronic", "organic"]):        return "Electronic"
    if "hip-hop" in g or "rap" in g or "travis scott" in g:    return "Hip-Hop/Rap"
    if "r&b" in g:                                            return "R&B"
    if "pop" in g:                                            return "Pop"
    if "dance" in g:                                          return "Dance/EDM"
    return "Other"

GENRE_COLOR_MAP = {
    "Dance/House": "deepskyblue",
    "Dance/EDM":   "lime",
    "Electronic":  "purple",
    "Hip-Hop/Rap": "red",
    "R&B":         "pink",
    "Pop":         "orange",
    "Other":       "gray"
}

# ─── Session State Init ─────────────────────────────────────────────────────────
if "page" not in st.session_state:
    st.session_state.page = "Home"
if "generated_setlist" not in st.session_state:
    st.session_state.generated_setlist = []

def go_to(page_name: str):
    st.session_state.page = page_name
    st.rerun()

# ─── Helpers ────────────────────────────────────────────────────────────────────
# ─── Helper: Filter Songs with Ranges ─────────────────────────────────────────
def filter_songs(
    songs, 
    genres, 
    energy_range, 
    dance_range, 
    bpm_range, 
    limit
):
    e_min, e_max     = energy_range
    d_min, d_max     = dance_range
    bpm_min, bpm_max = bpm_range
    filtered = [
        s for s in songs
        if map_genre(s.genre) in genres
        and e_min <= s.energy <= e_max
        and d_min <= s.danceability <= d_max
        and bpm_min <= s.bpm <= bpm_max
    ]
    return filtered[:limit]


@st.cache_data
def build_nx_graph(_songs_list):
    g = DJSetlistGraph()
    g.build_graph(_songs_list)
    return g.graph

@st.cache_data
def spring_layout_pos(_G):
    # underscore in parameter name prevents hashing errors
    return nx.spring_layout(_G, k=0.5, iterations=50)

def key_compatibility(k1, k2):
    if not k1 or not k2: return 5
    if k1 == k2:        return 0
    if k1.split()[0] == k2.split()[0]: return 1
    if k1[-1] == k2[-1]: return 2
    return 4

def smoothest_setlist(slist):
    G = nx.DiGraph()
    for i, a in enumerate(slist):
        for j, b in enumerate(slist):
            if i == j: continue
            w = abs(a.bpm - b.bpm) + key_compatibility(a.key, b.key) * 2
            G.add_edge(i, j, weight=w)
    path = [0]; visited = {0}
    while len(visited) < len(slist):
        cur = path[-1]
        nbr = min(
            (n for n in G.neighbors(cur) if n not in visited),
            key=lambda n: G[cur][n]['weight'],
            default=None
        )
        if nbr is None: break
        path.append(nbr); visited.add(nbr)
    return [slist[i] for i in path]

def plot_2d(G, pos):
    ex, ey = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]; x1, y1 = pos[v]
        ex += [x0, x1, None]; ey += [y0, y1, None]
    edge_trace = go.Scatter(
        x=ex, y=ey, mode="lines",
        line=dict(color="#00FFFF", width=1),
        hoverinfo="none"
    )
    nx_, ny_, txt_, col_, sz_ = [], [], [], [], []
    for n, d in G.nodes(data=True):
        x, y = pos[n]
        nx_.append(x); ny_.append(y)
        col_.append(GENRE_COLOR_MAP[map_genre(d.get('genre',''))])
        txt_.append(f"{d['name']}<br>{d['artist']}<br>{d['bpm']} BPM<br>{d['key']}")
        sz_.append(8 + d.get('energy',5)*2)
    node_trace = go.Scatter(
        x=nx_, y=ny_, mode="markers+text",
        marker=dict(size=sz_, color=col_, line=dict(width=0)),
        text=txt_, textposition="bottom center",
        textfont=dict(size=14, color="white"),
        hoverinfo="text"
    )
    fig = go.Figure([edge_trace, node_trace], layout=go.Layout(
        paper_bgcolor="#0e0e0e", plot_bgcolor="#0e0e0e",
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        margin=dict(l=0, r=0, t=0, b=0)
    ))
    return fig

def plot_3d(G):
    pos3 = {n: (random.uniform(-1,1), random.uniform(-1,1), random.uniform(-1,1)) for n in G.nodes}
    ex, ey, ez = [], [], []
    for u, v in G.edges():
        x0, y0, z0 = pos3[u]; x1, y1, z1 = pos3[v]
        ex += [x0, x1, None]; ey += [y0, y1, None]; ez += [z0, z1, None]
    edge_trace = go.Scatter3d(
        x=ex, y=ey, z=ez, mode="lines",
        line=dict(color="#00FFFF", width=2),
        hoverinfo="none"
    )
    nx_, ny_, nz_, txt_, col_, sz_ = [], [], [], [], [], []
    for n, d in G.nodes(data=True):
        x, y, z = pos3[n]
        nx_.append(x); ny_.append(y); nz_.append(z)
        col_.append(GENRE_COLOR_MAP[map_genre(d.get('genre',''))])
        txt_.append(f"{d['name']}<br>{d['artist']}<br>{d['bpm']} BPM<br>{d['key']}")
        sz_.append(6 + d.get('energy',5)*1.5)
    node_trace = go.Scatter3d(
        x=nx_, y=ny_, z=nz_, mode="markers+text",
        marker=dict(size=sz_, color=col_, line=dict(width=0)),
        text=txt_, textposition="bottom center",
        textfont=dict(size=14, color="white"),
        hoverinfo="text"
    )
    fig = go.Figure([edge_trace, node_trace], layout=go.Layout(
        scene=dict(
            xaxis=dict(showbackground=False),
            yaxis=dict(showbackground=False),
            zaxis=dict(showbackground=False)
        ),
        paper_bgcolor="#0e0e0e", plot_bgcolor="#0e0e0e",
        margin=dict(l=0, r=0, t=0, b=0)
    ))
    return fig

# ─── Main Navigation & Pages ───────────────────────────────────────────────────
page = st.sidebar.radio("Navigate", ["Home", "Visualizer", "Generate Setlist", "Cluster Songs"])

if page == "Home":
    st.markdown("<h1 style='text-align:center;color:white;'>DJ Setlist Builder</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("Visualizer"):       go_to("Visualizer")
    if c2.button("Generate Setlist"): go_to("Generate Setlist")
    if c3.button("Cluster Songs"):    go_to("Cluster Songs")

elif page == "Visualizer":
    st.header("Visualizer")
    if st.button("← Back"):
        go_to("Home")

    mode = st.radio("View Mode", ["2D", "3D"], horizontal=True)

    # Sidebar filters
    genres       = st.sidebar.multiselect("Genres", list(GENRE_COLOR_MAP), default=list(GENRE_COLOR_MAP))
    energy_range = st.sidebar.slider("Energy Range", 1, 10, (1, 10))
    dance_range  = st.sidebar.slider("Danceability Range", 1, 10, (1, 10))
    bpm_range    = st.sidebar.slider("BPM Range", 60, 200, (60, 200))
    max_songs    = st.sidebar.number_input("Max Songs to Display", 5, 100, 30)

    # Apply filters
    filtered = filter_songs(songs, genres, energy_range, dance_range, bpm_range, max_songs)
    st.write(f"Showing {len(filtered)} songs after filtering.")

    # Build + cache the graph
    G2 = build_nx_graph(filtered)

    # Plot
    if mode == "2D":
        pos = spring_layout_pos(G2)
        fig = plot_2d(G2, pos)
    else:
        fig = plot_3d(G2)

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


elif page == "Generate Setlist":
    st.header("Generate Setlist")
    if st.button("← Back"): go_to("Home")
    genres        = st.multiselect("Genres", list(GENRE_COLOR_MAP), default=list(GENRE_COLOR_MAP))
    bpm_min,bpm_max = st.slider("BPM Range", 60, 200, (120,135))
    e_min         = st.slider("Min Energy", 1, 10, 5)
    cnt           = st.number_input("Length", 5, 50, 15)

    if st.button("Generate Base"):
        base = sorted(filter_songs(songs, genres, e_min, e_min, bpm_min, bpm_max, cnt), key=lambda s:s.bpm)
        st.session_state.generated_setlist = base
        st.markdown("### Base Setlist")
        for i, sng in enumerate(base, 1):
            st.write(f"{i}. {sng.name} — {sng.bpm} BPM — {sng.key}")

    if st.session_state.generated_setlist and st.button("Smoothest (Dijkstra)"):
        sm = smoothest_setlist(st.session_state.generated_setlist)
        st.markdown("### Smoothest Setlist")
        for i, sng in enumerate(sm, 1):
            st.write(f"{i}. {sng.name} — {sng.bpm} BPM — {sng.key}")

elif page == "Cluster Songs":
    st.header("Cluster Songs")
    if st.button("← Back"): go_to("Home")

    # ─── NEW FILTERS ─────────────────────────────────────────────────────────────
    genres        = st.multiselect("Filter Genres", list(GENRE_COLOR_MAP), default=list(GENRE_COLOR_MAP))
    e_min, _      = st.slider("Min Energy", 1, 10, (1,10))
    d_min, _      = st.slider("Min Danceability", 1, 10, (1,10))
    bpm_min,bpm_max = st.slider("BPM Range", 60, 200, (60,200))
    max_cluster   = st.number_input("Max Songs to Cluster", 5, len(songs), len(songs))

    sl = filter_songs(songs, genres, e_min, d_min, bpm_min, bpm_max, max_cluster)

    k = st.slider("Number of Clusters", 2, 10, 4)
    df = pd.DataFrame([{
        "bpm": s.bpm,
        "energy": s.energy,
        "danceability": s.danceability,
        "name": s.name
    } for s in sl])

    # scale → PCA for clearer separation
    Xs = StandardScaler().fit_transform(df[["bpm","energy","danceability"]])
    pcs = PCA(n_components=2).fit_transform(Xs)
    df["pc1"], df["pc2"] = pcs[:,0], pcs[:,1]
    df["cluster"] = KMeans(n_clusters=k, random_state=42).fit_predict(Xs)

    colors = px.colors.qualitative.Bold
    fig = go.Figure()
    for cid in sorted(df.cluster.unique()):
        sub = df[df.cluster==cid]
        fig.add_trace(go.Scatter(
            x=sub.pc1, y=sub.pc2, mode="markers+text",
            marker=dict(color=colors[cid % len(colors)], size=12),
            text=sub.name, textposition="bottom center",
            name=f"Cluster {cid}"
        ))
    fig.update_layout(
        xaxis_title="PC1", yaxis_title="PC2",
        paper_bgcolor="#0e0e0e", plot_bgcolor="#0e0e0e",
        font_color="white", margin=dict(l=20, r=20, t=20, b=20)
    )
    st.plotly_chart(fig, use_container_width=True)
