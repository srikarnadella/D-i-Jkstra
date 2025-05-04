class SongNode:
    idcounter = 1

    def __init__(self, name, genre, bpm, duration, key, artist=None, tags=None):
        self.id = "n" + str(SongNode.idcounter)
        SongNode.idcounter += 1

        self.name = name
        self.genre = genre
        self.bpm = bpm
        self.duration = duration
        self.key = key
        self.artist = artist if artist else "Unknown Artist"
        self.tags = tags if tags else []

    def __str__(self):
        return f"Song ID: {self.id}\n" \
               f"Name: {self.name}\n" \
               f"Artist: {self.artist}\n" \
               f"Genre: {self.genre}\n" \
               f"BPM: {self.bpm}\n" \
               f"Duration: {self.duration} minutes\n" \
               f"Key: {self.key}\n" \
               f"Tags: {', '.join(self.tags)}"