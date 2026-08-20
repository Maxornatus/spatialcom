"""Datos sintéticos: un mundo de 3 especies sobre una cuadrícula 4x4.

Permite probar el paquete completo sin depender de los 300 GB de rásters del
proyecto real, que es lo que hacía imposible testear el notebook.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

CRS = "EPSG:3116"  # MAGNA-SIRGAS / Colombia Bogotá zone
CELL = 4  # píxeles por lado de celda
N = 4  # celdas por lado


@pytest.fixture
def grid() -> gpd.GeoDataFrame:
    """Cuadrícula regular de 4x4 celdas, cada una de 4x4 píxeles."""
    cells = [
        box(i * CELL, j * CELL, (i + 1) * CELL, (j + 1) * CELL)
        for j in range(N)
        for i in range(N)
    ]
    gdf = gpd.GeoDataFrame({"cell_id": range(len(cells))}, geometry=cells, crs=CRS)
    return gdf.set_index("cell_id", drop=False)


def _write_raster(path, array, origin=(0, N * CELL)):
    transform = from_origin(origin[0], origin[1], 1, 1)
    profile = dict(
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype="uint8",
        crs=CRS,
        transform=transform,
        blockxsize=16,
        blockysize=16,
        tiled=True,
    )
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype("uint8"), 1)


@pytest.fixture
def species_rasters(tmp_path):
    """Tres especies con patrones de distribución conocidos.

    sp_a ocupa la mitad izquierda, sp_b la mitad superior y sp_c una única celda
    situada en la esquina superior izquierda, donde ya coinciden a y b. Las
    composiciones esperadas son, por tanto, {a,b,c}, {a,b}, {a}, {b} y {}.
    """
    from spatialcom.io.rasters import SpeciesRaster

    size = N * CELL
    a = np.zeros((size, size), dtype="uint8")
    a[:, : size // 2] = 1

    b = np.zeros((size, size), dtype="uint8")
    b[: size // 2, :] = 1

    c = np.zeros((size, size), dtype="uint8")
    c[:CELL, :CELL] = 1  # esquina superior izquierda

    out = []
    for name, arr in [("sp_a", a), ("sp_b", b), ("sp_c", c)]:
        path = tmp_path / f"{name}_binario.tif"
        _write_raster(path, arr)
        out.append(SpeciesRaster(species=name, path=path))
    return out


@pytest.fixture
def species_cfg():
    from spatialcom.config import SpeciesConfig

    return SpeciesConfig(raster_dir=".", presence_rule="any")


@pytest.fixture
def species_rasters_recortados(tmp_path):
    """Dos especies con **extensiones distintas**, alineadas al mismo enrejado.

    Reproduce la situación real del proyecto: cada modelo de distribución viene
    recortado a su propia área. sp_x cubre el cuadrante superior izquierdo
    (celdas 8-9, 12-13) y sp_y el superior derecho (celdas 10-11, 14-15), con un
    solape de una columna de celdas.
    """
    from spatialcom.io.rasters import SpeciesRaster

    half = N * CELL // 2

    # sp_x: mitad izquierda del mundo, mitad superior. Origen (0, 16).
    x = np.ones((half, half + CELL), dtype="uint8")
    px = tmp_path / "sp_x_binario.tif"
    _write_raster(px, x, origin=(0, N * CELL))

    # sp_y: mitad derecha, mitad superior. Origen desplazado (8, 16).
    y = np.ones((half, half), dtype="uint8")
    py = tmp_path / "sp_y_binario.tif"
    _write_raster(py, y, origin=(half, N * CELL))

    return [SpeciesRaster("sp_x", px), SpeciesRaster("sp_y", py)]
