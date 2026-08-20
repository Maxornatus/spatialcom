"""Dendrograma y diagnósticos del clustering."""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import dendrogram, set_link_color_palette

from ..cluster.hierarchical import ClusterResult
from .theme import cluster_colors


def plot_dendrogram(
    result: ClusterResult,
    labels: list[str] | None = None,
    figsize: tuple[float, float] = (14, 7),
    truncate_at: int | None = None,
):
    """Dendrograma con los grupos coloreados según el corte seleccionado.

    Parameters
    ----------
    result:
        Salida de `cluster_communities`.
    labels:
        Etiquetas de hoja. Con más de ~60 comunidades conviene omitirlas o usar
        `truncate_at`: el dendrograma del notebook rotulaba cada hoja con su
        GUID completo, ilegible en la figura final.
    truncate_at:
        Si se indica, muestra solo los `p` últimos nodos fusionados.
    """
    set_link_color_palette(cluster_colors(result.k))

    fig, ax = plt.subplots(figsize=figsize)
    heights = result.linkage_matrix[:, 2]
    cut = heights[-(result.k - 1)] if result.k > 1 else heights[-1]

    kwargs = dict(
        Z=result.linkage_matrix,
        ax=ax,
        color_threshold=cut,
        above_threshold_color="0.6",
        leaf_rotation=90,
        leaf_font_size=7,
    )
    if truncate_at:
        kwargs.update(truncate_mode="lastp", p=truncate_at, show_contracted=True)
    elif labels is not None:
        kwargs["labels"] = labels
    else:
        kwargs["no_labels"] = True

    dendrogram(**kwargs)
    ax.axhline(cut, color="0.3", linestyle="--", linewidth=0.8)
    ax.set_ylabel(f"Distancia de {result.metric.capitalize()}")
    ax.set_xlabel(f"Comunidades (n = {len(result.labels)})")
    ax.set_title(
        f"Clustering jerárquico ({result.method.upper()}), k = {result.k}, "
        f"r cofenética = {result.cophenetic_r:.2f}"
    )
    ax.grid(axis="x", visible=False)
    set_link_color_palette(None)
    return fig, ax


def plot_k_diagnostics(result: ClusterResult, figsize: tuple[float, float] = (6, 4)):
    """Curva de silueta frente a k, con el valor elegido resaltado."""
    fig, ax = plt.subplots(figsize=figsize)
    d = result.diagnostics
    ax.plot(d["k"], d["silhouette"], marker="o", color="#0072B2")
    ax.axvline(result.k, color="#D55E00", linestyle="--", linewidth=1)
    ax.set_xlabel("Número de grupos (k)")
    ax.set_ylabel("Silueta media")
    ax.set_title("Selección del número de grupos")
    ax.set_xticks(d["k"])
    return fig, ax


def plot_ordination(
    ordination,
    labels,
    figsize: tuple[float, float] = (7, 6),
    sizes=None,
):
    """Dispersión de las comunidades en el espacio de ordenación, por cluster."""
    coords = ordination.coords
    unique = sorted(np.unique(labels))
    colors = cluster_colors(len(unique))

    fig, ax = plt.subplots(figsize=figsize)
    for color, group in zip(colors, unique, strict=True):
        sel = labels == group
        ax.scatter(
            coords.loc[sel, 0],
            coords.loc[sel, 1],
            s=(sizes[sel] if sizes is not None else 40),
            c=color,
            alpha=0.8,
            edgecolor="white",
            linewidth=0.5,
            label=f"Grupo {group}",
        )
    ax.set_xlabel(ordination.axis_label(0))
    ax.set_ylabel(ordination.axis_label(1))
    ax.legend(title="Cluster", loc="best")
    ax.set_title("Ordenación de comunidades por composición")
    return fig, ax
