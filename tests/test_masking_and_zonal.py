"""Pruebas de exclusión de celdas, recuento y clasificación de perturbación."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from spatialcom.config import DeforestationConfig
from spatialcom.core.masking import apply_exclusion_mask, filter_by_species, recount_communities
from spatialcom.core.zonal import classify_disturbance_levels


@pytest.fixture
def grid_con_comunidades(grid):
    g = grid.copy()
    g["community_id"] = ["C1"] * 8 + ["C2"] * 8
    return g


class TestExclusion:
    def test_marca_y_anula_solo_las_celdas_afectadas(self, grid_con_comunidades):
        mask = gpd.GeoDataFrame(
            geometry=[box(0, 0, 4, 4)], crs=grid_con_comunidades.crs
        )
        out = apply_exclusion_mask(grid_con_comunidades, mask)

        assert len(out) == len(grid_con_comunidades)  # no se pierden filas
        assert out["excluded"].sum() >= 1
        assert out.loc[out["excluded"], "community_id"].isna().all()
        assert out.loc[~out["excluded"], "community_id"].notna().all()

    def test_recuento_elimina_comunidades_sin_celdas(self, grid_con_comunidades):
        catalog = pd.DataFrame(
            {
                "community_id": ["C1", "C2", "C3"],
                "species_list": ["a", "b", "c"],
                "richness": [1, 1, 1],
                "n_cells": [8, 8, 5],
            }
        )
        _, updated = recount_communities(grid_con_comunidades, catalog)
        assert set(updated["community_id"]) == {"C1", "C2"}
        assert updated.set_index("community_id").loc["C1", "n_cells"] == 8


class TestFiltroEspecie:
    def test_no_confunde_epitetos_parciales(self):
        catalog = pd.DataFrame(
            {
                "community_id": ["C1", "C2"],
                "species_list": ["Cebus_albifrons", "Cebus_albifrons_versicolor"],
            }
        )
        out = filter_by_species(catalog, "Cebus_albifrons")
        assert list(out["community_id"]) == ["C1"]


class TestNiveles:
    def test_clasifica_segun_los_bordes_configurados(self, grid):
        g = grid.copy()
        g["cell_pixels_total"] = 100
        g["cell_pixels_disturbed"] = [0, 5, 20, 40, 60, 90] + [0] * 10

        out = classify_disturbance_levels(g, DeforestationConfig())
        niveles = out["disturbance_level"].tolist()[:6]
        assert niveles == [0, 1, 2, 3, 4, 5]

    def test_celdas_sin_pixeles_quedan_en_nivel_cero(self, grid):
        g = grid.copy()
        g["cell_pixels_total"] = 0
        g["cell_pixels_disturbed"] = 0
        out = classify_disturbance_levels(g, DeforestationConfig())
        assert (out["disturbance_level"] == 0).all()


class TestEscritura:
    def test_escribe_cuadricula_con_id_en_indice_y_columna(self, grid, tmp_path):
        """`load_grid` deja el identificador duplicado como índice y columna."""
        from spatialcom.io.writers import write_vector

        assert grid.index.name in grid.columns  # precondición de load_grid
        out = write_vector(grid, tmp_path / "capa", fmt="gpkg")
        assert out.exists()

        vuelta = gpd.read_file(out)
        assert len(vuelta) == len(grid)
        assert list(vuelta.columns).count("cell_id") == 1
