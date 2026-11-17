"""Overview: what's in the crate, and where is it thin? The Camelot wheel leads."""
from html import escape as _safe  # every user/library string inside unsafe_allow_html
import streamlit as st
from models import Song, map_genre, READ_ONLY
from db import get_saved_setlists, delete_setlist
from setlist_engine import key_gaps
from viz import camelot_wheel_figure
from ui.common import go_to, kpi_strip


def render(songs: list[Song]) -> None:
    n = len(songs)
    bpms = [s.bpm for s in songs if s.bpm]
    gaps = key_gaps(songs, top=24)
    covered = sum(1 for _, c in gaps if c > 0)
    rated = sum(1 for s in songs if s.energy is not None)
    thin_slot, thin_n = gaps[0] if gaps else ("—", 0)

    # ── Title row: the noun, the finding, the one job ──────────────────────────
    t_left, t_right = st.columns([3, 1], vertical_alignment="bottom")
    with t_left:
        st.title("Overview")
        st.markdown(f'<p class="lede">{n:,} tracks across {covered:d} of 24 keys. Thinnest key: '
                    f'<span style="color:#fff">{_safe(thin_slot)}</span> with {thin_n:d} '
                    + ("track." if thin_n == 1 else "tracks.") + "</p>", unsafe_allow_html=True)
    with t_right:
        b1, b2 = st.columns(2)
        if b1.button("Build a set", type="primary", width="stretch"):
            go_to("generate_setlist")
        if b2.button("Go live", width="stretch"):
            go_to("live")

    avg_bpm = sum(bpms) / len(bpms) if bpms else 0
    st.markdown(kpi_strip([
        ("Tracks", f"{n:,}"),
        ("Average tempo", f"{avg_bpm:.0f}<small> BPM</small>" if bpms else "—"),
        ("Keys covered", f"{covered:d}<small> of 24</small>"),
        ("Energy rated", f"{rated:,}<small> of {n:,}</small>"),
    ]), unsafe_allow_html=True)

    left, right = st.columns([3, 2], gap="small")

    # ── The wheel: the screen's answer ─────────────────────────────────────────
    with left, st.container(key="card_keys"):
        st.markdown('<p class="card-title">Keys</p><p class="card-sub">Tracks per Camelot key. '
                    'Inner ring minor (A), outer ring major (B); a short bar is a thin key.</p>',
                    unsafe_allow_html=True)
        st.plotly_chart(camelot_wheel_figure(songs), width="stretch", config={"displayModeBar": False})
        thin = gaps[:3]
        peak = max((c for _, c in gaps), default=1) or 1
        rows = "".join(
            f'<div class="row"><div class="row-main"><div class="row-title">{_safe(slot)}</div></div>'
            f'<div class="row-figs">{c:d}<small> tracks</small></div>'
            f'<div class="bar"><span style="width:{100 * c / peak:.0f}%"></span></div></div>'
            for slot, c in thin)
        st.markdown('<p class="card-title" style="margin-top:6px">Thinnest keys</p>'
                    '<p class="card-sub">Buying here opens up the most new transitions.</p>'
                    '<div class="rowlist">' + rows + "</div>", unsafe_allow_html=True)

    # ── Genres + saved sets ────────────────────────────────────────────────────
    with right:
        with st.container(key="card_genres"):
            counts: dict[str, int] = {}
            for s in songs:
                counts[map_genre(s.genre)] = counts.get(map_genre(s.genre), 0) + 1
            ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
            top = ranked[0][1] if ranked else 1
            rows = "".join(
                f'<div class="row"><div class="row-main"><div class="row-title">{_safe(g)}</div></div>'
                f'<div class="row-figs">{c:,}</div>'
                + ('<div class="bar lead">' if i == 0 else '<div class="bar">')
                + f'<span style="width:{100 * c / top:.0f}%"></span></div></div>'
                for i, (g, c) in enumerate(ranked))
            st.markdown('<p class="card-title">Genres</p>'
                        f'<p class="card-sub">{len(ranked):d} groups, most tracks first</p>'
                        '<div class="rowlist">' + rows + "</div>", unsafe_allow_html=True)

        with st.container(key="card_saved"):
            saved = get_saved_setlists()
            st.markdown('<p class="card-title">Saved sets</p>'
                        f'<p class="card-sub">{len(saved):d} saved</p>', unsafe_allow_html=True)
            if not saved:
                st.markdown('<p class="empty">Nothing saved yet. Build a set and press Save; '
                            'it will be listed here.</p>', unsafe_allow_html=True)
            for sl in saved[:4]:
                c1, c2, c3 = st.columns([5, 2, 2], vertical_alignment="center")
                minutes = sum(s.duration for s in sl["songs"]) / 60
                c1.markdown(f'<div class="row-title">{_safe(sl["name"])}</div>'
                            f'<div class="row-sub">{_safe(str(sl["vibe"]).title())} · '
                            f'{len(sl["songs"]):d} tracks · {minutes:.0f} min</div>',
                            unsafe_allow_html=True)
                if c2.button("Load", key=f"load_sl_{sl['id']}", width="stretch"):
                    st.session_state.generated_setlist = sl["songs"]
                    st.session_state.loaded_setlist_name = sl["name"]
                    st.session_state.setlist_start_time = None
                    go_to("generate_setlist")
                if c3.button("Delete", key=f"del_sl_{sl['id']}", width="stretch", disabled=READ_ONLY):
                    delete_setlist(sl["id"])
                    st.rerun()
            if len(saved) > 4:
                st.caption(f"{len(saved) - 4:d} more saved sets.")
