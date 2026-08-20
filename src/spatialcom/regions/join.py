"""Vinculación de celdas con regiones naturales por área de intersección máxima.

Sustituye a `vincular_regiones_naturales` del notebook. Aquel resolvía los
solapamientos múltiples iterando sobre un índice con duplicados —origen del
`KeyError` y del `TypeError` documentados en `SOLUCION_KEYERROR.md` y
`SOLUCION_TYPEERROR.md`, y de los parches aplicados por `final_fix.py` sobre el
JSON del propio notebook—. Aquí la asignación es una operación vectorizada:
`sjoin` seguido de `groupby(...).idxmax()` sobre el área de intersección, sin
bucles ni índices duplicados.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .._logging import get_logger
from ..exceptions import SchemaError
from ..io.vectors import ensure_crs

log = get_logger(__name__)


def detect_region_column(regions: gpd.GeoDataFrame, hint: str | None = None) -> str:
    """Determina la columna con el nombre de la región.

    Con `hint` explícito la valida; si no, busca una columna que contenga
    "region" y falla de forma clara cuando hay ambigüedad, en lugar de tomar
    silenciosamente la primera coincidencia.
    """
    if hint:
        if hint not in regions.columns:
            raise SchemaError(
                f"La columna de región '{hint}' no existe. Disponibles: {list(regions.columns)}"
            )
        return hint

    candidates = [c for c in regions.columns if "region" in c.lower()]
    if not candidates:
        raise SchemaError(
            "No se detectó ninguna columna de región. Indíquela con "
            f"regions.name_column. Columnas disponibles: {list(regions.columns)}"
        )
    if len(candidates) > 1:
        log.warning("Varias columnas candidatas %s; se usa '%s'.", candidates, candidates[0])
    return candidates[0]


def assign_regions(
    grid: gpd.GeoDataFrame,
    regions: gpd.GeoDataFrame,
    region_column: str | None = None,
    id_column: str = "community_id",
) -> gpd.GeoDataFrame:
    """Asigna a cada celda la región con la que comparte mayor área.

    Las celdas que no intersectan ninguna región reciben `NA`, no se descartan.
    """
    regions = ensure_crs(regions, grid.crs, "regiones naturales")
    region_column = detect_region_column(regions, region_column)

    left = grid[["geometry"]].copy()
    left["_cell"] = grid.index
    right = regions[[region_column, "geometry"]].copy()
    right["_region"] = range(len(right))

    # `sjoin` hereda el índice de la cuadrícula y lo repite una vez por región
    # intersectada. `reset_index(drop=True)` lo sustituye por uno posicional
    # único: sin él, el `.loc[...idxmax()]` de más abajo recuperaría *todas* las
    # filas que comparten cada etiqueta en lugar de una sola, y la cuadrícula
    # saldría con más filas de las que entró.
    pairs = gpd.sjoin(left, right, how="inner", predicate="intersects").reset_index(drop=True)
    if pairs.empty:
        log.warning("Ninguna celda intersecta las regiones; revise extensiones y CRS.")
        out = grid.copy()
        out[region_column] = pd.NA
        return out

    # Área real de solape para cada par celda-región.
    region_geoms = regions.geometry.to_numpy()
    pairs["_area"] = [
        cell.intersection(region_geoms[ridx]).area
        for cell, ridx in zip(
            pairs.geometry.to_numpy(), pairs["index_right"].to_numpy(), strict=True
        )
    ]

    best = pairs.loc[pairs.groupby("_cell")["_area"].idxmax(), ["_cell", region_column, "_area"]]
    best = best.set_index("_cell").rename(columns={"_area": "region_overlap_area"})
    if best.index.has_duplicates:  # invariante: una región por celda
        raise RuntimeError("La asignación de regiones produjo celdas duplicadas.")

    out = grid.join(best)
    if len(out) != len(grid):
        raise RuntimeError(
            f"La asignación de regiones alteró el número de celdas: {len(grid)} -> {len(out)}."
        )
    matched = int(out[region_column].notna().sum())
    log.info(
        "Celdas asignadas a una región: %d de %d (%.1f%%).",
        matched,
        len(out),
        100 * matched / max(len(out), 1),
    )
    out.attrs["region_column"] = region_column
    return out


def cluster_region_crosstab(
    grid: gpd.GeoDataFrame,
    labels: pd.Series,
    region_column: str,
    id_column: str = "community_id",
) -> pd.DataFrame:
    """Tabla región x cluster con el número de celdas de cada combinación."""
    subset = grid[[id_column, region_column]].dropna(subset=[id_column, region_column]).copy()
    subset["cluster"] = subset[id_column].map(labels)
    subset = subset.dropna(subset=["cluster"])

    table = pd.crosstab(subset[region_column], subset["cluster"].astype(int))
    table.columns = [f"cluster_{c}" for c in table.columns]
    table["cells_total"] = table.sum(axis=1)
    table["clusters_present"] = (table.drop(columns="cells_total") > 0).sum(axis=1)
    return table.sort_values("cells_total", ascending=False)


def dominant_cluster_by_region(
    regions: gpd.GeoDataFrame,
    crosstab: pd.DataFrame,
    region_column: str,
) -> gpd.GeoDataFrame:
    """Añade a la capa de regiones el cluster mayoritario y su proporción."""
    cluster_cols = [c for c in crosstab.columns if c.startswith("cluster_")]
    dominant = crosstab[cluster_cols].idxmax(axis=1).str.replace("cluster_", "").astype(int)
    share = crosstab[cluster_cols].max(axis=1) / crosstab["cells_total"]

    summary = pd.DataFrame(
        {
            "dominant_cluster": dominant,
            "dominant_share": share.round(3),
            "cells_total": crosstab["cells_total"],
            "clusters_present": crosstab["clusters_present"],
        }
    )
    return regions.merge(summary, left_on=region_column, right_index=True, how="left")
