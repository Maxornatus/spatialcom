"""Construcción de la cuadrícula de análisis.

La cuadrícula es la unidad espacial de todo el análisis y, en el flujo original,
se preparaba a mano en QGIS. Generarla desde la librería elimina ese paso manual
—la fuente más común de desajustes de CRS y de extensión— y deja registrado en
la configuración con qué tamaño de celda se produjo cada corrida.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from .._logging import get_logger
from ..exceptions import GridError
from .vectors import load_layer

log = get_logger(__name__)


def make_grid(
    boundary: gpd.GeoDataFrame,
    cell_size: float,
    crs: str | None = None,
    clip: bool = True,
    min_area_fraction: float = 0.0,
    id_column: str = "cell_id",
) -> gpd.GeoDataFrame:
    """Genera una cuadrícula regular que cubre el límite indicado.

    Parameters
    ----------
    boundary:
        Capa con el área de estudio (país, cuenca, región). Se usa su envolvente
        para tender la malla y su geometría para recortar.
    cell_size:
        Lado de la celda **en las unidades del CRS de trabajo**: grados si el CRS
        es geográfico (EPSG:4326), metros si es proyectado. Un aviso lo recuerda
        cuando el valor parece incoherente con el tipo de CRS.
    crs:
        CRS de trabajo. Si se omite se usa el de `boundary`.
    clip:
        Recortar las celdas al límite. Con `False` se conservan cuadrados
        completos, incluidas las porciones fuera del área de estudio.
    min_area_fraction:
        Descarta las celdas de borde cuya área tras el recorte sea menor que esta
        fracción de una celda completa. Útil para evitar astillas costeras que
        aportan ruido al análisis.

    Returns
    -------
    GeoDataFrame indexado por `id_column`, con columnas `row`, `col` y `geometry`.
    """
    if cell_size <= 0:
        raise GridError(f"cell_size debe ser positivo, recibido {cell_size}")

    if crs is not None and str(boundary.crs) != str(crs):
        log.info("Reproyectando el límite de %s a %s.", boundary.crs, crs)
        boundary = boundary.to_crs(crs)
    target_crs = boundary.crs

    if target_crs is None:
        raise GridError("La capa de límite no tiene CRS definido.")

    geografico = target_crs.is_geographic
    if geografico and cell_size > 5:
        log.warning(
            "cell_size=%s en un CRS geográfico son %s grados (~%.0f km). "
            "¿Quería un CRS proyectado en metros?",
            cell_size, cell_size, cell_size * 111,
        )
    if not geografico and cell_size < 1:
        log.warning(
            "cell_size=%s en un CRS proyectado son %s metros. "
            "¿Quería expresarlo en grados sobre EPSG:4326?",
            cell_size, cell_size,
        )

    minx, miny, maxx, maxy = boundary.total_bounds
    # Alinear el origen a múltiplos del tamaño de celda: dos corridas sobre la
    # misma zona producen entonces exactamente la misma malla.
    minx = np.floor(minx / cell_size) * cell_size
    miny = np.floor(miny / cell_size) * cell_size

    ncols = int(np.ceil((maxx - minx) / cell_size))
    nrows = int(np.ceil((maxy - miny) / cell_size))
    total = ncols * nrows
    if total > 5_000_000:
        raise GridError(
            f"La malla tendría {total:,} celdas. Aumente cell_size o reduzca el área."
        )

    log.info("Tendiendo malla de %d x %d = %d celdas de %s.", nrows, ncols, total, cell_size)

    celdas, filas, columnas = [], [], []
    for fila in range(nrows):
        y0 = miny + fila * cell_size
        for col in range(ncols):
            x0 = minx + col * cell_size
            celdas.append(box(x0, y0, x0 + cell_size, y0 + cell_size))
            filas.append(fila)
            columnas.append(col)

    grid = gpd.GeoDataFrame(
        {"row": filas, "col": columnas}, geometry=celdas, crs=target_crs
    )

    # Conservar solo las celdas que tocan el área de estudio, usando el índice
    # espacial de la malla: sin él cada celda se compararía contra el polígono
    # completo del área de estudio.
    disuelto = boundary.geometry.union_all()
    candidatas = grid.sindex.query(disuelto, predicate="intersects")
    grid = grid.iloc[sorted(candidatas)].copy()
    log.info("Celdas que intersectan el área de estudio: %d", len(grid))

    if clip:
        # Recortar es caro contra un contorno detallado —un país tiene decenas de
        # miles de vértices—, y la inmensa mayoría de las celdas cae entera
        # dentro y no cambia al recortarse. Solo se recortan las del borde.
        interiores = set(grid.sindex.query(disuelto, predicate="contains").tolist())
        mascara_borde = ~pd.Series(
            [i in interiores for i in range(len(grid))], index=grid.index
        )
        n_borde = int(mascara_borde.sum())
        log.info(
            "Recortando %d celdas de borde; %d quedan intactas.",
            n_borde, len(grid) - n_borde,
        )
        if n_borde:
            grid.loc[mascara_borde, "geometry"] = grid.loc[
                mascara_borde, "geometry"
            ].intersection(disuelto)
        grid = grid[~grid.geometry.is_empty & grid.geometry.notna()]

    if min_area_fraction > 0:
        # Fracción del área nominal de una celda. Es una razón entre áreas
        # planares en las mismas unidades, así que es válida también en un CRS
        # geográfico, donde el área absoluta en grados no significaría nada.
        area_completa = cell_size**2
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*Geometry is in a geographic CRS.*")
            areas = grid.geometry.area
        conserva = areas >= area_completa * min_area_fraction
        descartadas = int((~conserva).sum())
        if descartadas:
            log.info(
                "Descartadas %d celdas de borde con menos del %.0f %% de área.",
                descartadas, min_area_fraction * 100,
            )
        grid = grid[conserva]

    grid = grid.reset_index(drop=True)
    grid[id_column] = range(len(grid))
    log.info("Cuadrícula final: %d celdas.", len(grid))
    return grid.set_index(id_column, drop=False)


def make_grid_from_file(
    boundary_path: str | Path,
    cell_size: float,
    crs: str | None = None,
    clip: bool = True,
    min_area_fraction: float = 0.0,
    layer: str | None = None,
) -> gpd.GeoDataFrame:
    """`make_grid` leyendo el límite desde un archivo vectorial."""
    boundary = load_layer(boundary_path, layer=layer)
    return make_grid(
        boundary,
        cell_size=cell_size,
        crs=crs,
        clip=clip,
        min_area_fraction=min_area_fraction,
    )
