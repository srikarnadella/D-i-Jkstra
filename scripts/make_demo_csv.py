"""Generate demo_tracks.csv — a fictional library for fresh clones / public demos.
Run: python scripts/make_demo_csv.py   (deterministic; titles/artists are made-up combos)."""
import csv
import random

GENRES = {  # genre: (bpm_lo, bpm_hi, weight)
    "House": (120, 128, 5), "Tech House": (124, 130, 4), "Deep House": (118, 124, 3),
    "Techno": (128, 140, 3), "Afro House": (118, 124, 2), "Tropical House": (100, 118, 2),
    "Chill": (90, 110, 2), "Dance/EDM": (124, 132, 3), "Pop": (100, 128, 3),
    "Hip-Hop/Rap": (85, 105, 2), "R&B": (80, 100, 2), "Latin": (92, 106, 2),
}
ADJ = ["Velvet", "Neon", "Midnight", "Golden", "Hollow", "Electric", "Slow", "Paper", "Crimson", "Glass",
       "Lunar", "Silent", "Burning", "Distant", "Fading", "Cobalt", "Amber", "Static", "Wild", "Quiet"]
NOUN = ["Static", "Tide", "Skyline", "Garden", "Signal", "Mirage", "Echo", "Harbor", "Pulse", "Orbit",
        "Fever", "Canyon", "Lights", "Engine", "Bloom", "Drift", "Circuit", "Horizon", "Rain", "Ritual"]
FIRST = ["Nova", "Kai", "Mira", "Juno", "Rafa", "Sol", "Ivy", "Teo", "Lena", "Ezra", "Zuri", "Milo"]
LAST = ["Kline", "Vega", "Okafor", "Strand", "Lund", "Reyes", "Moss", "Hart", "Adler", "Park"]
KEYS = [f"{n}{m}" for n in range(1, 13) for m in "AB"]



def fake_rows(n: int, seed: int = 2026) -> list[list]:
    """n unique fictional [title, artist, bpm, key, genre, duration] rows. Titles get a
    "(Mix N)" suffix once the plain combinations run out, so any n works."""
    rng = random.Random(seed)
    rows, seen = [], set()
    genres, weights = zip(*[(g, w) for g, (_, _, w) in GENRES.items()])
    while len(rows) < n:
        g = rng.choices(genres, weights)[0]
        lo, hi, _ = GENRES[g]
        title = f"{rng.choice(ADJ)} {rng.choice(NOUN)}"
        if n > 2000:
            title += f" (Mix {rng.randint(1, n // 1000 + 1)})"
        artist = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if (title, artist) in seen:
            continue
        seen.add((title, artist))
        rows.append([title, artist, round(rng.uniform(lo, hi), 1), rng.choice(KEYS), g, rng.randint(170, 420)])
    return rows


if __name__ == "__main__":
    rows = fake_rows(150)
    with open("demo_tracks.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Title", "Artist", "BPM", "Key", "Genre", "Duration"])
        w.writerows(rows)
    print(f"wrote {len(rows)} tracks")
