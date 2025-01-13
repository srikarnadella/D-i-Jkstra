import requests
import os
from dotenv import load_dotenv
import time
import pandas as pd


load_dotenv()
LASTFMAPIKEY = os.getenv("LASTFMAPIKEY")

spreadsheet = "songs.xlsx"
cols = ["name", "genre", "bpm", "duration", "key", "artist"]


def get_details(name, artist):
    url = "http://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "track.getInfo",
        "track": name,
        "artist": artist,
        "api_key": LASTFMAPIKEY,
        "format": "json"
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if "track" in data:
            tags = data.get("track", {}).get("toptags", {}).get("tag", [])
            genre = tags[0]["name"] if tags else "Unknown"
            return {
                "name": data["track"]["name"],
                "genre": genre,
                "bpm": 120,
                "duration": int(data["track"]["duration"]) / 60000 if data["track"]["duration"] else 0,
                "key": "Unknown",
                "artist": data["track"]["artist"]["name"]
            }
    return None


def load_or_create_spreadsheet(filename):
    if os.path.exists(filename):
        return pd.read_excel(filename)
    else:
        return pd.DataFrame(columns=cols)
    
def update_spreadsheet(songs):
    df = load_or_create_spreadsheet(spreadsheet)

    # Standardize dataframe for comparison (trim spaces, lowercase)
    df["name"] = df["name"].str.strip().str.lower()
    df["artist"] = df["artist"].str.strip().str.lower()

    for song in songs:
        song_name = song["name"].strip().lower()
        song_artist = song["artist"].strip().lower()

        # Check if song exists
        if not ((df["name"] == song_name) & (df["artist"] == song_artist)).any():
            song_details = get_details(song["name"], song["artist"])
            print(song_details)
            if song_details:
                df = pd.concat([df, pd.DataFrame([song_details])], ignore_index=True)
                print(f"Added: {song['name']} by {song['artist']}")
            else:
                print(f"Failed to fetch details for: {song['name']} by {song['artist']}")
        else:
            print(f"Song already exists: {song['name']} by {song['artist']}")

    # Save the updated DataFrame back to the spreadsheet
    df.to_excel(spreadsheet, index=False)



songs_to_add = [
    {"name": "Saving Up", "artist": "Dom Dolla"},
    {"name": "(It Goes Like) Nanana", "artist": "Peggy Gou"},
    {"name": "Take It Off", "artist": "Fischer"}

]

update_spreadsheet(songs_to_add)