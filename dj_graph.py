import networkx as nx

from models import get_harmonic_neighbors, effective_bpm_delta
from setlist_engine import _bpm_compatible


class DJSetlistGraph:
    def __init__(self):
        self.graph = nx.DiGraph()

    def add_song(self, song):
        node_id = f"{song.name}_{song.artist}"
        self.graph.add_node(
            node_id,
            name=song.name,
            artist=song.artist,
            bpm=song.bpm,
            key=song.key,
            genre=song.genre,
            energy=song.energy,
        )

    def add_transition(self, song_a, song_b):
        node_a = f"{song_a.name}_{song_a.artist}"
        node_b = f"{song_b.name}_{song_b.artist}"
        self.graph.add_edge(
            node_a,
            node_b,
            bpm_diff=round(song_b.bpm - song_a.bpm, 1),
            mix_delta=round(effective_bpm_delta(song_a.bpm, song_b.bpm), 1),  # counts half/double-time
            key_change=f"{song_a.key} → {song_b.key}"
        )

    def build_sequence(self, songs):
        """Linear path graph for an ordered setlist (node order = set order)."""
        for i, song in enumerate(songs):
            self.add_song(song)
            if i > 0:
                self.add_transition(songs[i - 1], song)
        return self.graph

    def build_harmonic_graph(self, songs):
        """Connect every pair of songs that are harmonically compatible."""
        for song in songs:
            self.add_song(song)
        for a in songs:
            for b in songs:
                if a is b:
                    continue
                if (b.key in get_harmonic_neighbors(a.key)
                        and _bpm_compatible(a.bpm, b.bpm)):
                    self.add_transition(a, b)
