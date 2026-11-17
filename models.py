from collections import namedtuple
import os
import re

# ── Path / timing constants ───────────────────────────────────────────────────
DB_PATH = os.environ.get("DJ_DB_PATH", "dj_tracks.db")
READ_ONLY = os.environ.get("DJ_READ_ONLY", "").lower() in ("1", "true", "yes")  # public demo: no writes
TRACK_DURATION_SECONDS = 210    # fallback when a track has no stored duration
MAX_HARMONIC_BPM_DELTA = 25     # max BPM difference for a harmonic edge
BPM_OCTAVE_DELTA = 8            # tolerance when matching half-time/double-time BPMs
SCORE_JITTER = 0.3              # random tiebreak added to vibe score

# ── Energy (1–10) ─────────────────────────────────────────────────────────────
# Tracks without a rating get one estimated from BPM: ENERGY_BPM_LOW → 3, ENERGY_BPM_HIGH → 9.
ENERGY_BPM_LOW, ENERGY_BPM_HIGH = 90.0, 140.0
# Cost of one energy point off the curve, in transition-cost units (≈ BPM). One energy
# point ≈ 8 BPM on the estimate scale, so this keeps curve-following and smoothness balanced.
ENERGY_WEIGHT = 6.0
STYLE_WEIGHT = 3.0              # cost bonus per log(1 + times you've played a transition)
BLEND_BARS = 32                 # default mix-out = this many bars before the end, if no cue

# ── Core type ────────────────────────────────────────────────────────────────
# Defined here (not inside any function) so pickle can find it for st.cache_data.
# duration (seconds), location (file URL from Rekordbox, needed to export playlists) and
# energy (1–10 rating, None = estimate from BPM) are optional so 5-field constructors and
# old saved setlists still work.
Song = namedtuple("Song", ["name", "artist", "genre", "bpm", "key", "duration", "location", "energy"],
                  defaults=(TRACK_DURATION_SECONDS, None, None))


def track_energy(bpm: float, energy=None) -> float:
    """The track's 1–10 energy rating, or an estimate from BPM when it has none."""
    if energy is not None and energy == energy:  # not None / NaN
        return float(energy)
    est = 3 + (float(bpm or 0) - ENERGY_BPM_LOW) * 6 / (ENERGY_BPM_HIGH - ENERGY_BPM_LOW)
    return min(10.0, max(1.0, est))


def parse_energy(value) -> int | None:
    """1–10 from a number or a Mixed In Key style comment ("8A - Energy 6"); else None."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    text = str(value)
    m = re.search(r"energy\s*[:=-]?\s*(\d+(?:\.\d+)?)", text, re.I) or re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", text)
    if not m:
        return None
    n = round(float(m.group(1)))
    return n if 1 <= n <= 10 else None


def song_id(s: Song) -> tuple[str, str]:
    """Unique identity — matches the DB's UNIQUE(track_title, artist)."""
    return (s.name, s.artist)


def song_label(s: Song | None) -> str:
    return "— None —" if s is None else f"{s.name} — {s.artist}"

# ── Vibe configuration ────────────────────────────────────────────────────────
# Adding a new vibe: add one entry here. No other code needs to change.
# energy_curve: (position 0→1 through the set, target energy 1–10) points, linearly interpolated.
VIBE_CONFIG: dict[str, dict] = {
    
    "sunset": {
        "excluded_genres": ["pop", "rap", "hip hop", "electronica", "jersey club"],
        "bpm_range": (95, 118),
        "bpm_bonus": 2,
        "genre_bonuses": {},
        "energy_curve": [(0, 4), (0.6, 6), (1, 5)],
    },
    "kick back": {
        "excluded_genres": ["rock", "rap", "hip hop"],
        "bpm_range": (120, 135),
        "bpm_bonus": 2,
        "genre_bonuses": {},
        "energy_curve": [(0, 5), (0.7, 7), (1, 6)],
    },
    "rave": {
        "excluded_genres": ["r&b", "indie pop", "latin pop", "pop"],
        "bpm_range": (125, 140),
        "bpm_bonus": 2,
        "genre_bonuses": {"techno": 2},
        "energy_curve": [(0, 7), (0.75, 9.5), (1, 8)],
    },
    "house": {
        "excluded_genres": ["rap", "hip hop", "rock"],
        "bpm_range": None,
        "bpm_bonus": 0,
        "genre_bonuses": {"house": 2},
        "energy_curve": [(0, 5.5), (0.7, 7.5), (1, 6.5)],
    },
    "poolside": {
        "excluded_genres": ["rock", "trap", "metal", "jersey club"],
        "bpm_range": None,
        "bpm_bonus": 0,
        "genre_bonuses": {"chill": 2, "tropical": 2},
        "energy_curve": [(0, 3.5), (0.6, 6), (1, 5)],
    },
}

# ── Genre normalization ───────────────────────────────────────────────────────
# Some DB rows use artist/label names as the genre field. Map them explicitly.
ARTIST_GENRE_OVERRIDES: dict[str, str] = {
    "pitbull":       "Pop",
    "travis scott":  "Hip-Hop/Rap",
    "tiesto":        "Dance/House",
    "rufus":         "Electronic",
    "pawsa":         "Dance/House",
    "demi lovato":   "Pop",
    "major lazer":   "Dance/EDM",
    "calvin harris": "Dance/House",
    "i love music":  "Dance/EDM",
}

def map_genre(raw_genre: str) -> str:
    genre = str(raw_genre or "").strip().lower()
    if genre in ARTIST_GENRE_OVERRIDES:
        return ARTIST_GENRE_OVERRIDES[genre]
    if any(k in genre for k in ["house", "deep tech", "techno", "tech house",
                                  "deep house", "afro house", "organic house", "deep sea house"]):
        return "Dance/House"
    if any(k in genre for k in ["garage", "bassline", "grime", "edm",
                                  "disco", "jersey club", "dancehall"]):
        return "Dance/EDM"
    if "dance" in genre:
        return "Dance/EDM"
    if any(k in genre for k in ["electronic", "electronica", "organic", "minimal"]):
        return "Electronic"
    if any(k in genre for k in ["hip-hop", "hip hop", "rap"]):
        return "Hip-Hop/Rap"
    if "r&b" in genre or "r & b" in genre:
        return "R&B"
    if "latin" in genre:
        return "Latin"
    if "pop" in genre or "indie" in genre:
        return "Pop"
    return "Other"


# ── Camelot wheel helpers ─────────────────────────────────────────────────────

def parse_key(k: str) -> tuple[int | None, str | None]:
    match = re.match(r"^(\d{1,2})([AB])$", str(k or "").strip().upper())
    return (int(match.group(1)), match.group(2)) if match else (None, None)


def get_harmonic_neighbors(key: str) -> list[str]:
    num, mode = parse_key(key)
    if num is None:
        return []
    return [
        f"{num}{mode}",
        f"{num}{'B' if mode == 'A' else 'A'}",
        f"{(num % 12) + 1}{mode}",
        f"{(num - 2) % 12 + 1}{mode}",
    ]


def key_compat_label(k1: str, k2: str) -> str:
    if not k1 or not k2:
        return "?"
    if k1.strip().upper() == k2.strip().upper():
        return "Same"
    if k2.strip().upper() in get_harmonic_neighbors(k1):
        return "Harmonic"
    return "Non-harmonic"


def to_camelot(raw: str) -> str:
    """Normalize a key to Camelot. Accepts Camelot ("8a") or musical notation
    ("Am", "F#m", "Bb", "Ebmaj"). Unrecognized input is returned uppercased so
    callers' parse_key() validation rejects it."""
    s = str(raw or "").strip().replace(" ", "")
    if not s:
        return ""
    num, mode = parse_key(s)
    if num is not None:
        return f"{num}{mode}"
    m = re.match(r"^([A-Ga-g])([#♯b♭]?)(m|min|minor|maj|major)?$", s)
    if not m:
        return s.upper()
    letter, acc, suffix = m.groups()
    pc = ({"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter.upper()]
          + {"#": 1, "♯": 1, "b": -1, "♭": -1}.get(acc, 0)) % 12
    minor = bool(suffix) and not suffix.startswith("maj")
    # Each fifth (+7 semitones) is one step round the wheel; Am = 8A, C = 8B.
    return f"{(7 * pc + (4 if minor else 7)) % 12 + 1}{'A' if minor else 'B'}"


# ── BPM / duration helpers ────────────────────────────────────────────────────

def effective_bpm_delta(bpm1: float, bpm2: float) -> float:
    """BPM gap a DJ actually has to bridge — counts half/double-time mixing (70 → 140 = 0)."""
    a, b = float(bpm1 or 0), float(bpm2 or 0)
    return min(abs(a - b), abs(a * 2 - b), abs(a - b * 2))


def parse_duration(value) -> float | None:
    """Seconds from a number (seconds), "m:ss" or "h:mm:ss". None if blank/invalid."""
    if value is None or (isinstance(value, float) and value != value):  # NaN
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        secs = 0.0
        for part in text.split(":"):
            secs = secs * 60 + float(part)
    except ValueError:
        return None
    return secs if secs > 0 else None


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
