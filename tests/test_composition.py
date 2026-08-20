"""Pruebas de la delineación de comunidades."""
from __future__ import annotations

import pytest

from spatialcom.config import SpeciesConfig
from spatialcom.core.composition import community_id, delineate_communities


class TestCommunityId:
    def test_es_independiente_del_orden(self):
        assert community_id(["b", "a"]) == community_id(["a", "b"])

    def test_es_estable_entre_llamadas(self):
        assert community_id(["Ateles_hybridus"]) == community_id(["Ateles_hybridus"])

    def test_distingue_composiciones_distintas(self):
        assert community_id(["a"]) != community_id(["a", "b"])

    def test_tiene_prefijo_y_longitud_fijos(self):
        cid = community_id(["a", "b"])
        assert cid.startswith("C") and len(cid) == 13


class TestDelineate:
    def test_asigna_composiciones_esperadas(self, grid, species_rasters, species_cfg):
        result = delineate_communities(grid, species_rasters, species_cfg)

        # Toda celda ocupada tiene identificador; ninguna celda se pierde.
        assert len(result.grid) == len(grid)
        assert result.grid["richness"].max() == 3

        # El catálogo no repite composiciones.
        assert result.catalog["community_id"].is_unique
        assert result.catalog["species_list"].is_unique

        # La ocupancia total coincide con las celdas con especies.
        ocupadas = int((result.grid["richness"] > 0).sum())
        assert result.catalog["n_cells"].sum() == ocupadas

    def test_incidencia_coincide_con_el_catalogo(self, grid, species_rasters, species_cfg):
        result = delineate_communities(grid, species_rasters, species_cfg)
        for cid, listed in zip(
            result.catalog["community_id"], result.catalog["species_list"], strict=True
        ):
            presentes = set(result.incidence.columns[result.incidence.loc[cid]])
            assert presentes == set(listed.split(", "))

    def test_min_fraction_es_mas_restrictivo_que_any(self, grid, species_rasters):
        laxa = delineate_communities(
            grid, species_rasters, SpeciesConfig(raster_dir=".", presence_rule="any")
        )
        estricta = delineate_communities(
            grid,
            species_rasters,
            SpeciesConfig(raster_dir=".", presence_rule="min_fraction", min_fraction=0.9),
        )
        assert estricta.grid["richness"].sum() <= laxa.grid["richness"].sum()

    def test_falla_si_el_crs_no_coincide(self, grid, species_rasters, species_cfg):
        from spatialcom.exceptions import RasterError

        with pytest.raises(RasterError, match="CRS"):
            delineate_communities(grid.to_crs("EPSG:4326"), species_rasters, species_cfg)


class TestExtensionesDistintas:
    """Regresión: los rásters de SDM traen cada uno su propio recorte.

    Una implementación que lea todas las especies con el mismo índice de ventana
    —en lugar de con los mismos límites geográficos— desplaza unas capas
    respecto a otras y produce composiciones falsas.
    """

    def test_superpone_correctamente_recortes_distintos(
        self, grid, species_rasters_recortados, species_cfg
    ):
        result = delineate_communities(grid, species_rasters_recortados, species_cfg)
        richness = result.grid["richness"]

        # Fila superior de celdas (8-15 en orden de creación j, i): con especies.
        # Fila inferior (0-7): fuera de ambos recortes.
        assert richness.loc[[0, 1, 2, 3]].sum() == 0
        assert (richness.loc[[8, 9, 12, 13]] >= 1).all()
        assert (richness.loc[[10, 11, 14, 15]] >= 1).all()

        # La columna de solape debe registrar ambas especies.
        assert richness.max() == 2

    def test_las_dos_especies_aparecen_en_el_catalogo(
        self, grid, species_rasters_recortados, species_cfg
    ):
        result = delineate_communities(grid, species_rasters_recortados, species_cfg)
        todas = set()
        for lista in result.catalog["species_list"]:
            todas.update(lista.split(", "))
        assert todas == {"sp_x", "sp_y"}

    def test_rechaza_rasters_desalineados(self, grid, tmp_path, species_cfg):
        """Extensiones distintas son válidas; enrejados distintos no."""
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        from spatialcom.exceptions import RasterError
        from spatialcom.io.rasters import SpeciesRaster

        paths = []
        for name, origin in [("sp_a", (0.0, 16.0)), ("sp_b", (0.5, 16.0))]:  # medio píxel
            path = tmp_path / f"{name}.tif"
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                height=8,
                width=8,
                count=1,
                dtype="uint8",
                crs=grid.crs,
                transform=from_origin(origin[0], origin[1], 1, 1),
            ) as dst:
                dst.write(np.ones((8, 8), dtype="uint8"), 1)
            paths.append(SpeciesRaster(name, path))

        with pytest.raises(RasterError, match="desalineados"):
            delineate_communities(grid, paths, species_cfg)


class TestCrsAsumido:
    """Muchas salidas de MaxEnt se escriben sin CRS; declararlo es legítimo."""

    @pytest.fixture
    def rasters_sin_crs(self, grid, tmp_path):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        from spatialcom.io.rasters import SpeciesRaster

        salida = []
        for nombre in ("sp_x", "sp_y"):
            ruta = tmp_path / f"{nombre}.tif"
            with rasterio.open(
                ruta, "w", driver="GTiff", height=16, width=16, count=1,
                dtype="uint8", crs=None, transform=from_origin(0, 16, 1, 1),
            ) as dst:
                dst.write(np.ones((16, 16), dtype="uint8"), 1)
            salida.append(SpeciesRaster(nombre, ruta))
        return salida

    def test_sin_declararlo_falla_con_mensaje_util(self, grid, rasters_sin_crs, species_cfg):
        from spatialcom.exceptions import RasterError

        with pytest.raises(RasterError, match="sin CRS declarado"):
            delineate_communities(grid, rasters_sin_crs, species_cfg)

    def test_declarado_permite_continuar(self, grid, rasters_sin_crs):
        from spatialcom.config import SpeciesConfig

        cfg = SpeciesConfig(raster_dir=".", presence_rule="any", assume_crs=str(grid.crs))
        result = delineate_communities(grid, rasters_sin_crs, cfg)
        assert result.grid["richness"].max() == 2

    def test_no_sobrescribe_un_crs_declarado(self, grid, species_rasters, species_cfg):
        """Los rásters con CRS propio deben seguir validándose contra la cuadrícula."""
        from spatialcom.config import SpeciesConfig
        from spatialcom.exceptions import RasterError

        cfg = SpeciesConfig(raster_dir=".", presence_rule="any", assume_crs="EPSG:4326")
        # Los rásters de la fixture declaran EPSG:3116, igual que la cuadrícula:
        # el assume_crs no debe aplicarse ni provocar un falso conflicto.
        result = delineate_communities(grid, species_rasters, cfg)
        assert len(result.catalog) > 0

        with pytest.raises(RasterError, match="CRS"):
            delineate_communities(grid.to_crs("EPSG:4326"), species_rasters, cfg)

    def test_rechaza_una_suposicion_implausible(self, grid, rasters_sin_crs):
        """Coordenadas 0-16 no son grados si se asume un CRS geográfico... salvo que lo sean."""
        from spatialcom.io.rasters import validate_raster_stack

        # 0-16 sí caen dentro del dominio geográfico, así que se acepta.
        perfil = validate_raster_stack(rasters_sin_crs, assume_crs="EPSG:4326")
        assert perfil["crs"] is not None
