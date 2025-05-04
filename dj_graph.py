import networkx as nx
from math import fabs
from song import Song

class DJSetlistGraph:
    def __init__(self):
        self.graph = nx.DiGraph()

    def add_song(self, song: Song):
        self.graph.add_node(song.song_id, 
                        name=song.name,
                        artist=song.artist,
                        bpm=song.bpm,
                        key=song.key,
                        energy=song.energy,
                        danceability=song.danceability,
                        genre=song.genre,
                        duration=song.duration)


    def add_transition(self, song1_id, song2_id, weight):
        self.graph.add_edge(song1_id, song2_id, weight=weight)

    def calculate_penalty(self, song1: Song, song2: Song):
        bpm_penalty = fabs(song1.bpm - song2.bpm) / 2
        key_penalty = 10
        if song1.key == song2.key:
            key_penalty = 0
        elif self.is_compatible_key(song1.key, song2.key):
            key_penalty = 2

        energy_penalty = fabs(song1.energy - song2.energy)
        danceability_penalty = fabs(song1.danceability - song2.danceability) / 2

        total_penalty = bpm_penalty + key_penalty + energy_penalty + danceability_penalty
        return total_penalty

    def is_compatible_key(self, key1, key2):
        try:
            num1, letter1 = int(key1[:-1]), key1[-1]
            num2, letter2 = int(key2[:-1]), key2[-1]
            if num1 == num2:
                return True
            if abs(num1 - num2) == 1 or abs(num1 - num2) == 11:
                return True
            if letter1 != letter2:
                return True
        except:
            return False
        return False

    def build_graph(self, songs):
        for song in songs:
            self.add_song(song)

        for i, song1 in enumerate(songs):
            for j, song2 in enumerate(songs):
                if i != j:
                    penalty = self.calculate_penalty(song1, song2)
                    self.add_transition(song1.song_id, song2.song_id, penalty)

    def save_graph(self, filename="dj_setlist_graph.gml"):
        nx.write_gml(self.graph, filename)
