from collections import namedtuple
import re

# ── Core type ────────────────────────────────────────────────────────────────
# Defined here (not inside any function) so pickle can find it for st.cache_data.
Song = namedtuple("Song", ["name", "artist", "genre", "bpm", "key"])

# ── Path / timing constants ───────────────────────────────────────────────────
DB_PATH = "dj_tracks.db"
TRACK_DURATION_SECONDS = 210    # assumed average track length
FIRST_SEGMENT_CAP_SECONDS = 1800  # opening segment is capped at 30 min
MID_SEGMENT_FRACTION = 0.6
LATE_SEGMENT_FRACTION = 0.4
MAX_HARMONIC_BPM_DELTA = 25     # max BPM difference for a harmonic edge
BPM_OCTAVE_DELTA = 8            # tolerance when matching half-time/double-time BPMs
SCORE_JITTER = 0.3              # random tiebreak added to vibe score

# ── Vibe configuration ────────────────────────────────────────────────────────
# Adding a new vibe: add one entry here. No other code needs to change.
VIBE_CONFIG: dict[str, dict] = {
    
    "sunset": {
        "excluded_genres": ["pop", "rap", "hip hop", "electronica", "jersey club"],
        "bpm_range": (95, 118),
        "bpm_bonus": 2,
        "genre_bonuses": {},
    },
    "kick back": {
        "excluded_genres": ["rock", "rap", "hip hop"],
        "bpm_range": (120, 135),
        "bpm_bonus": 2,
        "genre_bonuses": {},
    },
    "rave": {
        "excluded_genres": ["r&b", "indie pop", "latin pop", "pop"],
        "bpm_range": (125, 140),
        "bpm_bonus": 2,
        "genre_bonuses": {"techno": 2},
    },
    "house": {
        "excluded_genres": ["rap", "hip hop", "rock"],
        "bpm_range": None,
        "bpm_bonus": 0,
        "genre_bonuses": {"house": 2},
    },
    "poolside": {
        "excluded_genres": ["rock", "trap", "metal", "jersey club"],
        "bpm_range": None,
        "bpm_bonus": 0,
        "genre_bonuses": {"chill": 2, "tropical": 2},
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

GENRE_COLOR_MAP: dict[str, str] = {
    "Dance/House":  "deepskyblue",
    "Dance/EDM":    "lime",
    "Electronic":   "mediumpurple",
    "Hip-Hop/Rap":  "tomato",
    "R&B":          "hotpink",
    "Pop":          "orange",
    "Latin":        "gold",
    "Other":        "gray",
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
