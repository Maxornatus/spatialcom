"""Carga y validación de capas vectoriales."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from .._logging import get_logger
from ..exceptions import CRSMismatchError, GridError

log = get_logger(__name__)


def load_layer(path: str | Path, layer: str | None = None) -> gpd.GeoDataFrame:
    """Lee una capa vectorial y exige un CRS definido."""
    path = Path(path)
    gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    if gdf.crs is None:
        raise CRSMismatchError(
            f"La capa {path.name} no tiene CRS definido. Asígnelo antes de continuar "
            "(el análisis espacial sin CRS produce resultados silenciosamente erróneos)."
        )
    log.info("Capa cargada: %s (%d geometrías, CRS %s)", path.name, len(gdf), gdf.crs)
    return gdf


def load_grid(
    path: str | Path,
    id_column: str = "cell_id",
    target_crs: str | None = None,
    layer: str | None = None,
) -> gpd.GeoDataFrame:
    """Carga la cuadrícula de análisis garantizando un identificador estable.

    El notebook original dependía del índice posicional de `GeoDataFrame`, que
    cambia con cualquier filtrado. Aquí se materializa un `cell_id` persistente.
    """
    grid = load_layer(path, layer=layer)

    if not (grid.geom_type.isin({"Polygon", "MultiPolygon"})).all():
        raise GridError("La cuadrícula debe contener únicamente polígonos.")

    invalid = ~grid.geometry.is_valid
    if invalid.any():
        log.warning("Reparando %d geometrías inválidas de la cuadrícula.", int(invalid.sum()))
        grid.loc[invalid, "geometry"] = grid.loc[invalid, "geometry"].buffer(0)

    if id_column not in grid.columns:
        log.info("Generando columna de identificador '%s'.", id_column)
        grid[id_column] = range(len(grid))
    elif grid[id_column].duplicated().any():
        raise GridError(f"La columna '{id_column}' contiene identificadores duplicados.")

    if target_crs is not None and str(grid.crs) != str(target_crs):
        log.info("Reproyectando cuadrícula de %s a %s.", grid.crs, target_crs)
        grid = grid.to_crs(target_crs)

    return grid.set_index(id_column, drop=False)


def ensure_crs(gdf: gpd.GeoDataFrame, target_crs, name: str = "capa") -> gpd.GeoDataFrame:
    """Reproyecta si hace falta; falla si la capa no tiene CRS."""
    if gdf.crs is None:
        raise CRSMismatchError(f"{name} no tiene CRS definido.")
    if str(gdf.crs) == str(target_crs):
        return gdf
    log.info("Reproyectando %s: %s -> %s", name, gdf.crs, target_crs)
    return gdf.to_crs(target_crs)
