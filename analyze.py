"""Fill in missing BPM / key / length / energy by analyzing your audio files.

    pip install -r requirements-analysis.txt
    python analyze.py ~/Music/DJ [--overwrite] [--add-new] [--dry-run]

Files are matched to library rows by Rekordbox file location, then by title/artist tags,
then by "Artist - Title" filenames. Only empty fields are filled unless --overwrite.
Slow (a few seconds per track), so it runs here, never inside the Streamlit app.
"""
import argparse
import importlib.util
import os
import sqlite3
import sys
import urllib.parse

import numpy as np

from models import DB_PATH, to_camelot

AUDIO_EXT = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".ogg"}
ANALYSIS_SR = 22050
MIN_FILES_FOR_ENERGY = 10   # energy is a percentile over the batch; meaningless for a handful

# Krumhansl–Kessler key profiles, index 0 = tonic.
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


# ── Pure-numpy analysis (testable without librosa) ────────────────────────────

def spectrum_stats(y: np.ndarray, sr: int, n_fft: int = 8192, hop: int = 4096) -> tuple[np.ndarray, float]:
    """(12-bin chroma normalized to sum 1, spectral centroid in Hz) from a mono signal."""
    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    acc = np.zeros(len(freqs))
    frames = 0
    for start in range(0, max(1, len(y) - n_fft + 1), hop):
        frame = y[start:start + n_fft]
        if len(frame) < n_fft:
            frame = np.pad(frame, (0, n_fft - len(frame)))
        acc += np.abs(np.fft.rfft(frame * window))
        frames += 1
    mag = acc / max(frames, 1)
    band = (freqs >= 55) & (freqs <= 4200)
    pitch_class = (np.round(12 * np.log2(freqs[band] / 440.0)).astype(int) + 9) % 12   # A = 9
    chroma = np.bincount(pitch_class, weights=mag[band] ** 2, minlength=12)
    centroid = float((freqs * mag).sum() / mag.sum()) if mag.sum() else 0.0
    return chroma / (chroma.sum() or 1.0), centroid


def estimate_key(chroma: np.ndarray) -> str:
    """Camelot key whose Krumhansl profile correlates best with the chroma."""
    best = max(
        (np.corrcoef(chroma, np.roll(profile, tonic))[0, 1], tonic, minor)
        for tonic in range(12)
        for minor, profile in ((False, MAJOR_PROFILE), (True, MINOR_PROFILE))
    )
    _, tonic, minor = best
    return to_camelot(NOTE_NAMES[tonic] + ("m" if minor else ""))


def energy_scores(raw: list[tuple[float, float, float]]) -> list[int]:
    """1–10 energy per track from (rms_db, centroid_hz, bpm): mean of the three z-scores,
    then deciles over the batch. Loud, bright, fast → high."""
    arr = np.array(raw, dtype=float)
    std = arr.std(axis=0)
    std[std == 0] = 1.0
    combined = ((arr - arr.mean(axis=0)) / std).mean(axis=1)
    ranks = combined.argsort().argsort()
    return [int(1 + r * 10 // len(raw)) for r in ranks]


def refine_bpm(beat_times) -> float | None:
    """BPM from the least-squares slope of beat time vs beat number — sub-frame precise,
    unlike the tempo estimate, which snaps to a coarse grid (… 123.0, 129.2 …)."""
    beat_times = np.asarray(beat_times, dtype=float)
    if len(beat_times) < 8:
        return None
    slope = np.polyfit(np.arange(len(beat_times)), beat_times, 1)[0]
    return 60.0 / slope if slope > 0 else None


# ── File analysis (librosa) ───────────────────────────────────────────────────

def analyze_file(path: str) -> dict:
    import librosa  # optional dependency
    y, sr = librosa.load(path, sr=ANALYSIS_SR, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    bpm = refine_bpm(beats) or float(np.atleast_1d(tempo)[0])
    while bpm and bpm < 70:     # beat trackers often lock onto half time
        bpm *= 2
    chroma, centroid = spectrum_stats(y, sr)
    rms_db = float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9))
    return {"bpm": round(bpm, 1), "key": estimate_key(chroma), "duration": round(len(y) / sr, 1),
            "rms_db": rms_db, "centroid": centroid}


def read_tags(path: str) -> tuple[str, str]:
    """(title, artist) from tags, else from an 'Artist - Title' filename."""
    try:
        import mutagen
        tags = mutagen.File(path, easy=True) or {}
        title, artist = (tags.get("title") or [""])[0], (tags.get("artist") or [""])[0]
        if title and artist:
            return title.strip(), artist.strip()
    except Exception:
        pass
    stem = os.path.splitext(os.path.basename(path))[0]
    artist, _, title = stem.partition(" - ")
    return (title.strip(), artist.strip()) if title else (stem.strip(), "")


def _location_path(location: str) -> str:
    """Rekordbox 'file://localhost/Users/x/a%20b.mp3' → '/Users/x/a b.mp3'."""
    p = urllib.parse.urlparse(location)
    return os.path.normpath(urllib.parse.unquote(p.path))


def _file_url(path: str) -> str:
    return "file://localhost" + urllib.parse.quote(os.path.abspath(path))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music_dir")
    ap.add_argument("--overwrite", action="store_true", help="replace existing BPM/key/length/energy")
    ap.add_argument("--add-new", action="store_true", help="insert files that match no library row")
    ap.add_argument("--dry-run", action="store_true", help="print what would change, write nothing")
    args = ap.parse_args(argv)

    if importlib.util.find_spec("librosa") is None:
        print("librosa is required: pip install -r requirements-analysis.txt", file=sys.stderr)
        return 1

    import db   # creates/migrates the schema
    db._ensure_schema()
    files = sorted(os.path.join(root, f) for root, _, names in os.walk(args.music_dir)
                   for f in names if os.path.splitext(f)[1].lower() in AUDIO_EXT)
    if not files:
        print("No audio files found.")
        return 0

    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT track_title, artist, bpm, key, duration, energy, location FROM tracks").fetchall()
    by_loc = {_location_path(r[6]): r for r in rows if r[6]}
    by_name = {(r[0].lower(), r[1].lower()): r for r in rows}

    results = []
    for i, path in enumerate(files, 1):
        title, artist = read_tags(path)
        row = by_loc.get(os.path.normpath(os.path.abspath(path))) or by_name.get((title.lower(), artist.lower()))
        if row is None and not args.add_new:
            print(f"[{i}/{len(files)}] skip (not in library): {os.path.basename(path)}")
            continue
        try:
            a = analyze_file(path)
        except Exception as e:  # unreadable / unsupported file — report and move on
            print(f"[{i}/{len(files)}] failed: {os.path.basename(path)}: {e}")
            continue
        print(f"[{i}/{len(files)}] {title} — {artist}: {a['bpm']} BPM, {a['key']}, {a['duration']:.0f}s")
        results.append((path, title, artist, row, a))

    energies = (energy_scores([(a["rms_db"], a["centroid"], a["bpm"]) for *_, a in results])
                if len(results) >= MIN_FILES_FOR_ENERGY else [None] * len(results))
    if len(results) < MIN_FILES_FOR_ENERGY:
        print(f"(energy skipped: needs ≥{MIN_FILES_FOR_ENERGY} analyzed files to rank against)")

    updates, inserts = [], []
    for (path, title, artist, row, a), energy in zip(results, energies):
        if row is None:
            inserts.append((title, artist, a["bpm"], a["key"], "", a["duration"], _file_url(path), energy))
            continue
        _, _, bpm, key, duration, cur_energy, _ = row
        new = {
            "bpm": a["bpm"] if args.overwrite or not bpm else bpm,
            "key": a["key"] if args.overwrite or not key else key,
            "duration": a["duration"] if args.overwrite or not duration else duration,
            "energy": energy if energy is not None and (args.overwrite or cur_energy is None) else cur_energy,
        }
        if (new["bpm"], new["key"], new["duration"], new["energy"]) != (bpm, key, duration, cur_energy):
            updates.append((new["bpm"], new["key"], new["duration"], new["energy"], row[0], row[1]))

    print(f"\n{len(updates)} track(s) to update, {len(inserts)} to add.")
    if args.dry_run:
        print("Dry run — nothing written.")
        return 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany("UPDATE tracks SET bpm=?, key=?, duration=?, energy=? WHERE track_title=? AND artist=?",
                         updates)
        conn.executemany("INSERT OR IGNORE INTO tracks (track_title, artist, bpm, key, genre, duration, location, "
                         "energy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", inserts)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
