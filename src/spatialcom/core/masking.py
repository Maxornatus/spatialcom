"""Exclusión de celdas (zonas urbanas u otras) y recálculo de ocupancia.

Unifica las celdas 4 y 5 del notebook. El punto crítico corregido: en el flujo
original el dendrograma se construía sobre `composicion_especies.csv` (con
urbano) mientras la cadena de deforestación usaba
`composicion_especies_sin_urbano.csv`. Los clusters describían, por tanto, un
conjunto de comunidades distinto del que se caracterizaba. Aquí la exclusión
devuelve un único par (cuadrícula, catálogo) coherente que alimenta todo lo
demás.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from .._logging import get_logger
from ..io.vectors import ensure_crs

log = get_logger(__name__)


def apply_exclusion_mask(
    grid: gpd.GeoDataFrame,
    mask_layer: gpd.GeoDataFrame,
    id_column: str = "community_id",
    predicate: str = "intersects",
    flag_column: str = "excluded",
) -> gpd.GeoDataFrame:
    """Anula la comunidad en las celdas que intersectan la capa de exclusión.

    No borra filas: marca `excluded=True` y pone el identificador a nulo, de
    modo que la cuadrícula conserva su geometría completa y la trazabilidad de
    qué se excluyó y por qué.
    """
    mask_layer = ensure_crs(mask_layer, grid.crs, "capa de exclusión")

    hits = gpd.sjoin(
        grid[["geometry"]], mask_layer[["geometry"]], how="inner", predicate=predicate
    ).index.unique()

    out = grid.copy()
    out[flag_column] = False
    out.loc[hits, flag_column] = True
    out.loc[hits, id_column] = None

    log.info(
        "Exclusión aplicada: %d de %d celdas (%.1f%%) marcadas.",
        len(hits),
        len(out),
        100 * len(hits) / max(len(out), 1),
    )
    return out


def recount_communities(
    grid: gpd.GeoDataFrame,
    catalog: pd.DataFrame,
    id_column: str = "community_id",
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Recalcula `n_cells` tras una exclusión y descarta comunidades vacías.

    Devuelve la cuadrícula sin cambios y el catálogo filtrado y actualizado.
    Las comunidades que solo existían en celdas excluidas desaparecen.
    """
    counts = grid[id_column].value_counts()
    updated = catalog.copy()
    updated["n_cells"] = updated[id_column].map(counts).fillna(0).astype(int)

    dropped = int((updated["n_cells"] == 0).sum())
    updated = updated[updated["n_cells"] > 0].reset_index(drop=True)

    log.info(
        "Recuento actualizado: %d comunidades vigentes, %d eliminadas por quedar sin celdas.",
        len(updated),
        dropped,
    )
    return grid, updated


def filter_by_species(catalog: pd.DataFrame, species: str, column: str = "species_list"):
    """Selecciona las comunidades que contienen una especie concreta.

    Reemplaza la celda 3 del notebook. Compara sobre la lista tokenizada en
    lugar de una expresión regular sobre el texto plano, lo que elimina el
    riesgo de coincidencias parciales entre epítetos.
    """
    tokens = catalog[column].fillna("").str.split(", ")
    return catalog[tokens.apply(lambda lst: species in lst)].copy()
