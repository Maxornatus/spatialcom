"""Pruebas de la generación de cuadrícula y del inventario de datos."""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from spatialcom.diagnostics import inventory, is_runnable
from spatialcom.exceptions import GridError
from spatialcom.io.grid import make_grid

CRS = "EPSG:3116"


@pytest.fixture
def limite():
    """Área de estudio cuadrada de 10 x 10 unidades."""
    return gpd.GeoDataFrame(geometry=[box(0, 0, 10, 10)], crs=CRS)


@pytest.fixture
def limite_diagonal():
    """Triángulo: la mitad de las celdas quedan cortadas por la hipotenusa."""
    return gpd.GeoDataFrame(
        geometry=[Polygon([(0, 0), (10, 0), (0, 10)])], crs=CRS
    )


class TestMakeGrid:
    def test_cubre_el_area_con_el_numero_esperado_de_celdas(self, limite):
        grid = make_grid(limite, cell_size=2)
        assert len(grid) == 25          # 5 x 5
        assert grid.crs == limite.crs
        assert set(grid.columns) >= {"row", "col", "cell_id", "geometry"}

    def test_identificadores_unicos_y_consecutivos(self, limite):
        grid = make_grid(limite, cell_size=2)
        assert grid["cell_id"].is_unique
        assert list(grid["cell_id"]) == list(range(len(grid)))
        assert grid.index.name == "cell_id"

    def test_el_origen_se_alinea_a_multiplos_del_tamano(self, limite):
        """Dos corridas sobre la misma zona deben dar exactamente la misma malla."""
        desplazado = gpd.GeoDataFrame(geometry=[box(0.3, 0.3, 10, 10)], crs=CRS)
        a = make_grid(limite, cell_size=2, clip=False)
        b = make_grid(desplazado, cell_size=2, clip=False)
        esquinas_a = {(round(g.bounds[0], 6), round(g.bounds[1], 6)) for g in a.geometry}
        esquinas_b = {(round(g.bounds[0], 6), round(g.bounds[1], 6)) for g in b.geometry}
        assert esquinas_b <= esquinas_a

    def test_recorta_las_celdas_de_borde(self, limite_diagonal):
        recortada = make_grid(limite_diagonal, cell_size=2, clip=True)
        completa = make_grid(limite_diagonal, cell_size=2, clip=False)
        assert recortada.geometry.area.sum() < completa.geometry.area.sum()
        # Ninguna celda recortada sobresale del área de estudio.
        area_estudio = limite_diagonal.geometry.iloc[0]
        assert recortada.geometry.apply(lambda g: g.within(area_estudio.buffer(1e-9))).all()

    def test_sin_recorte_las_celdas_siguen_siendo_cuadradas(self, limite_diagonal):
        grid = make_grid(limite_diagonal, cell_size=2, clip=False)
        areas = grid.geometry.area.round(6).unique()
        assert len(areas) == 1 and areas[0] == pytest.approx(4.0)

    def test_min_area_fraction_descarta_astillas(self, limite_diagonal):
        todas = make_grid(limite_diagonal, cell_size=2, clip=True)
        filtrada = make_grid(limite_diagonal, cell_size=2, clip=True, min_area_fraction=0.5)
        assert len(filtrada) < len(todas)
        assert (filtrada.geometry.area >= 4 * 0.5 - 1e-9).all()

    def test_celdas_interiores_no_se_alteran_al_recortar(self, limite):
        """Solo se recortan las de borde; las interiores deben quedar intactas."""
        grid = make_grid(limite, cell_size=2, clip=True)
        assert grid.geometry.area.round(6).unique().tolist() == [4.0]

    def test_rechaza_tamano_no_positivo(self, limite):
        with pytest.raises(GridError, match="positivo"):
            make_grid(limite, cell_size=0)

    def test_rechaza_limite_sin_crs(self):
        sin_crs = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)])
        with pytest.raises(GridError, match="CRS"):
            make_grid(sin_crs, cell_size=0.5)

    def test_rechaza_mallas_desmesuradas(self, limite):
        with pytest.raises(GridError, match="celdas"):
            make_grid(limite, cell_size=0.001)

    def test_reproyecta_al_crs_indicado(self, limite):
        grid = make_grid(limite, cell_size=2, crs="EPSG:4326")
        assert grid.crs.to_epsg() == 4326


class TestInventario:
    def test_detecta_los_insumos_completos(self, grid, species_rasters, tmp_path):
        from spatialcom.config import Config

        ruta_grid = tmp_path / "cuadricula.gpkg"
        grid.reset_index(drop=True).to_file(ruta_grid, driver="GPKG")

        cfg = Config.from_dict(
            {
                "grid": {"path": str(ruta_grid)},
                "species": {"raster_dir": str(species_rasters[0].path.parent)},
                "output": {"dir": str(tmp_path / "out")},
            },
            base_dir=tmp_path,
        )
        informe = inventory(cfg)

        estados = dict(zip(informe["dataset"], informe["estado"], strict=True))
        assert estados["cuadrícula"] == "ok"
        assert estados["rásters de especie"] == "ok"
        assert estados["alineación de rásters"] == "ok"
        assert is_runnable(informe)

    def test_reporta_la_cuadricula_faltante_en_vez_de_reventar(self, species_rasters, tmp_path):
        """`check` debe informar de lo que falta, no fallar al cargar la configuración."""
        from spatialcom.config import Config

        cfg = Config.from_dict(
            {
                "grid": {"path": str(tmp_path / "inexistente.gpkg")},
                "species": {"raster_dir": str(species_rasters[0].path.parent)},
                "output": {"dir": str(tmp_path / "out")},
            },
            base_dir=tmp_path,
            validate_paths=False,
        )
        informe = inventory(cfg)
        fila = informe[informe["dataset"] == "cuadrícula"].iloc[0]

        assert fila["estado"] == "falta"
        assert not is_runnable(informe)

    def test_con_validacion_de_rutas_la_carga_si_falla(self, species_rasters, tmp_path):
        from spatialcom.config import Config, ConfigError

        with pytest.raises(ConfigError, match="Cuadrícula no encontrada"):
            Config.from_dict(
                {
                    "grid": {"path": str(tmp_path / "inexistente.gpkg")},
                    "species": {"raster_dir": str(species_rasters[0].path.parent)},
                },
                base_dir=tmp_path,
            )

    def test_las_capas_opcionales_ausentes_son_aviso_no_error(
        self, grid, species_rasters, tmp_path
    ):
        from spatialcom.config import Config

        ruta_grid = tmp_path / "cuadricula.gpkg"
        grid.reset_index(drop=True).to_file(ruta_grid, driver="GPKG")

        cfg = Config.from_dict(
            {
                "grid": {"path": str(ruta_grid)},
                "species": {"raster_dir": str(species_rasters[0].path.parent)},
                "output": {"dir": str(tmp_path / "out")},
            },
            base_dir=tmp_path,
        )
        informe = inventory(cfg)
        opcionales = informe[informe["obligatorio"] == "opcional"]

        assert not opcionales.empty
        assert (opcionales["estado"] == "aviso").all()
        assert is_runnable(informe)   # las opcionales no bloquean
