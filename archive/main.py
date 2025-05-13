from legacydata.load_songs import load_songs_from_excel
from dj_graph import DJSetlistGraph
from visualize_graph import visualize_graph_interactive
import os
from datetime import datetime

def get_user_filters():
    print("\n🎛️  Let's create your custom DJ set!")
    min_energy = int(input("Minimum Energy Level (1-10): ") or 0)
    min_danceability = int(input("Minimum Danceability (1-10): ") or 0)
    bpm_min = int(input("Minimum BPM (or press Enter to skip): ") or 0)
    bpm_max = int(input("Maximum BPM (or press Enter to skip): ") or 999)
    genre_filter = input("Specific Genre (or press Enter to skip): ").strip().lower()
    max_songs = int(input("How many songs do you want in the set? (ex: 30): ") or 30)

    return min_energy, min_danceability, bpm_min, bpm_max, genre_filter, max_songs

def filter_songs(songs, min_energy, min_danceability, bpm_min, bpm_max, genre_filter, max_songs):
    filtered = []
    for song in songs:
        if song.energy >= min_energy and song.danceability >= min_danceability:
            if bpm_min <= song.bpm <= bpm_max:
                if genre_filter == "" or (genre_filter in str(song.genre).lower()):
                    filtered.append(song)
    # Shuffle if you want random sampling
    filtered = filtered[:max_songs]
    return filtered

if __name__ == "__main__":
    file_path = "music_with_engineered.xlsx"
    songs = load_songs_from_excel(file_path)

    # Popup for user filters
    min_energy, min_danceability, bpm_min, bpm_max, genre_filter, max_songs = get_user_filters()

    # Apply filters
    filtered_songs = filter_songs(songs, min_energy, min_danceability, bpm_min, bpm_max, genre_filter, max_songs)

    print(f"\n🎶 Building graph with {len(filtered_songs)} filtered songs...")

    dj_graph = DJSetlistGraph()
    dj_graph.build_graph(filtered_songs)

    print(f"Graph built with {len(dj_graph.graph.nodes)} songs and {len(dj_graph.graph.edges)} transitions.")

    # Timestamp filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    graph_filename = f"dj_setlist_graph_{timestamp}.gml"

    if os.path.exists(graph_filename):
        print(f"Graph file '{graph_filename}' already exists. Skipping save.")
    else:
        dj_graph.save_graph(graph_filename)

    # Visualize smaller, smoother graph
    visualize_graph_interactive(dj_graph.graph)
