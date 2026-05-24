import math
import random
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from models import map_genre, GENRE_COLOR_MAP, Song, key_compat_label


# ── Layout helpers ────────────────────────────────────────────────────────────

def stable_3d_positions(G: nx.DiGraph) -> dict:
    """Deterministic random 3D positions seeded by node set — stable across rerenders."""
    seed = hash(frozenset(G.nodes())) & 0xFFFFFFFF
    rng = random.Random(seed)
    return {
        node: (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        for node in G.nodes
    }


def circular_layout_3d(node_list: list) -> dict:
    """Arrange nodes in a circle in the XY plane — readable for sequential setlists."""
    n = len(node_list)
    if n == 0:
        return {}
    return {
        node: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0)
        for i, node in enumerate(node_list)
    }


def spring_layout_2d(G: nx.DiGraph) -> dict:
    """Force-directed 2D layout with deterministic seed."""
    seed = hash(frozenset(G.nodes())) & 0xFFFFFFFF
    return nx.spring_layout(G, k=0.5, iterations=50, seed=seed)


# ── Edge color ────────────────────────────────────────────────────────────────

def bpm_edge_color(bpm_diff: float) -> str:
    if bpm_diff <= 2:
        return "#00FF00"
    if bpm_diff <= 5:
        return "#FFFF00"
    return "#FF0000"


# ── Figure builders ───────────────────────────────────────────────────────────

def _node_color(data: dict) -> str:
    return GENRE_COLOR_MAP.get(map_genre(data.get("genre", "")), "gray")


def _node_label(data: dict) -> str:
    return f"{data['name']}<br>{data['artist']}<br>{data['bpm']} BPM<br>{data['key']}"


def _edge_hover(edge_data: dict) -> str:
    diff = edge_data.get("bpm_diff", 0)
    change = edge_data.get("key_change", "")
    return f"{diff:+.1f} BPM | {change}"


def build_3d_figure(
    G: nx.DiGraph,
    pos: dict,
    edge_color_fn=None,
    paper_bg: str = "#0e0e0e",
) -> go.Figure:
    edge_traces = []
    for edge in G.edges(data=True):
        x0, y0, z0 = pos[edge[0]]
        x1, y1, z1 = pos[edge[1]]
        bpm_diff = abs(edge[2].get("bpm_diff", 0))
        color = edge_color_fn(bpm_diff) if edge_color_fn else "#00FFFF"
        edge_traces.append(go.Scatter3d(
            x=[x0, x1, None], y=[y0, y1, None], z=[z0, z1, None],
            mode="lines", line=dict(width=3, color=color),
            hoverinfo="text", text=_edge_hover(edge[2]),
        ))

    nx_, ny_, nz_, ntxt, ncol = [], [], [], [], []
    for node, data in G.nodes(data=True):
        x, y, z = pos[node]
        nx_.append(x); ny_.append(y); nz_.append(z)
        ncol.append(_node_color(data))
        ntxt.append(_node_label(data))

    node_trace = go.Scatter3d(
        x=nx_, y=ny_, z=nz_, mode="markers",
        marker=dict(size=10, color=ncol, line=dict(width=0)),
        text=ntxt, hoverinfo="text",
    )
    return go.Figure(
        data=edge_traces + [node_trace],
        layout=go.Layout(
            showlegend=False, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor=paper_bg,
            scene=dict(
                xaxis=dict(showbackground=False),
                yaxis=dict(showbackground=False),
                zaxis=dict(showbackground=False),
            ),
        ),
    )


def build_2d_figure(
    G: nx.DiGraph,
    pos: dict,
    edge_color_fn=None,
    paper_bg: str = "#0e0e0e",
) -> go.Figure:
    edge_traces = []
    for edge in G.edges(data=True):
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        bpm_diff = abs(edge[2].get("bpm_diff", 0))
        color = edge_color_fn(bpm_diff) if edge_color_fn else "#00FFFF"
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines", line=dict(width=2, color=color),
            hoverinfo="text", text=_edge_hover(edge[2]),
        ))

    nx_, ny_, ntxt, ncol = [], [], [], []
    for node, data in G.nodes(data=True):
        x, y = pos[node]
        nx_.append(x); ny_.append(y)
        ncol.append(_node_color(data))
        ntxt.append(_node_label(data))

    node_trace = go.Scatter(
        x=nx_, y=ny_, mode="markers",
        marker=dict(size=10, color=ncol, line=dict(width=0)),
        text=ntxt, hoverinfo="text",
    )
    return go.Figure(
        data=edge_traces + [node_trace],
        layout=go.Layout(
            showlegend=False, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor=paper_bg, plot_bgcolor=paper_bg,
            xaxis=dict(showgrid=False, zeroline=False, visible=False),
            yaxis=dict(showgrid=False, zeroline=False, visible=False),
        ),
    )


def cluster_figure(df: pd.DataFrame) -> go.Figure:
    colors = px.colors.qualitative.Bold
    fig = go.Figure()
    for cid in sorted(df["cluster"].unique()):
        sub = df[df["cluster"] == cid]
        fig.add_trace(go.Scatter(
            x=sub["pc1"], y=sub["pc2"],
            mode="markers",
            marker=dict(color=colors[int(cid) % len(colors)], size=12),
            name=f"Cluster {cid}",
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "%{customdata[1]}<br>"
                "BPM: %{customdata[2]}<br>"
                "Key: %{customdata[3]}<extra></extra>"
            ),
            customdata=sub[["name", "artist", "bpm", "key"]].values,
        ))
    fig.update_layout(
        xaxis_title="PC1",
        yaxis_title="PC2",
        paper_bgcolor="#0e0e0e",
        plot_bgcolor="#0e0e0e",
        font_color="white",
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(font=dict(color="white")),
    )
    return fig


def energy_timeline_figure(setlist: list[Song]) -> go.Figure:
    """BPM line chart for a setlist with markers colored by key transition quality."""
    x = list(range(1, len(setlist) + 1))
    y = [s.bpm for s in setlist]
    colors = ["#888888"] + [
        {"Same": "#00FF00", "Harmonic": "#FFFF00"}.get(
            key_compat_label(setlist[i - 1].key, setlist[i].key), "#FF4444"
        )
        for i in range(1, len(setlist))
    ]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y,
        mode="lines+markers",
        marker=dict(color=colors, size=10, line=dict(width=1, color="#222")),
        line=dict(color="#555", width=2),
        hovertemplate="<b>%{text}</b><br>BPM: %{y}<extra></extra>",
        text=[s.name for s in setlist],
    ))
    fig.update_layout(
        paper_bgcolor="#0e0e0e", plot_bgcolor="#0e0e0e",
        font_color="white",
        xaxis_title="Track #", yaxis_title="BPM",
        margin=dict(l=20, r=20, t=10, b=20),
    )
    return fig


# ── Export ────────────────────────────────────────────────────────────────────

def setlist_to_csv_bytes(setlist: list[Song]) -> bytes:
    rows = [
        {
            "#": i + 1, "Title": s.name, "Artist": s.artist,
            "BPM": s.bpm, "Key": s.key, "Genre": map_genre(s.genre),
        }
        for i, s in enumerate(setlist)
    ]
    return pd.DataFrame(rows).to_csv(index=False).encode()
