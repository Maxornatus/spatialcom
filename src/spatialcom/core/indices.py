"""Índices derivados de la composición de comunidades.

Generaliza dos análisis que en el proyecto original vivían en notebooks
separados (`analisis_vectores.ipynb`, `dilu_fa/dilucion.ipynb`):

* `point_exposure_index`: exposición de cada comunidad a un conjunto de
  ocurrencias puntuales (vectores de fiebre amarilla: *Aedes*, *Haemagogus*,
  *Sabethes*).
* `trait_weighted_index`: índice de dilución/amplificación a partir de una
  tabla de rasgos por especie.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from .._logging import get_logger
from ..io.vectors import ensure_crs
from ..io.writers import require_columns

log = get_logger(__name__)


def richness_summary(catalog: pd.DataFrame) -> pd.DataFrame:
    """Estadísticos descriptivos de riqueza y extensión del conjunto de comunidades."""
    require_columns(catalog, ["richness", "n_cells"], "catálogo")
    return pd.DataFrame(
        {
            "n_communities": [len(catalog)],
            "cells_total": [int(catalog["n_cells"].sum())],
            "richness_min": [int(catalog["richness"].min())],
            "richness_max": [int(catalog["richness"].max())],
            "richness_mean": [float(catalog["richness"].mean())],
            "richness_weighted_mean": [
                float(np.average(catalog["richness"], weights=catalog["n_cells"]))
            ],
        }
    )


def point_exposure_index(
    points: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    id_column: str = "community_id",
    lon_column: str = "LON",
    lat_column: str = "LAT",
    group_column: str | None = "GENERO",
    points_crs: str = "EPSG:4326",
) -> pd.DataFrame:
    """Cuenta ocurrencias puntuales por comunidad y normaliza por extensión.

    Returns
    -------
    DataFrame con, por comunidad: conteo total de puntos, conteo por grupo
    (si `group_column`), densidad por celda y densidad por km2.
    """
    require_columns(points, [lon_column, lat_column], "tabla de ocurrencias")

    gdf_points = gpd.GeoDataFrame(
        points.copy(),
        geometry=gpd.points_from_xy(points[lon_column], points[lat_column]),
        crs=points_crs,
    )
    gdf_points = ensure_crs(gdf_points, grid.crs, "ocurrencias")

    joined = gpd.sjoin(
        gdf_points, grid[[id_column, "geometry"]], how="inner", predicate="within"
    )
    joined = joined.dropna(subset=[id_column])
    log.info("Ocurrencias asignadas a una comunidad: %d de %d", len(joined), len(gdf_points))

    total = joined.groupby(id_column).size().rename("points_total")
    frames = [total]

    if group_column and group_column in joined.columns:
        by_group = (
            pd.crosstab(joined[id_column], joined[group_column])
            .add_prefix("points_")
            .rename(columns=str.lower)
        )
        frames.append(by_group)

    result = pd.concat(frames, axis=1).fillna(0).astype(int).reset_index()

    extent = grid.dropna(subset=[id_column]).groupby(id_column).agg(
        n_cells=(id_column, "size"), area_m2=("geometry", lambda s: s.area.sum())
    )
    result = result.merge(extent.reset_index(), on=id_column, how="left")
    result["points_per_cell"] = result["points_total"] / result["n_cells"]
    result["points_per_km2"] = result["points_total"] / (result["area_m2"] / 1e6)

    return result


def trait_weighted_index(
    incidence: pd.DataFrame,
    traits: pd.DataFrame,
    trait_column: str,
    species_column: str = "species",
    normalize: bool = True,
) -> pd.Series:
    """Índice por comunidad como suma de un rasgo sobre las especies presentes.

    Con `trait_column` = competencia de hospedero, valores altos indican
    amplificación y valores bajos dilución. `normalize=True` divide por la
    riqueza, dando la competencia media de la comunidad en lugar del total.
    """
    require_columns(traits, [species_column, trait_column], "tabla de rasgos")

    weights = traits.set_index(species_column)[trait_column]
    missing = [sp for sp in incidence.columns if sp not in weights.index]
    if missing:
        log.warning("Especies sin rasgo definido (peso 0): %s", ", ".join(missing))

    aligned = weights.reindex(incidence.columns).fillna(0.0).to_numpy()
    matrix = incidence.to_numpy(dtype="float64")
    total = matrix @ aligned

    if normalize:
        richness = matrix.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            total = np.where(richness > 0, total / richness, 0.0)

    return pd.Series(total, index=incidence.index, name=trait_column + "_index")
