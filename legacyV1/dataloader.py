import requests
import os
from dotenv import load_dotenv
import time
import pandas as pd

from songlistcleaner import process_playlist_file


spreadsheet = "songs.xlsx"
cols = ["name", "genre", "bpm", "duration", "key", "artist"]


def load_or_create_spreadsheet(filename):
    if os.path.exists(filename):
        return pd.read_excel(filename)
    else:
        return pd.DataFrame(columns=cols)
    

