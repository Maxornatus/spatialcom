"""Pruebas de la vinculación con regiones naturales."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from spatialcom.exceptions import SchemaError
from spatialcom.regions.join import (
    assign_regions,
    cluster_region_crosstab,
    detect_region_column,
    dominant_cluster_by_region,
)


@pytest.fixture
def regiones(grid):
    """Dos regiones que se solapan sobre la banda central de la cuadrícula.

    El solape es deliberado: es la situación que hacía fallar la
    implementación original y la que debe resolverse por área máxima.
    """
    return gpd.GeoDataFrame(
        {"Subregion": ["oeste", "este"]},
        geometry=[box(0, 0, 10, 16), box(6, 0, 16, 16)],
        crs=grid.crs,
    )


class TestDeteccionDeColumna:
    def test_detecta_subregion(self, regiones):
        assert detect_region_column(regiones) == "Subregion"

    def test_falla_si_no_hay_candidata(self, grid):
        sin_region = gpd.GeoDataFrame({"nombre": ["a"]}, geometry=[box(0, 0, 1, 1)], crs=grid.crs)
        with pytest.raises(SchemaError, match="columna de región"):
            detect_region_column(sin_region)

    def test_valida_el_nombre_indicado(self, regiones):
        with pytest.raises(SchemaError, match="no existe"):
            detect_region_column(regiones, "inexistente")


class TestAsignacion:
    def test_no_duplica_celdas_con_regiones_solapadas(self, grid, regiones):
        """Regresión: el solape múltiple inflaba la cuadrícula de salida."""
        out = assign_regions(grid, regiones)
        assert len(out) == len(grid)
        assert not out.index.has_duplicates

    def test_asigna_la_region_de_mayor_solape(self, grid, regiones):
        out = assign_regions(grid, regiones)
        # Celda 0 = box(0,0,4,4): solo cae en 'oeste'.
        assert out.loc[0, "Subregion"] == "oeste"
        # Celda 3 = box(12,0,16,4): solo cae en 'este'.
        assert out.loc[3, "Subregion"] == "este"
        # Celda 2 = box(8,0,12,4): solapa 2 unidades con oeste y 4 con este.
        assert out.loc[2, "Subregion"] == "este"

    def test_celdas_sin_region_quedan_nulas_sin_perderse(self, grid):
        lejos = gpd.GeoDataFrame(
            {"Subregion": ["otra"]}, geometry=[box(100, 100, 110, 110)], crs=grid.crs
        )
        out = assign_regions(grid, lejos)
        assert len(out) == len(grid)
        assert out["Subregion"].isna().all()


class TestTablas:
    def test_crosstab_y_cluster_dominante(self, grid, regiones):
        g = assign_regions(grid, regiones)
        g["community_id"] = ["C1"] * 8 + ["C2"] * 8
        labels = pd.Series({"C1": 1, "C2": 2})

        tabla = cluster_region_crosstab(g, labels, "Subregion")
        assert tabla["cells_total"].sum() == len(g)

        dominante = dominant_cluster_by_region(regiones, tabla, "Subregion")
        assert len(dominante) == len(regiones)
        assert dominante["dominant_share"].between(0, 1).all()
