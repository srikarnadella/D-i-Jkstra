import math
import zlib
import networkx as nx
import pandas as pd
import plotly.graph_objects as go

from models import map_genre, Song, key_compat_label, fmt_duration, parse_key, track_energy


# ── Layout helpers ────────────────────────────────────────────────────────────

def _stable_seed(G: nx.DiGraph) -> int:
    """Seed from the node set; crc32 (unlike hash()) is identical across processes."""
    return zlib.crc32("|".join(sorted(map(str, G.nodes()))).encode())


def stable_3d_positions(G: nx.DiGraph) -> dict:
    """Force-directed 3D layout, deterministic for a given node set."""
    return nx.spring_layout(G, dim=3, k=0.5, iterations=50, seed=_stable_seed(G))


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
    return nx.spring_layout(G, k=0.5, iterations=50, seed=_stable_seed(G))


# ── Palette (true-black flat; booth amber is the one data hue) ─────────────────

ACCENT = "#f2b33d"
NEGATIVE = "#e5484d"
INK, MUTED, FAINT = "#ffffff", "#cfcfcf", "#adadad"
GRID = "#2b2b2b"
NEUTRALS = ["#e6e6e6", "#6b6b6b", "#3a3a3a"]
_FONT = dict(family="Inter, system-ui, sans-serif", size=14, color=FAINT)
_AXIS = dict(showgrid=True, gridcolor=GRID, gridwidth=1, zeroline=False, showline=False,
             tickfont=dict(size=14, color=FAINT), title=None, automargin=True)
_HIDDEN = dict(visible=False, showgrid=False, zeroline=False)


def _style(fig: go.Figure, height: int | None = None, legend: bool = False) -> go.Figure:
    """Shared chart chrome: transparent on the card, Inter 12px grey, faint grid, no axis lines."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=_FONT,
        margin=dict(l=8, r=8, t=8 if not legend else 36, b=8), showlegend=legend,
        hoverlabel=dict(bgcolor="#2a2a2a", bordercolor="#2a2a2a", font=dict(color=INK, size=14)),
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", font=dict(size=14, color=MUTED),
                    bgcolor="rgba(0,0,0,0)"),
        **({"height": height} if height else {}),
    )
    return fig


# ── Edge color ────────────────────────────────────────────────────────────────

def bpm_edge_color(bpm_diff: float) -> str:
    """Brighter = smoother: ≤2 BPM near-white, ≤5 mid grey, more than that dark grey."""
    if bpm_diff <= 2:
        return NEUTRALS[0]
    if bpm_diff <= 5:
        return NEUTRALS[1]
    return NEUTRALS[2]


# ── Figure builders ───────────────────────────────────────────────────────────

_ENERGY_SCALE = [[0.0, "#3a2c10"], [1.0, ACCENT]]   # one hue, darker = calmer


def _node_energy(data: dict) -> float:
    return track_energy(data.get("bpm"), data.get("energy"))


def _node_label(data: dict) -> str:
    return (f"<b>{data['name']}</b><br>{data['artist']}<br>{data['bpm']} BPM · {data['key']} · "
            f"energy {_node_energy(data):.1f}")


def _edge_hover(edge_data: dict) -> str:
    diff = edge_data.get("bpm_diff", 0)
    change = edge_data.get("key_change", "")
    mix = edge_data.get("mix_delta")
    octave = f" (half/double-time Δ {mix:.1f})" if mix is not None and mix < abs(diff) else ""
    return f"{diff:+.1f} BPM{octave} · {change}"


def _edge_groups(G: nx.DiGraph, pos: dict, edge_color_fn, dims: int):
    """One trace per edge colour (not per edge): far fewer traces, same picture."""
    groups: dict[str, dict] = {}
    for a, b, data in G.edges(data=True):
        diff = data.get("mix_delta", abs(data.get("bpm_diff", 0)))
        color = edge_color_fn(diff) if edge_color_fn else NEUTRALS[1]
        g = groups.setdefault(color, {"x": [], "y": [], "z": [], "text": []})
        for axis, i in (("x", 0), ("y", 1), ("z", 2))[:dims]:
            g[axis] += [pos[a][i], pos[b][i], None]
        g["text"] += [_edge_hover(data)] * 3
    return groups


def build_3d_figure(G: nx.DiGraph, pos: dict, edge_color_fn=None, paper_bg: str | None = None) -> go.Figure:
    traces = [
        go.Scatter3d(x=g["x"], y=g["y"], z=g["z"], mode="lines", line=dict(width=3, color=c),
                     hoverinfo="text", text=g["text"])
        for c, g in _edge_groups(G, pos, edge_color_fn, 3).items()
    ]
    nodes = list(G.nodes(data=True))
    traces.append(go.Scatter3d(
        x=[pos[n][0] for n, _ in nodes], y=[pos[n][1] for n, _ in nodes], z=[pos[n][2] for n, _ in nodes],
        mode="markers", hoverinfo="text", text=[_node_label(d) for _, d in nodes],
        marker=dict(size=7, color=[_node_energy(d) for _, d in nodes], colorscale=_ENERGY_SCALE,
                    cmin=1, cmax=10, line=dict(width=0)),
    ))
    fig = go.Figure(traces)
    fig.update_layout(scene=dict(xaxis=_HIDDEN, yaxis=_HIDDEN, zaxis=_HIDDEN, bgcolor="rgba(0,0,0,0)"))
    return _style(fig, height=560)


def build_2d_figure(G: nx.DiGraph, pos: dict, edge_color_fn=None, paper_bg: str | None = None) -> go.Figure:
    traces = [
        go.Scatter(x=g["x"], y=g["y"], mode="lines", line=dict(width=1.5, color=c),
                   hoverinfo="text", text=g["text"])
        for c, g in _edge_groups(G, pos, edge_color_fn, 2).items()
    ]
    nodes = list(G.nodes(data=True))
    traces.append(go.Scatter(
        x=[pos[n][0] for n, _ in nodes], y=[pos[n][1] for n, _ in nodes], mode="markers",
        hoverinfo="text", text=[_node_label(d) for _, d in nodes],
        marker=dict(size=10, color=[_node_energy(d) for _, d in nodes], colorscale=_ENERGY_SCALE,
                    cmin=1, cmax=10, line=dict(width=0)),
    ))
    fig = go.Figure(traces)
    fig.update_layout(xaxis=_HIDDEN, yaxis=_HIDDEN)
    return _style(fig, height=560)


_CLUSTER_TONES = [ACCENT, NEUTRALS[0], NEUTRALS[1]]
_CLUSTER_SYMBOLS = ["circle", "square", "diamond", "triangle-up"]


def cluster_figure(df: pd.DataFrame, cluster_labels: dict | None = None) -> go.Figure:
    """Clusters as tone × shape (three tones, four shapes) — never a rainbow."""
    fig = go.Figure()
    for i, cid in enumerate(sorted(df["cluster"].unique())):
        sub = df[df["cluster"] == cid]
        fig.add_trace(go.Scatter(
            x=sub["pc1"], y=sub["pc2"], mode="markers",
            name=(cluster_labels or {}).get(int(cid), f"Cluster {cid}"),
            marker=dict(color=_CLUSTER_TONES[i % 3], symbol=_CLUSTER_SYMBOLS[(i // 3) % 4], size=9,
                        line=dict(width=0)),
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
                          "%{customdata[2]} BPM · %{customdata[3]}<extra></extra>",
            customdata=sub[["name", "artist", "bpm", "key"]].values,
        ))
    fig.update_layout(xaxis=dict(_AXIS, showticklabels=False), yaxis=dict(_AXIS, showticklabels=False))
    return _style(fig, height=440, legend=True)


def energy_timeline_figure(
    setlist: list[Song],
    x_labels: list[str] | None = None,
    energy: list[float] | None = None,
    energy_target: list[float] | None = None,
) -> go.Figure:
    """The set's shape: BPM (white) on the left axis, energy (amber, the one data hue) and the
    vibe's target curve (dotted grey) on a 0–10 right axis. Red marks only the key clashes."""
    x = x_labels if x_labels else list(range(1, len(setlist) + 1))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=[s.bpm for s in setlist], mode="lines", name="BPM",
        line=dict(color=NEUTRALS[0], width=2), text=[s.name for s in setlist],
        hovertemplate="<b>%{text}</b><br>%{y:.1f} BPM<extra></extra>",
    ))
    clashes = [i for i in range(1, len(setlist))
               if key_compat_label(setlist[i - 1].key, setlist[i].key) == "Non-harmonic"]
    if clashes:
        fig.add_trace(go.Scatter(
            x=[x[i] for i in clashes], y=[setlist[i].bpm for i in clashes], mode="markers",
            name="Key clash", marker=dict(color=NEGATIVE, size=8, line=dict(width=0)),
            text=[f"{setlist[i - 1].key} → {setlist[i].key}" for i in clashes],
            hovertemplate="Key clash %{text}<extra></extra>",
        ))
    if energy_target:
        fig.add_trace(go.Scatter(x=x, y=energy_target, yaxis="y2", mode="lines", name="Vibe curve",
                                 line=dict(color=NEUTRALS[1], width=1.5, dash="dot"),
                                 hovertemplate="Target energy %{y:.1f}<extra></extra>"))
    if energy:
        fig.add_trace(go.Scatter(x=x, y=energy, yaxis="y2", mode="lines", name="Energy",
                                 line=dict(color=ACCENT, width=2),
                                 hovertemplate="Energy %{y:.1f}<extra></extra>"))
    fig.update_layout(
        xaxis=dict(_AXIS, showgrid=False, nticks=8),
        yaxis=dict(_AXIS, nticks=5, ticksuffix=" BPM"),
        yaxis2=dict(_AXIS, overlaying="y", side="right", range=[0, 10.5], tickvals=[0, 5, 10],
                    showgrid=False, ticksuffix=" E"),
    )
    return _style(fig, height=280, legend=True)


# ── Camelot wheel ─────────────────────────────────────────────────────────────

def camelot_wheel_figure(songs: list) -> go.Figure:
    """The library on a real Camelot wheel: 12 at the top, minor keys (A) on the inner ring,
    major keys (B) on the outer. Each slot's amber bar grows with its track count, so thin
    keys show as short bars against their dark track."""
    counts: dict[str, int] = {}
    for s in songs:
        num, mode = parse_key(s.key)
        if num is not None and 1 <= num <= 12:
            counts[f"{num}{mode}"] = counts.get(f"{num}{mode}", 0) + 1
    peak = max(counts.values(), default=1)
    angles = [(n % 12) * 30 for n in range(1, 13)]
    fig = go.Figure()
    for mode, base, name in (("A", 1.0, "minor"), ("B", 4.6, "major")):
        n_list = list(range(1, 13))
        vals = [counts.get(f"{n}{mode}", 0) for n in n_list]
        fig.add_trace(go.Barpolar(r=[3.0] * 12, base=base, theta=angles, width=26,
                                  marker=dict(color="#1c1c1c", line=dict(width=0)), hoverinfo="skip"))
        fig.add_trace(go.Barpolar(
            r=[max(0.08, 3.0 * v / peak) for v in vals], base=base, theta=angles, width=26,
            marker=dict(color=ACCENT, line=dict(width=0)),
            customdata=[[f"{n}{mode}", v] for n, v in zip(n_list, vals)],
            hovertemplate="%{customdata[0]} (" + name + ") · %{customdata[1]} tracks<extra></extra>",
        ))
    # The wheel's numbers once, outside it, like a clock face; A/B are the rings (see the subtitle).
    fig.add_trace(go.Scatterpolar(
        r=[8.35] * 12, theta=angles, mode="text", text=[str(n) for n in range(1, 13)],
        textfont=dict(size=14, color=FAINT), hoverinfo="skip",
    ))
    fig.update_layout(polar=dict(
        bgcolor="rgba(0,0,0,0)", hole=0.0,
        radialaxis=dict(visible=False, range=[0, 8.9]),
        angularaxis=dict(visible=False, rotation=90, direction="clockwise"),
    ))
    return _style(fig, height=340)


# ── Export ────────────────────────────────────────────────────────────────────

def setlist_to_csv_bytes(setlist: list[Song]) -> bytes:
    rows = [
        {
            "#": i + 1, "Title": s.name, "Artist": s.artist,
            "BPM": s.bpm, "Key": s.key, "Genre": map_genre(s.genre),
            "Length": fmt_duration(s.duration),
        }
        for i, s in enumerate(setlist)
    ]
    return pd.DataFrame(rows).to_csv(index=False).encode()
