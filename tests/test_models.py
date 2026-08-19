import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import parse_key, get_harmonic_neighbors, key_compat_label, map_genre


# ── parse_key ─────────────────────────────────────────────────────────────────

class TestParseKey:
    def test_valid_minor(self):
        assert parse_key("8A") == (8, "A")

    def test_valid_major(self):
        assert parse_key("12B") == (12, "B")

    def test_single_digit(self):
        assert parse_key("1A") == (1, "A")

    def test_lowercase_normalized(self):
        assert parse_key("8a") == (8, "A")

    def test_whitespace_stripped(self):
        assert parse_key("  3B  ") == (3, "B")

    def test_empty_string(self):
        assert parse_key("") == (None, None)

    def test_none_input(self):
        assert parse_key(None) == (None, None)

    def test_invalid_format(self):
        assert parse_key("C#") == (None, None)

    def test_out_of_range_still_parses(self):
        # parse_key only checks regex, not Camelot range 1-12
        assert parse_key("13A") == (13, "A")

    def test_zero_parses_but_is_out_of_camelot_range(self):
        # parse_key only validates format (regex), not Camelot range 1-12
        assert parse_key("0A") == (0, "A")


# ── get_harmonic_neighbors ────────────────────────────────────────────────────

class TestGetHarmonicNeighbors:
    def test_same_key_included(self):
        assert "8A" in get_harmonic_neighbors("8A")

    def test_relative_mode(self):
        # 8A's relative major is 8B
        assert "8B" in get_harmonic_neighbors("8A")

    def test_plus_one_same_mode(self):
        # 8A → 9A (step up)
        assert "9A" in get_harmonic_neighbors("8A")

    def test_minus_one_same_mode(self):
        # 8A → 7A (step down: (8-2)%12+1 = 7)
        assert "7A" in get_harmonic_neighbors("8A")

    def test_wrap_at_12_up(self):
        # 12A → 1A (wraps: (12%12)+1 = 1)
        assert "1A" in get_harmonic_neighbors("12A")

    def test_wrap_at_1_down(self):
        # 1A → 12A (wraps: (1-2)%12+1 = 12)
        assert "12A" in get_harmonic_neighbors("1A")

    def test_invalid_key_returns_empty(self):
        assert get_harmonic_neighbors("") == []
        assert get_harmonic_neighbors("C#") == []

    def test_returns_four_neighbors(self):
        assert len(get_harmonic_neighbors("5B")) == 4


# ── key_compat_label ──────────────────────────────────────────────────────────

class TestKeyCompatLabel:
    def test_same_key(self):
        assert key_compat_label("8A", "8A") == "Same"

    def test_harmonic_relative(self):
        assert key_compat_label("8A", "8B") == "Harmonic"

    def test_harmonic_step_up(self):
        assert key_compat_label("8A", "9A") == "Harmonic"

    def test_non_harmonic(self):
        assert key_compat_label("1A", "6B") == "Non-harmonic"

    def test_empty_key_returns_unknown(self):
        assert key_compat_label("", "8A") == "?"
        assert key_compat_label("8A", "") == "?"

    def test_case_insensitive(self):
        assert key_compat_label("8a", "8A") == "Same"


# ── map_genre ─────────────────────────────────────────────────────────────────

class TestMapGenre:
    def test_house_variants(self):
        for raw in ["deep house", "tech house", "afro house", "techno"]:
            assert map_genre(raw) == "Dance/House", f"Failed for: {raw}"

    def test_edm_variants(self):
        for raw in ["edm", "jersey club", "disco", "garage"]:
            assert map_genre(raw) == "Dance/EDM", f"Failed for: {raw}"

    def test_hip_hop(self):
        assert map_genre("hip hop") == "Hip-Hop/Rap"
        assert map_genre("hip-hop") == "Hip-Hop/Rap"
        assert map_genre("rap") == "Hip-Hop/Rap"

    def test_artist_override(self):
        assert map_genre("pitbull") == "Pop"
        assert map_genre("tiesto") == "Dance/House"

    def test_unknown_returns_other(self):
        assert map_genre("zydeco") == "Other"
        assert map_genre("") == "Other"

    def test_case_insensitive(self):
        assert map_genre("HOUSE") == "Dance/House"
        assert map_genre("Pop") == "Pop"
