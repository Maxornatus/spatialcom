"""Mapa de calor de incidencia comunidad x especie.

El dendrograma resume la estructura pero esconde su origen: no deja ver qué
especies producen cada agrupación. El mapa de calor, con las filas en el orden
de las hojas del dendrograma, muestra la matriz que el clustering realmente
usó y hace visibles los bloques de coocurrencia.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import pdist

from .._logging import get_logger
from ..cluster.hierarchical import ClusterResult
from .theme import cluster_colors, italic_binomial

log = get_logger(__name__)


def _orden_especies(incidence: pd.DataFrame, modo: str, metric: str) -> list[str]:
    """Orden de las columnas del mapa de calor."""
    if modo == "prevalence":
        return incidence.sum(axis=0).sort_values(ascending=False).index.tolist()
    if modo == "alphabetic":
        return sorted(incidence.columns)
    if modo == "cluster":
        matriz = incidence.to_numpy(dtype=bool).T
        # Una especie presente en todas o en ninguna comunidad no tiene
        # distancia definida con ninguna otra: se aparta y se añade al final.
        variables = matriz.any(axis=1) & ~matriz.all(axis=1)
        if variables.sum() < 3:
            return incidence.columns.tolist()
        d = np.nan_to_num(pdist(matriz[variables], metric=metric), nan=1.0)
        orden = leaves_list(linkage(d, method="average"))
        nombres = np.array(incidence.columns)
        return list(nombres[variables][orden]) + list(nombres[~variables])
    raise ValueError(f"Orden de especies desconocido: {modo}")


def plot_incidence_heatmap(
    incidence: pd.DataFrame,
    result: ClusterResult,
    weights: pd.Series | None = None,
    order_species: str = "cluster",
    figsize: tuple[float, float] = (11, 8),
    show_cluster_strip: bool = True,
    max_species_labels: int = 60,
):
    """Matriz de presencia/ausencia con las filas ordenadas por el dendrograma.

    Cada fila es una comunidad y cada columna una especie. Las celdas presentes
    se colorean con el color del grupo al que pertenece la comunidad, de modo
    que los bloques del clustering se leen directamente sobre la matriz.

    Parameters
    ----------
    incidence:
        Matriz booleana comunidad x especie.
    result:
        Salida de `cluster_communities`; aporta el orden de las hojas y las
        etiquetas de grupo.
    weights:
        Extensión de cada comunidad. Si se aporta, se añade una barra lateral
        con el número de celdas: sin ella, una comunidad de 2 celdas ocupa en la
        figura lo mismo que una de 954.
    order_species:
        `cluster` (agrupa especies que coocurren), `prevalence` o `alphabetic`.
    """
    orden_filas = leaves_list(result.linkage_matrix)
    filas = result.labels.index[orden_filas]

    columnas = _orden_especies(incidence, order_species, result.metric)
    matriz = incidence.loc[filas, columnas].to_numpy(dtype=bool)
    etiquetas = result.labels.loc[filas].to_numpy()

    grupos = sorted(pd.unique(etiquetas))
    colores = dict(zip(grupos, cluster_colors(len(grupos)), strict=True))

    # Cada presencia se pinta con el color del grupo de su fila: 0 = ausencia.
    codigos = np.zeros(matriz.shape, dtype=int)
    for i, g in enumerate(etiquetas):
        codigos[i] = np.where(matriz[i], grupos.index(g) + 1, 0)

    cmap = ListedColormap(["#f2f4f6"] + [colores[g] for g in grupos])

    anchos = [0.04, 1.0, 0.10] if weights is not None else [0.04, 1.0]
    if not show_cluster_strip:
        anchos = anchos[1:]

    fig, axes = plt.subplots(
        1, len(anchos), figsize=figsize,
        gridspec_kw={"width_ratios": anchos, "wspace": 0.02},
    )
    axes = np.atleast_1d(axes)
    idx = 0

    # --- franja de grupo ---
    if show_cluster_strip:
        ax_strip = axes[idx]
        idx += 1
        franja = np.array([[grupos.index(g) + 1] for g in etiquetas])
        ax_strip.imshow(franja, aspect="auto", cmap=cmap, vmin=0, vmax=len(grupos),
                        interpolation="nearest")
        ax_strip.set_xticks([])
        ax_strip.set_yticks([])
        ax_strip.set_ylabel(f"Comunidades (n = {len(filas)})", fontsize=10)
        for lado in ax_strip.spines.values():
            lado.set_visible(False)

    # --- matriz ---
    ax = axes[idx]
    idx += 1
    ax.imshow(codigos, aspect="auto", cmap=cmap, vmin=0, vmax=len(grupos),
              interpolation="nearest")
    ax.set_yticks([])

    if len(columnas) <= max_species_labels:
        ax.set_xticks(range(len(columnas)))
        ax.set_xticklabels([italic_binomial(c) for c in columnas],
                           rotation=90, fontsize=8)
    else:
        ax.set_xticks([])
        ax.set_xlabel(f"{len(columnas)} especies", fontsize=10)
    ax.grid(False)
    for lado in ax.spines.values():
        lado.set_visible(False)

    # Separadores entre grupos consecutivos.
    cambios = np.flatnonzero(etiquetas[1:] != etiquetas[:-1]) + 0.5
    for c in cambios:
        ax.axhline(c, color="#ffffff", linewidth=1.4)

    # --- barra de extensión ---
    if weights is not None:
        ax_w = axes[idx]
        valores = weights.reindex(filas).fillna(0).to_numpy(dtype="float64")
        ax_w.barh(np.arange(len(filas)), valores,
                  color=[colores[g] for g in etiquetas], height=1.0)
        ax_w.set_ylim(len(filas) - 0.5, -0.5)
        ax_w.set_yticks([])
        ax_w.set_xlabel("celdas", fontsize=9)
        ax_w.tick_params(labelsize=8)
        ax_w.grid(axis="y", visible=False)
        for lado in ("top", "right", "left"):
            ax_w.spines[lado].set_visible(False)

    handles = [
        Line2D([], [], marker="s", linestyle="", markersize=9, color=colores[g],
               label=f"Grupo {g}")
        for g in grupos
    ]
    fig.legend(handles=handles, loc="upper center", ncol=len(grupos),
               frameon=False, fontsize=9, bbox_to_anchor=(0.5, 1.02))
    fig.suptitle(
        f"Incidencia por comunidad ({result.method.upper()}, "
        f"{result.metric}, k = {result.k})",
        y=1.07, fontsize=12, fontweight="bold",
    )
    return fig, axes
