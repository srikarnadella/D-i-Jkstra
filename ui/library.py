"""Library page: browse/edit tracks, history learning, cue viewer, bulk import, add track."""
import pandas as pd
import streamlit as st
from models import Song, map_genre, parse_key, to_camelot, parse_duration, fmt_duration, READ_ONLY
from db import (
    get_library_df, insert_track, save_library_changes, adapt_uploaded_csv,
    parse_rekordbox_xml, parse_rekordbox_cues, get_cues, parse_rekordbox_playlists,
    record_transitions, get_transition_counts, clear_transitions, library_changes,
    import_tracks,
)
from setlist_engine import harmonic_orphans
from ui.common import _plural, library_graph


def render(songs: list[Song]) -> None:
    st.title("Library")

    search = st.text_input("Search by title or artist")
    all_mapped_genres = sorted(set(map_genre(s.genre) for s in songs))
    filter_col1, filter_col2 = st.columns([3, 1])
    genre_filter = filter_col1.multiselect("Filter by genre", all_mapped_genres, default=[])
    show_orphans = filter_col2.toggle(
        "Orphans only",
        help="Songs with no key- and BPM-compatible partner — they will never appear in a generated setlist",
    )

    df_lib = get_library_df(search=search, genre_filter=genre_filter)

    if show_orphans:
        orphans = harmonic_orphans(songs, library_graph(songs))
        df_lib = df_lib[[(t, a) in orphans for t, a in zip(df_lib["Title"], df_lib["Artist"])]]
        st.warning(f"{len(df_lib)} harmonic orphan(s) — no compatible key + BPM partner in the library.")

    st.caption(f"{len(df_lib)} tracks — check 'Delete?' and click **Save Changes** to remove rows, "
               "or edit BPM/Key/Genre/Length inline. Key accepts Camelot (8A) or musical (Am).")

    editor_df = df_lib.copy()
    editor_df.insert(0, "Delete?", False)

    # Key includes filter state so any filter change resets edit state,
    # preventing stale edits from being applied to wrong rows.
    editor_key = f"library_editor_{hash(search)}_{hash(tuple(sorted(genre_filter)))}_{show_orphans}"
    edited = st.data_editor(
        editor_df,
        column_config={
            "Delete?": st.column_config.CheckboxColumn(help="Mark row for deletion"),
            "Title": st.column_config.TextColumn(disabled=True),
            "Artist": st.column_config.TextColumn(disabled=True),
            "BPM": st.column_config.NumberColumn(min_value=60.0, max_value=220.0, step=0.5, format="%.1f"),
            "Key": st.column_config.TextColumn(help="Camelot (8A, 12B) or musical (Am, F#)"),
            "Genre": st.column_config.TextColumn(),
            "Length (s)": st.column_config.NumberColumn(
                min_value=1, step=1, format="%d s",
                help="Track length in seconds. Blank = assumed 3:30"),
            "Energy": st.column_config.NumberColumn(
                min_value=1, max_value=10, step=1,
                help="1–10 (e.g. Mixed In Key). Blank = estimated from BPM"),
        },
        hide_index=True,
        width="stretch",
        key=editor_key,
        disabled=READ_ONLY,
    )

    if st.button("Save Changes", type="primary", disabled=READ_ONLY):
        to_delete, to_update, errors = library_changes(df_lib, edited)
        if errors:
            for e in errors:
                st.error(e)
        elif to_delete or to_update:
            save_library_changes(to_delete=to_delete, to_update=to_update)
            parts = []
            if to_delete:
                parts.append(f"Deleted {_plural(len(to_delete), 'track')}")
            if to_update:
                parts.append(f"Updated {_plural(len(to_update), 'track')}")
            st.session_state.library_msg = ". ".join(parts) + "."
            st.cache_data.clear()
            st.rerun()
        else:
            st.info("No changes detected.")

    if msg := st.session_state.pop("library_msg", None):
        st.success(msg)

    with st.expander("Learn from your mixing history"):
        counts = get_transition_counts()
        st.caption(f"{len(counts)} transitions learned so far. Upload a Rekordbox XML export and pick the "
                   "playlists you actually played (history playlists are ideal) — every consecutive pair is "
                   "counted, and generation can favor transitions you've proven work.")
        hist_file = st.file_uploader("Rekordbox XML", type=["xml"], key="history_xml", disabled=READ_ONLY)
        if hist_file:
            playlists = parse_rekordbox_playlists(hist_file.getvalue())
            if not playlists:
                st.warning("No playlists found in this file.")
            else:
                chosen = st.multiselect("Played playlists", list(playlists),
                                        format_func=lambda p: f"{p} ({len(playlists[p])} tracks)")
                if st.button("Learn transitions", disabled=not chosen or READ_ONLY):
                    n_pairs = record_transitions([playlists[p] for p in chosen])
                    st.session_state.library_msg = f"Learned {_plural(n_pairs, 'transition')} from {len(chosen)} playlist(s)."
                    st.rerun()
        if counts and st.button("Forget all learned transitions", disabled=READ_ONLY):
            clear_transitions()
            st.session_state.library_msg = "Cleared mixing history."
            st.rerun()

    with st.expander("Cue points"):
        if df_lib.empty:
            st.caption("No tracks match the filters.")
        else:
            pick = st.selectbox("Track", list(zip(df_lib["Title"], df_lib["Artist"])),
                                format_func=lambda p: f"{p[0]} — {p[1]}")
            cue_rows = get_cues(*pick)
            if cue_rows:
                st.dataframe(pd.DataFrame([
                    {"Cue": "Memory" if c["num"] < 0 else f"Hot {chr(65 + c['num'])}",
                     "Name": c["name"], "Time": fmt_duration(c["start_seconds"])}
                    for c in cue_rows]), hide_index=True, width="stretch")
            else:
                st.caption("No cues stored — import a Rekordbox XML export to bring them in.")

    st.divider()
    imp_col, add_col = st.columns([1, 1])

    with imp_col:
        st.subheader("Bulk Import")
        st.caption("CSV with columns Title (or track_title), Artist, BPM, Key, Genre, optional Duration "
                   "(seconds or m:ss) — or a Rekordbox collection XML export.")
        import_file = st.file_uploader("Upload CSV or Rekordbox XML", type=["csv", "xml"], key="lib_csv_import",
                                       disabled=READ_ONLY)
        # The uploader keeps the file across reruns; import each upload once.
        if import_file and st.session_state.get("last_import_id") != import_file.file_id:
            st.session_state.last_import_id = import_file.file_id
            try:
                cues = []
                if import_file.name.lower().endswith(".xml"):
                    xml_bytes = import_file.getvalue()
                    adapted = parse_rekordbox_xml(xml_bytes)
                    cues = parse_rekordbox_cues(xml_bytes)
                else:
                    adapted = adapt_uploaded_csv(pd.read_csv(import_file), fill_duration=False)
                c = import_tracks(adapted, cues)
                parts = []
                if c["inserted"]:
                    parts.append(f"Imported {_plural(c['inserted'], 'new track')}")
                if c["cues"]:
                    parts.append(f"{_plural(c['cues'], 'cue point')} saved")
                if c["skipped"]:
                    parts.append(f"{c['skipped']} already existed")
                if c["invalid"]:
                    parts.append(f"{c['invalid']} skipped (missing title/artist or invalid key)")
                st.session_state.library_msg = ". ".join(parts) + "." if parts else "Nothing to import."
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")

    with add_col:
        st.subheader("Add Track")
        with st.form("add_track", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            title = fc1.text_input("Title *")
            artist = fc2.text_input("Artist *")
            fc3, fc4, fc5, fc6, fc7 = st.columns(5)
            bpm = fc3.number_input("BPM", min_value=60.0, max_value=220.0, step=0.5, value=120.0)
            key_input = fc4.text_input("Key (8A or Am)")
            length_input = fc5.text_input("Length (m:ss)")
            energy_input = fc6.selectbox("Energy", [None, *range(1, 11)],
                                         format_func=lambda e: "Auto" if e is None else str(e))
            genre_input = fc7.text_input("Genre")
            submitted = st.form_submit_button("Add Track", type="primary", disabled=READ_ONLY)

        if submitted:
            key_val = to_camelot(key_input)
            if not title.strip() or not artist.strip():
                st.error("Title and Artist are required.")
            elif key_val and parse_key(key_val)[0] is None:
                st.error("Key must be Camelot (8A, 12B) or musical notation (Am, F#, Bb).")
            elif length_input.strip() and parse_duration(length_input) is None:
                st.error("Length must look like 3:45 (or seconds).")
            else:
                try:
                    inserted = insert_track(
                        title=title.strip(), artist=artist.strip(), bpm=bpm, key=key_val,
                        genre=genre_input.strip(), duration=parse_duration(length_input),
                        energy=energy_input,
                    )
                    if inserted:
                        st.session_state.library_msg = f"Added '{title.strip()}' by {artist.strip()}."
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.warning(f"'{title.strip()}' by {artist.strip()} already exists in the library.")
                except Exception as e:
                    st.error(f"Failed to add track: {e}")
