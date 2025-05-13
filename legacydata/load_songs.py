import pandas as pd
from song import Song

def load_songs_from_excel(file_path):
    df = pd.read_excel(file_path)
    songs = []

    for idx, row in df.iterrows():
        try:
            song = Song(
                song_id=idx,
                name=row['Track Title'],
                artist=row['Artist'],
                bpm=float(row['BPM']),
                key=str(row['Key']),
                energy=int(row['Energy']),
                danceability=int(row['Danceability']),
                genre=row['Genre'] if 'Genre' in row else "Unknown",
                duration=row['Time'] if 'Time' in row else "0:00"
            )
            songs.append(song)
        except Exception as e:
            print(f"Skipping row {idx} due to error: {e}")
    return songs
