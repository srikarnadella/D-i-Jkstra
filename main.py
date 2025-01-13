from songnode import SongNode
from songedge import SongEdge
from songedge import TransitionType
import networkx as nx
import requests
import os
from dotenv import load_dotenv
import time


'''
Test Code: 
song1 = SongNode(name="Song 1", genre="House", bpm=128, duration=5, key="C Major", artist="DJ A", tags=["Party", "Mainstage"])
song2 = SongNode(name="Song 2", genre="Techno", bpm=130, duration=6, key="D Minor", artist="DJ B", tags=["Chill", "Afterparty"])

edge = SongEdge(transition_type=TransitionType.SMOOTH, notes="Gradual build-up", source=song1, destination=song2)

print(song1)
print(song2)
print(edge)
'''

G = nx.DiGraph()
