import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyze import energy_scores, estimate_key, spectrum_stats, _location_path  # noqa: E402

SR = 22050


def _tones(notes: dict[str, float], seconds: float = 3.0) -> np.ndarray:
    """Sum of sine tones (plus an octave) for {note_name: weight}; A4 = 440 Hz."""
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    t = np.arange(int(SR * seconds)) / SR
    y = np.zeros_like(t)
    for name, w in notes.items():
        f = 440.0 * 2 ** ((names.index(name) - 9) / 12)   # octave 4
        y += w * (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2 * t))
    return y


# Tonic triad strong, rest of the scale weaker — like real music.
@pytest.mark.parametrize("notes,expected", [
    ({"C": 1, "E": .8, "G": .9, "D": .3, "F": .3, "A": .3, "B": .3}, "8B"),          # C major
    ({"A": 1, "C": .8, "E": .9, "B": .3, "D": .3, "F": .3, "G": .3}, "8A"),          # A minor
    ({"F#": 1, "A": .8, "C#": .9, "G#": .3, "B": .3, "D": .3, "E": .3}, "11A"),      # F# minor
    ({"D": 1, "F#": .8, "A": .9, "E": .3, "G": .3, "B": .3, "C#": .3}, "10B"),       # D major
])
def test_key_detection_on_synthetic_tones(notes, expected):
    chroma, _ = spectrum_stats(_tones(notes), SR)
    assert estimate_key(chroma) == expected


def test_centroid_rises_with_brightness():
    _, dull = spectrum_stats(_tones({"C": 1}), SR)
    _, bright = spectrum_stats(_tones({"C": 1}) + np.sin(2 * np.pi * 3000 * np.arange(3 * SR) / SR), SR)
    assert bright > dull


def test_energy_scores_rank_loud_bright_fast_highest():
    raw = [(-30 + i, 1000 + 100 * i, 100 + 3 * i) for i in range(20)]
    scores = energy_scores(raw)
    assert scores == sorted(scores) and scores[0] == 1 and scores[-1] == 10


def test_location_path_decodes_rekordbox_urls():
    assert _location_path("file://localhost/Users/me/My%20Music/a.mp3") == "/Users/me/My Music/a.mp3"


def test_refine_bpm_is_sub_frame_precise():
    from analyze import refine_bpm
    hop = 512 / 22050                                  # beat times quantized to analysis frames
    beats = np.round(np.arange(64) * (60 / 124.0) / hop) * hop
    assert abs(refine_bpm(beats) - 124.0) < 0.1
    assert refine_bpm([0.0, 0.5]) is None
