"""Generate Setlist page: options, generation, quality, set editor, exports, energy timeline."""
import random
from html import escape as _safe  # every user/library string inside unsafe_allow_html
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from models import (
    Song, map_genre, key_compat_label, VIBE_CONFIG, song_id, song_label, fmt_duration,
    track_energy, STYLE_WEIGHT, READ_ONLY,
)
from db import (
    save_setlist, get_saved_setlists, setlist_to_rekordbox_xml, get_all_cues,
    get_transition_counts,
)
from setlist_engine import (
    generate_setlist, smoothest_setlist, setlist_quality, start_offsets, move_track,
    swap_candidates, insert_bridge, mix_points, play_times, style_bonuses, regenerate_unlocked,
    energy_target,
)
from viz import setlist_to_csv_bytes, energy_timeline_figure
from ui.common import _fmt_clock, _highlight_compat, _sequence_figure, kpi_strip, library_graph


def render(songs: list[Song]) -> None:
    st.title("Build a set")
    st.markdown('<p class="lede">Pick the window and the vibe; the set follows its energy curve and '
                'only mixes between compatible keys.</p>', unsafe_allow_html=True)

    cluster_ids = st.session_state.get("cluster_filter_ids")
    cluster_label = st.session_state.get("cluster_filter_label")
    if cluster_ids:
        col_info, col_clear = st.columns([5, 1])
        col_info.info(f"Generating from **{cluster_label}** — {len(cluster_ids)} songs pre-selected.")
        if col_clear.button("Clear", help="Remove cluster filter"):
            st.session_state.cluster_filter_ids = None
            st.session_state.cluster_filter_label = None
            st.rerun()

    # ── Time window ──────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        start_time = st.time_input("Start time", value=datetime.strptime("23:00", "%H:%M").time())
    with c2:
        end_time = st.time_input("End time", value=datetime.strptime("01:00", "%H:%M").time())
    overnight = st.toggle("Overnight set (ends next day)", value=(end_time <= start_time))

    # ── Vibe + generation options ─────────────────────────────────────────────
    col_vibe, col_seed = st.columns([3, 1])
    vibe = col_vibe.selectbox("Vibe", [v.title() for v in VIBE_CONFIG])
    reproducible = col_seed.toggle("Reproducible", value=False,
                                     help="Fixed seed — same inputs always produce the same setlist")

    bpm_target = st.slider("BPM range filter", 60, 220, (60, 220),
                           help="Only tracks within this BPM range are eligible for the set")
    use_curve = st.toggle(
        "Follow vibe energy curve", value=True,
        help="Steer track choice toward the vibe's target energy over the set (warm-up → peak → cool-down). "
             "Uses each track's 1–10 energy rating, or an estimate from BPM. Off = just the smoothest harmonic path.",
    )

    with st.expander("Advanced"):
        use_blends = st.toggle(
            "Account for blends", value=True,
            help="Time each track from its mix-in to its mix-out (Rekordbox cue points; otherwise "
                 "a 32-bar blend before the end), so the set fills the window the way you'd play it.",
        )
        counts = get_transition_counts()
        use_style = st.toggle(
            f"Use my mixing history ({len(counts)} learned transitions)", value=bool(counts),
            disabled=not counts,
            help="Favor transitions you've actually played (import history on the Library page). "
                 "Played pairs also count as valid even when the keys don't match.",
        )
        style_weight = st.slider("History influence", 0.0, 10.0, STYLE_WEIGHT, 0.5, disabled=not use_style)
        search = st.radio("Search", ["auto", "greedy", "beam"], horizontal=True,
                          help="Greedy tries up to 500 openers; beam keeps the 40 best partial sets per step. "
                               "Auto = greedy for libraries ≤ 500 tracks, beam above (it fits the energy "
                               "curve far better on big libraries). Both get a 2-opt polish.")
    play_time = play_times(songs, get_all_cues()) if use_blends else None
    style = style_bonuses(counts, style_weight) if use_style else None

    # ── Track pinning / avoidance ─────────────────────────────────────────────
    with st.expander("Pin opener / closer (optional)"):
        pin_col1, pin_col2 = st.columns(2)
        pinned_opener = pin_col1.selectbox("Opener (first track)", [None, *songs],
                                           format_func=song_label, key="pin_opener")
        pinned_closer = pin_col2.selectbox("Closer (last track)", [None, *songs],
                                           format_func=song_label, key="pin_closer")
        if pinned_opener and pinned_closer and song_id(pinned_opener) == song_id(pinned_closer):
            st.warning("Opener and closer are the same song — the closer will be ignored.")

    saved_by_id = {sl["id"]: sl for sl in get_saved_setlists()}
    avoid_ids = []
    if saved_by_id:
        avoid_ids = st.multiselect(
            "Avoid songs from saved setlists", list(saved_by_id),
            format_func=lambda i: f"{saved_by_id[i]['name']} ({saved_by_id[i]['created_at']})",
            help="Keep repeat crowds from hearing the same tracks — these songs are excluded (unless pinned).",
        )

    if st.button("Generate", width="stretch", type="primary"):
        st.session_state.show_setlist_viz = False

        start_dt = datetime.combine(datetime.today(), start_time)
        end_dt = datetime.combine(
            datetime.today() + timedelta(days=1 if overnight else 0), end_time
        )
        if not overnight and end_dt <= start_dt:
            st.error("End time must be after start time for a same-day set.")
            st.stop()

        total_duration = (end_dt - start_dt).total_seconds()
        final_songs = generate_setlist(
            songs, vibe, total_duration,
            candidate_ids=cluster_ids,
            exclude_ids={song_id(s) for i in avoid_ids for s in saved_by_id[i]["songs"]},
            opener=pinned_opener,
            closer=pinned_closer,
            use_energy_curve=use_curve,
            bpm_range=bpm_target if bpm_target != (60, 220) else None,
            rng=random.Random(42) if reproducible else None,
            play_time=play_time,
            style=style,
            search=search,
            graph=library_graph(songs, style),
        )

        if not final_songs:
            st.warning(
                "No tracks matched this vibe and time window. "
                "Try a different vibe or a wider time range."
            )
            st.session_state.generated_setlist = []
            st.session_state.setlist_start_time = None
            st.stop()

        st.session_state.generated_setlist = final_songs
        st.session_state.setlist_start_time = start_dt
        st.session_state.loaded_setlist_name = None
        st.session_state.setlist_window = total_duration

    setlist: list[Song] = st.session_state.get("generated_setlist", [])
    if not setlist:
        return

    start_dt: datetime | None = st.session_state.get("setlist_start_time")
    offsets = start_offsets(setlist, play_time)
    cues_by_id = get_all_cues() if use_blends else {}

    # ── Quality metrics ───────────────────────────────────────────────────────
    st.subheader(st.session_state.get("loaded_setlist_name") or "Your set")
    q = setlist_quality(setlist, play_time)
    if q:
        clashes = round((1 - q["pct_harmonic"]) * (len(setlist) - 1))
        st.markdown(kpi_strip([
            ("Quality", f"{q['quality']:.0f}<small> of 100</small>"),
            ("Tracks", f"{len(setlist):d}"),
            ("Length", _safe(fmt_duration(q["total_seconds"]))
             + (f"<small> of {st.session_state.setlist_window / 3600:.1f} h</small>"
                if st.session_state.get("setlist_window") else "")),
            ("Key clashes", (f'<span class="bad">{clashes:d}</span>' if clashes else "0")
             + f"<small> of {len(setlist) - 1:d} transitions</small>"),
            ("Average BPM change", f"{q['avg_bpm_delta']:.1f}"),
        ]), unsafe_allow_html=True)

    # ── Setlist table ─────────────────────────────────────────────────────────
    rows = []
    for i, song in enumerate(setlist):
        prev = setlist[i - 1] if i > 0 else None
        row = {
            "#": i + 1,
            "Title": song.name,
            "Artist": song.artist,
            "BPM": song.bpm,
            "Key": song.key,
            "Length": fmt_duration(song.duration),
            "Energy": (f"{song.energy}" if song.energy is not None
                       else f"~{track_energy(song.bpm):.0f}"),
            "Genre": map_genre(song.genre),
            "BPM Δ": f"{song.bpm - prev.bpm:+.1f}" if prev else "—",
            "Key Compat": key_compat_label(prev.key, song.key) if prev else "—",
        }
        if start_dt:
            row["Time"] = _fmt_clock(start_dt, offsets[i])
        if use_blends:
            mix_in, mix_out = mix_points(song, cues_by_id.get(song_id(song)))
            row["Mix in"], row["Mix out"] = fmt_duration(mix_in), fmt_duration(mix_out)
        rows.append(row)

    setlist_df = pd.DataFrame(rows)
    cols = (["#"] + (["Time"] if start_dt else []) + ["Title", "Artist", "BPM", "Key", "Energy", "Length"]
            + (["Mix in", "Mix out"] if use_blends else []) + ["Genre", "BPM Δ", "Key Compat"])
    setlist_df = setlist_df[cols]
    styled = setlist_df.style.map(_highlight_compat, subset=["Key Compat"]).format({"BPM": "{:.1f}"})
    st.dataframe(styled, width="stretch", hide_index=True)

    no_location = [s.name for s in setlist if not s.location]
    if no_location:
        st.caption(f"⚠️ {len(no_location)} track(s) have no file location, so the Rekordbox playlist "
                   "won't link them. Import your library from a Rekordbox XML export to capture locations.")

    # ── Edit the set ──────────────────────────────────────────────────────────
    curve = VIBE_CONFIG.get(vibe.lower(), {}).get("energy_curve") if use_curve else None
    with st.expander("Edit set"):
        row = st.selectbox("Track", range(len(setlist)), key=f"edit_row_{len(setlist)}",
                           format_func=lambda i: f"{i + 1}. {setlist[i].name} — {setlist[i].artist}")
        e1, e2, e3, e4 = st.columns(4)
        new_set = None
        if e1.button("↑ Move up", width="stretch", disabled=row == 0):
            new_set = move_track(setlist, row, -1)
        if e2.button("↓ Move down", width="stretch", disabled=row == len(setlist) - 1):
            new_set = move_track(setlist, row, 1)
        if e3.button("✕ Remove", width="stretch"):
            new_set = setlist[:row] + setlist[row + 1:]
        rough = row > 0 and key_compat_label(setlist[row - 1].key, setlist[row].key) == "Non-harmonic"
        if e4.button("Fix transition into this track", width="stretch", disabled=not rough,
                     help="Insert bridge songs (Dijkstra) between the previous track and this one"):
            new_set = insert_bridge(songs, setlist, row, style, graph=library_graph(songs, style))
            if new_set is None:
                st.warning("No harmonic bridge exists between these two tracks.")
        st.markdown("**Lock & regenerate** — keep the tracks you love in place, refill everything else")
        lock_col, regen_col = st.columns([4, 1])
        locked = lock_col.multiselect(
            "Locked tracks", range(len(setlist)), key=f"locked_{len(setlist)}",
            format_func=lambda i: f"{i + 1}. {setlist[i].name}", label_visibility="collapsed",
            placeholder="Choose tracks to keep…")
        if regen_col.button("Regenerate", width="stretch", disabled=not locked,
                            help="Each gap between locked tracks gets its old time budget, starts and ends "
                                 "harmonically against the locked tracks, and follows the energy curve."):
            new_set = regenerate_unlocked(
                songs, setlist, set(locked), vibe, use_energy_curve=use_curve,
                exclude_ids={song_id(s) for i in avoid_ids for s in saved_by_id[i]["songs"]},
                play_time=play_time, style=style, search=search)
        if new_set is not None:
            st.session_state.generated_setlist = new_set
            st.session_state.show_setlist_viz = False
            st.rerun()

        st.markdown("**Replacements** — best fit for this slot (lowest transition cost from the previous and into the next track)")
        for cand, cost in swap_candidates(songs, setlist, row, energy_curve=curve, play_time=play_time):
            rc1, rc2 = st.columns([5, 1])
            rc1.markdown(f"**{_safe(cand.name)}** — {_safe(cand.artist)} · {cand.bpm:.0f} BPM · {_safe(cand.key)} "
                         f"<span style='color:#888'>(cost {cost:.1f})</span>", unsafe_allow_html=True)
            if rc2.button("Swap in", key=f"swap_{row}_{cand.name}_{cand.artist}"):
                st.session_state.generated_setlist = setlist[:row] + [cand] + setlist[row + 1:]
                st.session_state.show_setlist_viz = False
                st.rerun()

    # ── Actions: exports on the left, save on the right, one row ─────────────
    a1, a2, a3, a4, a5, a6 = st.columns([1, 1.3, 1.1, 0.9, 1.4, 0.8], vertical_alignment="bottom")
    a1.download_button("CSV", setlist_to_csv_bytes(setlist), "setlist.csv", "text/csv", width="stretch",
                       help="Download the set as a spreadsheet")
    a2.download_button(
        "Rekordbox XML",
        setlist_to_rekordbox_xml(st.session_state.get("loaded_setlist_name") or f"{vibe} set", setlist),
        "setlist.xml", "application/xml", width="stretch",
        help="Rekordbox → Preferences → Advanced → Database → rekordbox xml, point it at this file, "
             "then import the playlist from the 'rekordbox xml' tree.",
    )
    if a3.button("Smoothest order", width="stretch",
                 help="Reorder by nearest neighbour from the first track: smallest BPM and key steps"):
        st.session_state.generated_setlist = smoothest_setlist(setlist, style)
        st.session_state.show_setlist_viz = False
        st.rerun()
    if a4.button("3D view", width="stretch", help="Show the set as a circle of transitions"):
        st.session_state.show_setlist_viz = True
    default_name = st.session_state.get("loaded_setlist_name") or f"{vibe} set"
    save_name = a5.text_input("Set name", value=default_name, placeholder="Name this set…")
    if a6.button("Save", width="stretch", disabled=READ_ONLY):
        sid = save_setlist(save_name or "Untitled", vibe, setlist)
        st.session_state.loaded_setlist_name = save_name
        st.success(f"Saved as **{save_name}** (#{sid})")

    # ── Energy Timeline ───────────────────────────────────────────────────────
    st.subheader("Energy across the night")
    timeline_x = [_fmt_clock(start_dt, o) for o in offsets] if start_dt else None
    total_time = sum(play_time.get(song_id(s), s.duration) if play_time else s.duration for s in setlist)
    st.plotly_chart(energy_timeline_figure(
        setlist, x_labels=timeline_x,
        energy=[track_energy(s.bpm, s.energy) for s in setlist],
        energy_target=[energy_target(curve, o / total_time) for o in offsets] if curve else None,
    ), width="stretch", config={"displayModeBar": False})

    if st.session_state.show_setlist_viz:
        st.plotly_chart(_sequence_figure(setlist), width="stretch")
        st.caption("Tracks in set order around the circle. Brighter edges are smaller BPM changes "
                   "(2 BPM or less, then 5 or less, then more).")
