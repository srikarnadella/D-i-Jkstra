import matplotlib.pyplot as plt
import networkx as nx
from pyvis.network import Network
import webbrowser

def get_node_color(genre):
    genre = (genre or "").lower()
    if "house" in genre:
        return "blue"
    elif "tech" in genre:
        return "green"
    elif "electronic" in genre:
        return "purple"
    else:
        return "gray"

def visualize_graph_interactive(graph):
    net = Network(height="900px", width="100%", bgcolor="#111111", font_color="white", heading="DJ Setlist Graph")

    for node, data in graph.nodes(data=True):
        energy = data.get('energy', 5)
        genre = data.get('genre', "")
        color = get_node_color(genre)
        size = 10 + (energy * 2)
        net.add_node(node, 
                     label=data['name'], 
                     title=f"{data['artist']} | {data['bpm']} BPM | {data['key']} | {genre}",
                     color=color,
                     size=size)

    for source, target, data in graph.edges(data=True):
        net.add_edge(source, target, value=max(1, 10 - data['weight']))

    html_file = "dj_setlist_graph.html"
    net.write_html(html_file)
    webbrowser.open(html_file)



def visualize_graph(graph):
    pos = nx.spring_layout(graph, k=0.15, iterations=30)

    plt.figure(figsize=(16, 16))
    node_colors = []
    for _, data in graph.nodes(data=True):
        energy = data.get('energy', 5)
        if energy >= 8:
            node_colors.append('red')  # High energy = Red
        elif energy >= 6:
            node_colors.append('orange')  # Medium = Orange
        else:
            node_colors.append('blue')  # Low = Blue

    nx.draw_networkx_nodes(graph, pos, node_color=node_colors, alpha=0.7, node_size=200)
    nx.draw_networkx_edges(graph, pos, alpha=0.2)
    nx.draw_networkx_labels(graph, pos, labels={n: d['name'] for n, d in graph.nodes(data=True)}, font_size=6)

    plt.title("DJ Setlist Graph Visualization")
    plt.axis('off')
    plt.show()
