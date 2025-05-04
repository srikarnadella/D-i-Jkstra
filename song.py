class Song:
    def __init__(self, song_id, name, artist, bpm, key, energy, danceability, genre, duration):
        self.song_id = song_id
        self.name = name
        self.artist = artist
        self.bpm = bpm
        self.key = key
        self.energy = energy
        self.danceability = danceability
        self.genre = genre
        self.duration = duration

    def __str__(self):
        return f"{self.name} by {self.artist} ({self.bpm} BPM, {self.key})"
