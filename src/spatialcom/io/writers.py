"""Escritura de resultados con formato seguro y esquema explícito."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from .._logging import get_logger

log = get_logger(__name__)

_SHP_FIELD_LIMIT = 10


def write_vector(
    gdf: gpd.GeoDataFrame,
    path: str | Path,
    fmt: str = "gpkg",
    layer: str | None = None,
    overwrite: bool = True,
) -> Path:
    """Escribe una capa vectorial.

    `fmt='shp'` avisa de los campos que DBF truncará a 10 caracteres. Ese truncado
    silencioso es el origen de `cell_deforested_pixels -> cell_defor` y
    `nivel_defor -> nivel_defo` en el flujo original, donde el código posterior
    leía unas veces el nombre largo y otras el truncado.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Ya existe y overwrite=False: {path}")

    # La cuadrícula lleva su identificador a la vez como índice y como columna
    # (ver `io.load_grid`). Los drivers vectoriales materializan el índice con
    # `reset_index(drop=False)`, lo que colisionaría con la columna homónima.
    if gdf.index.name is not None and gdf.index.name in gdf.columns:
        gdf = gdf.reset_index(drop=True)

    fmt = fmt.lower()
    if fmt == "gpkg":
        gdf.to_file(path.with_suffix(".gpkg"), layer=layer or path.stem, driver="GPKG")
        out = path.with_suffix(".gpkg")
    elif fmt == "parquet":
        gdf.to_parquet(path.with_suffix(".parquet"), index=False)
        out = path.with_suffix(".parquet")
    elif fmt == "shp":
        long_fields = [c for c in gdf.columns if len(c) > _SHP_FIELD_LIMIT and c != "geometry"]
        if long_fields:
            log.warning(
                "Shapefile truncará estos campos a 10 caracteres: %s. "
                "Use vector_format='gpkg' para evitarlo.",
                ", ".join(long_fields),
            )
        gdf.to_file(path.with_suffix(".shp"))
        out = path.with_suffix(".shp")
    else:
        raise ValueError(f"Formato vectorial no soportado: {fmt}")

    log.info("Capa escrita: %s (%d filas)", out.name, len(gdf))
    return out


def write_table(df: pd.DataFrame, path: str | Path, index: bool = False) -> Path:
    """Escribe una tabla en CSV UTF-8 (o Parquet si la extensión lo indica)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        df.to_parquet(path, index=index)
    else:
        df.to_csv(path, index=index, encoding="utf-8")
    log.info("Tabla escrita: %s (%d filas x %d columnas)", path.name, len(df), df.shape[1])
    return path


def require_columns(df: pd.DataFrame, columns: list[str], context: str) -> None:
    """Valida el esquema de una tabla antes de operar sobre ella."""
    from ..exceptions import SchemaError

    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise SchemaError(
            f"{context}: faltan las columnas {missing}. Disponibles: {list(df.columns)}"
        )
