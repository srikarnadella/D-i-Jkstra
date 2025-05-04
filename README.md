# D-i-Jkstra
**Currently in an MVP form** <br>
I made this website to be a Graphical Representation and Interpretation of a DJ setlist. As someone who DJ's in their freetime I wanted to bridge the gap between my hobbies and CS and I after completing my DSA 2 class I had a thought about representing a setlist or a library of songs as a directed graph with each song being its own node with values such as name, bpm, key, artist, and a few engineered attributes and each edge being a representation of a transition.

I broke down this app into two key functions: Generating setlists and graphically representing a set.

1. **Generating Setlists**  
   - **Filtering**: narrow down your library by genre, BPM range, energy, danceability, and maximum number of tracks.  
   - **Dijkstra-style optimization**: treat each song as a node and edges weighted by  
     - absolute BPM difference  
     - key compatibility penalty  
     Then compute the “shortest path” through the filtered songs to produce the **smoothest possible** setlist.

2. **Graphical Visualization**  
   - **2D force-directed layout** and **3D floating view** (Plotly) to explore your set graphically.  
   - **Node size** reflects energy, **node color** reflects genre; **edge color** indicates transition quality.  
   - Rich **hover tooltips** show song name, artist, BPM, and key on demand.

Features for the future:
- Setlist building tool (accept songs as you go)
- Music finding (swipe based music finder)
