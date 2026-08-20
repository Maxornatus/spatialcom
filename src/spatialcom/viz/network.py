"""Red de similitud entre comunidades.

Port de `crear_grafo_relaciones`. El umbral de similitud deja de ser un valor
mágico: `similarity_threshold=None` lo fija en el percentil indicado de la
distribución observada, de modo que la densidad del grafo sea comparable entre
conjuntos de datos distintos.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from .theme import cluster_colors


def build_similarity_graph(
    similarity: pd.DataFrame,
    labels: pd.Series,
    threshold: float | None = 0.5,
    percentile: float = 90.0,
    weights: pd.Series | None = None,
) -> nx.Graph:
    """Grafo no dirigido donde las aristas unen comunidades similares."""
    values = similarity.to_numpy(copy=True)
    np.fill_diagonal(values, 0.0)

    if threshold is None:
        threshold = float(np.percentile(values[np.triu_indices_from(values, k=1)], percentile))

    graph = nx.Graph()
    for cid in similarity.index:
        graph.add_node(
            cid,
            cluster=int(labels.get(cid, -1)),
            size=float(weights.get(cid, 1.0)) if weights is not None else 1.0,
        )

    idx = similarity.index.to_list()
    rows, cols = np.where(np.triu(values, k=1) >= threshold)
    for i, j in zip(rows, cols, strict=True):
        graph.add_edge(idx[i], idx[j], weight=float(values[i, j]))

    graph.graph["threshold"] = threshold
    return graph


def plot_similarity_graph(
    graph: nx.Graph,
    figsize: tuple[float, float] = (10, 9),
    seed: int = 42,
    max_node_size: float = 900.0,
):
    """Dibuja el grafo con disposición por fuerzas, coloreado por cluster."""
    clusters = sorted({d["cluster"] for _, d in graph.nodes(data=True)})
    palette = dict(zip(clusters, cluster_colors(len(clusters)), strict=True))

    sizes = np.array([d["size"] for _, d in graph.nodes(data=True)], dtype="float64")
    if sizes.max() > 0:
        sizes = 60 + (sizes / sizes.max()) * max_node_size

    pos = nx.spring_layout(graph, seed=seed, weight="weight")
    fig, ax = plt.subplots(figsize=figsize)

    nx.draw_networkx_edges(graph, pos, ax=ax, alpha=0.25, width=0.6, edge_color="0.4")
    nx.draw_networkx_nodes(
        graph,
        pos,
        ax=ax,
        node_size=sizes,
        node_color=[palette[d["cluster"]] for _, d in graph.nodes(data=True)],
        edgecolors="white",
        linewidths=0.6,
    )

    ax.set_axis_off()
    ax.set_title(
        f"Red de similitud composicional (umbral = {graph.graph['threshold']:.2f}, "
        f"{graph.number_of_edges()} aristas)"
    )
    return fig, ax
