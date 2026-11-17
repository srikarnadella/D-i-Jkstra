"""Live: what do I play next? Deck A (playing) → the move → Deck B (cued), then the other options."""
from html import escape as _safe  # every user/library string inside unsafe_allow_html
import streamlit as st
from datetime import datetime
from models import Song, map_genre, song_id, song_label, track_energy, key_compat_label, READ_ONLY
from db import save_setlist, get_transition_counts
from setlist_engine import style_bonuses, next_track_suggestions

DIRECTIONS = {"cool": "Cool down", "hold": "Hold", "push": "Push"}


def _live_play(current: Song, nxt: Song) -> None:
    """Button callback: move to the next track (runs before widgets, so it may set their state)."""
    st.session_state.live_played.append(current)
    st.session_state.live_current = nxt


def _deck_body(s: Song) -> str:
    return (f'<div class="deck-title">{_safe(s.name)}</div><div class="deck-artist">{_safe(s.artist)}</div>'
            f'<div class="deck-figs"><span>{s.bpm:.1f}<small> BPM</small></span>'
            f'<span>{_safe(s.key or "—")}</span>'
            f'<span>{track_energy(s.bpm, s.energy):.1f}<small> energy</small></span></div>')


def render(songs: list[Song]) -> None:
    if not songs:
        st.title("Live")
        st.info("Your library is empty. Add tracks on the Library page.")
        return

    played: list[Song] = st.session_state.live_played
    counts = get_transition_counts()

    # ── Title row: the noun + the floor's direction ────────────────────────────
    t_left, t_right = st.columns([3, 2], vertical_alignment="bottom")
    with t_left:
        st.title("Live")
        st.markdown(f'<p class="lede">{len(played):d} played tonight. The cued track is the smoothest '
                    'move in the direction you choose.</p>', unsafe_allow_html=True)
    with t_right:
        direction = st.segmented_control("Take the floor", list(DIRECTIONS), default="hold",
                                         format_func=DIRECTIONS.get, key="live_direction") or "hold"

    use_style = t_right.toggle(f"Favor my mixing history ({len(counts):,} learned)",
                               value=bool(counts), disabled=not counts)

    # ── The deck strip: the screen's answer. Each deck holds its own control. ──
    # Same 3:2 split as the row below, so Deck B and "Played tonight" share their left edge.
    top_left, d_b = st.columns([3, 2], gap="small")
    d_a, d_link = top_left.columns([2.3, 1], gap="small")
    with d_a, st.container(key="card_deck_a"):
        current = st.selectbox("Deck A · playing", songs, format_func=song_label, key="live_current")
        st.markdown(_deck_body(current), unsafe_allow_html=True)

    suggestions = next_track_suggestions(
        songs, current, {song_id(s) for s in played}, direction, n=6,
        style=style_bonuses(counts) if use_style else None,
    )
    cued = suggestions[0][0] if suggestions else None
    with d_link:
        if cued:
            clash = key_compat_label(current.key, cued.key) == "Non-harmonic"
            st.markdown(('<div class="link clash">' if clash else '<div class="link">')
                        + '<div class="link-words">' + _safe(" · ".join(suggestions[0][2]))
                        + '</div><div class="link-line"></div></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="link"><div class="link-words">Nothing compatible left in this '
                        'direction. Try another.</div></div>', unsafe_allow_html=True)
    with d_b, st.container(key="card_deck_b"):
        if cued:
            st.markdown('<div class="deck-label">Deck B · cued</div>' + _deck_body(cued),
                        unsafe_allow_html=True)
            st.button("Play next", type="primary", width="stretch", key="live_play_cued",
                      on_click=_live_play, args=(current, cued))
        else:
            st.markdown('<div class="deck-label">Deck B · cued</div><p class="empty">Empty</p>',
                        unsafe_allow_html=True)

    # ── Other options + tonight's history ──────────────────────────────────────
    left, right = st.columns([3, 2], gap="small")
    with left, st.container(key="card_options"):
        st.markdown('<p class="card-title">Other options</p>'
                    f'<p class="card-sub">Next best moves for “{_safe(DIRECTIONS[direction].lower())}”</p>',
                    unsafe_allow_html=True)
        if len(suggestions) <= 1:
            st.markdown('<p class="empty">No other compatible tracks.</p>', unsafe_allow_html=True)
        for cand, _, reasons in suggestions[1:]:
            c1, c2, c3 = st.columns([5, 3, 1.4], vertical_alignment="center")
            c1.markdown(f'<div class="row-title">{_safe(cand.name)}</div>'
                        f'<div class="row-sub">{_safe(cand.artist)} · {_safe(map_genre(cand.genre))}</div>',
                        unsafe_allow_html=True)
            c2.markdown(f'<div class="row-figs">{cand.bpm:.1f}<small> BPM</small> · {_safe(cand.key)}</div>'
                        f'<div class="row-sub" style="text-align:right">{_safe(" · ".join(reasons[1:]))}</div>',
                        unsafe_allow_html=True)
            c3.button("Play", key=f"live_{cand.name}_{cand.artist}", width="stretch",
                      on_click=_live_play, args=(current, cand))

    with right, st.container(key="card_tonight"):
        mins = sum(s.duration for s in played) / 60
        h1, h2, h3 = st.columns([3, 1.3, 1.3], vertical_alignment="center")
        h1.markdown('<p class="card-title">Played tonight</p>'
                    + (f'<p class="card-sub">{len(played):d} tracks · {mins:.0f} min</p>' if played
                       else '<p class="card-sub">Newest first</p>'),
                    unsafe_allow_html=True)
        if h2.button("Save", width="stretch", disabled=READ_ONLY or not played,
                     help="Saves tonight, including the track playing now, as a set"):
            name = f"Live {datetime.now():%Y-%m-%d %H:%M}"
            sid = save_setlist(name, "live", played + [current])
            st.success(f"Saved as **{name}** (#{sid}).")
        if h3.button("Reset", width="stretch", disabled=not played):
            st.session_state.live_played = []
            st.rerun()
        # A fixed five rows, newest first; empty slots stay as dashes so the card keeps its shape.
        recent = list(reversed(played[-5:]))
        rows = "".join(
            f'<div class="row"><div class="row-main"><div class="row-title">{_safe(s.name)}</div>'
            f'<div class="row-sub">{_safe(s.artist)}</div></div>'
            f'<div class="row-figs">{s.bpm:.0f}<small> BPM</small> · {_safe(s.key)}</div></div>'
            for s in recent)
        rows += "".join('<div class="row"><div class="row-main"><div class="row-title" style="color:#949494">—'
                        '</div><div class="row-sub">&nbsp;</div></div></div>' for _ in range(5 - len(recent)))
        st.markdown('<div class="rowlist tight">' + rows + "</div>", unsafe_allow_html=True)
