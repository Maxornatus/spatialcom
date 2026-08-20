"""Mapas temáticos de comunidades, riqueza, clusters y perturbación."""
from __future__ import annotations

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D

from .theme import cluster_colors, italic_binomial


def _basemap(ax, context: gpd.GeoDataFrame | None):
    if context is not None:
        context.plot(ax=ax, color="#f2f2f2", edgecolor="#bdbdbd", linewidth=0.4, zorder=0)


def plot_cluster_map(
    grid: gpd.GeoDataFrame,
    labels: pd.Series,
    id_column: str = "community_id",
    context: gpd.GeoDataFrame | None = None,
    figsize: tuple[float, float] = (8, 10),
):
    """Mapa de la cuadrícula coloreada por el cluster de su comunidad."""
    gdf = grid.copy()
    gdf["cluster"] = gdf[id_column].map(labels)

    unique = sorted(labels.unique())
    colors = dict(zip(unique, cluster_colors(len(unique)), strict=True))

    fig, ax = plt.subplots(figsize=figsize)
    _basemap(ax, context)
    gdf[gdf["cluster"].isna()].plot(ax=ax, color="#e8e8e8", linewidth=0)
    for group, color in colors.items():
        gdf[gdf["cluster"] == group].plot(ax=ax, color=color, linewidth=0)

    handles = [
        Line2D([], [], marker="s", linestyle="", markersize=9, color=c, label=f"Grupo {g}")
        for g, c in colors.items()
    ]
    ax.legend(handles=handles, title="Cluster", loc="lower left")
    ax.set_axis_off()
    ax.set_title("Distribución espacial de los grupos de comunidades")
    return fig, ax


def plot_choropleth(
    gdf: gpd.GeoDataFrame,
    column: str,
    cmap: str = "YlOrRd",
    scheme: str | None = None,
    context: gpd.GeoDataFrame | None = None,
    legend_label: str | None = None,
    figsize: tuple[float, float] = (8, 10),
):
    """Coropletas continuas: riqueza, porcentaje de pérdida, índices derivados."""
    fig, ax = plt.subplots(figsize=figsize)
    _basemap(ax, context)
    gdf.plot(
        ax=ax,
        column=column,
        cmap=cmap,
        scheme=scheme,
        linewidth=0,
        legend=True,
        legend_kwds={"label": legend_label or column, "shrink": 0.5},
        missing_kwds={"color": "#e8e8e8", "label": "sin datos"},
    )
    ax.set_axis_off()
    return fig, ax


def plot_community_panel(
    grid: gpd.GeoDataFrame,
    catalog: pd.DataFrame,
    community_ids: list[str],
    id_column: str = "community_id",
    context: gpd.GeoDataFrame | None = None,
    ncols: int = 3,
):
    """Panel con la extensión de varias comunidades y su lista de especies.

    Reemplaza `generar_graficos_top6`, que construía subgridspecs anidados y
    fijaba en el código el número de paneles. Aquí `community_ids` es un
    argumento: el llamador decide el criterio (mayor extensión, mayor riqueza,
    mayor pérdida de cobertura).
    """
    n = len(community_ids)
    nrows = -(-n // ncols)
    fig, axes = plt.subplots(nrows, ncols * 2, figsize=(5.5 * ncols, 4.2 * nrows))
    axes = axes.reshape(nrows, ncols, 2)

    lookup = catalog.set_index(id_column)

    for i, cid in enumerate(community_ids):
        r, c = divmod(i, ncols)
        ax_text, ax_map = axes[r, c]

        row = lookup.loc[cid]
        species = [italic_binomial(s) for s in str(row["species_list"]).split(", ")]
        text = "\n".join(f"· {s}" for s in species)
        ax_text.text(0.02, 0.98, text, va="top", ha="left", fontsize=9, transform=ax_text.transAxes)
        ax_text.set_title(f"S = {row['richness']} | {int(row['n_cells'])} celdas", loc="left")
        ax_text.set_axis_off()

        _basemap(ax_map, context)
        grid[grid[id_column] == cid].plot(ax=ax_map, color="#D55E00", linewidth=0)
        ax_map.set_axis_off()

    for i in range(n, nrows * ncols):
        r, c = divmod(i, ncols)
        axes[r, c, 0].set_axis_off()
        axes[r, c, 1].set_axis_off()

    fig.tight_layout()
    return fig, axes
