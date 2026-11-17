import streamlit as st

from models import READ_ONLY
from db import get_songs
from ui import cluster, generate, home, library, live, theme, visualizer

# ── Must be the first Streamlit call ─────────────────────────────────────────
st.set_page_config(page_title="D-i-Jkstra", layout="wide")

theme.apply()

# ── Load song library ─────────────────────────────────────────────────────────
songs = get_songs()
if READ_ONLY:
    st.info("Read-only demo — explore freely; saving, importing and editing are switched off.", icon="🔒")

# ── Session state ─────────────────────────────────────────────────────────────
for key, default in {
    "page": "home",
    "generated_setlist": [],
    "setlist_start_time": None,
    "show_setlist_viz": False,
    "viz_path_result": None,
    "viz_path_key": None,
    "cluster_filter_ids": None,
    "cluster_filter_label": None,
    "loaded_setlist_name": None,
    "live_played": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

PAGE_MODULES = {
    "home": home, "live": live, "visualizer": visualizer,
    "generate_setlist": generate, "library": library, "cluster": cluster,
}
# The URL names the page (?page=live), so pages can be bookmarked and the back button works.
if st.query_params.get("page") in PAGE_MODULES:
    st.session_state.page = st.query_params["page"]

# ── Shell: mark, scope and nav on every page (including Home) ────────────────
theme.sidebar(songs, st.session_state.page)

# ── Router ────────────────────────────────────────────────────────────────────
PAGE_MODULES[st.session_state.page].render(songs)
