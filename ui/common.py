"""Helpers shared by the page modules."""
import streamlit as st
from datetime import datetime, timedelta
from models import Song
from setlist_engine import harmonic_graph
from viz import circular_layout_3d, build_3d_figure, bpm_edge_color
from dj_graph import DJSetlistGraph


PAGE_LABELS = {
    "home": "Overview", "live": "Live", "generate_setlist": "Build a set",
    "library": "Library", "visualizer": "Key graph", "cluster": "Clusters",
}


def go_to(page: str) -> None:
    st.session_state.page = page
    st.query_params["page"] = page
    st.rerun()


def _highlight_compat(val: str) -> str:
    """Red ink on a clash only — the one fact that needs a decision. No fill bands."""
    return "color: #e5566f" if val == "Non-harmonic" else ""


def kpi_strip(cells: list[tuple[str, str]]) -> str:
    """One card split by 1px rules, label over value. Values must arrive formatted and escaped."""
    inner = "".join('<div class="kpi"><div class="kpi-label">' + label + '</div><div class="kpi-value">'
                    + value + "</div></div>" for label, value in cells)
    return f'<div class="kpis" style="--n:{len(cells):d}">' + inner + "</div>"


def _sequence_figure(path_songs: list[Song]):
    """3D circular figure of songs in order (setlist or Dijkstra path)."""
    G = DJSetlistGraph().build_sequence(path_songs)
    return build_3d_figure(G, circular_layout_3d(list(G.nodes)), edge_color_fn=bpm_edge_color)


def _fmt_clock(base_time: datetime, offset_seconds: float) -> str:
    t = (base_time + timedelta(seconds=offset_seconds)).time()
    return t.strftime("%H:%M")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


@st.cache_resource(max_entries=4, show_spinner="Indexing harmonic graph…")
def _library_graph(songs_t: tuple, style_items: tuple | None):
    """Harmonic graph of the whole library, built once per library/history version."""
    return harmonic_graph(list(songs_t), dict(style_items) if style_items else None)


def library_graph(songs: list[Song], style: dict | None = None):
    """Cached harmonic graph of the whole library (rebuilt only when songs/history change)."""
    return _library_graph(tuple(songs), tuple(sorted(style.items())) if style else None)
