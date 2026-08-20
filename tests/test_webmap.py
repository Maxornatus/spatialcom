"""Pruebas del mapa web interactivo."""
from __future__ import annotations

import json
import re

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from spatialcom.exceptions import SchemaError
from spatialcom.viz.webmap import (
    BUNDLED_LEAFLET,
    LEAFLET_VERSION,
    build_payload,
    build_webmap,
    context_geojson,
)


@pytest.fixture
def regiones_ctx(grid):
    """Capa de contorno para el modo sin teselas."""
    return gpd.GeoDataFrame(geometry=[box(0, 0, 16, 16)], crs=grid.crs)


@pytest.fixture
def datos(grid):
    """Cuatro celdas por comunidad, repartidas entre dos regiones.

    C1 ocupa 8 celdas, todas en 'oeste'. C2 ocupa 8 celdas repartidas entre
    'oeste' (4) y 'este' (4): sirve para comprobar que el conteo por región no
    atribuye a una región celdas que están en la otra.
    """
    g = grid.copy()
    g["community_id"] = ["C1"] * 8 + ["C2"] * 8
    g["Subregion"] = ["oeste"] * 12 + ["este"] * 4
    catalog = pd.DataFrame(
        {
            "community_id": ["C1", "C2"],
            "species_list": ["sp_a, sp_b", "sp_b, sp_c"],
            "richness": [2, 2],
            "n_cells": [8, 8],
            "cluster": [1, 2],
            "pct_loss_total": [3.5, 12.25],
        }
    )
    return g, catalog


class TestPayload:
    def test_estructura_basica(self, datos):
        grid, catalog = datos
        p = build_payload(grid, catalog, region_column="Subregion")

        assert p["species"] == ["sp_a", "sp_b", "sp_c"]
        assert p["regions"] == ["este", "oeste"]
        assert len(p["communities"]) == 2
        assert p["hasCluster"] and p["hasLoss"]

    def test_las_especies_se_codifican_por_indice(self, datos):
        grid, catalog = datos
        p = build_payload(grid, catalog, region_column="Subregion")
        por_id = {c["id"]: c for c in p["communities"]}

        assert por_id["C1"]["sp"] == [0, 1]  # sp_a, sp_b
        assert por_id["C2"]["sp"] == [1, 2]  # sp_b, sp_c
        assert por_id["C1"]["r"] == 2

    def test_celdas_por_segmento_no_por_comunidad(self, datos):
        """Regresión: el contador sumaba la extensión total de la comunidad."""
        grid, catalog = datos
        p = build_payload(grid, catalog, region_column="Subregion")

        idx = {c["id"]: i for i, c in enumerate(p["communities"])}
        por_segmento = {}
        for feat in p["features"]["features"]:
            cid = p["communities"][feat["properties"]["c"]]["id"]
            region = p["regions"][feat["properties"]["g"]]
            por_segmento[(cid, region)] = feat["properties"]["n"]

        assert por_segmento[("C1", "oeste")] == 8
        assert por_segmento[("C2", "oeste")] == 4
        assert por_segmento[("C2", "este")] == 4
        # La suma de segmentos reproduce la extensión total de cada comunidad.
        assert por_segmento[("C2", "oeste")] + por_segmento[("C2", "este")] == 8
        assert p["communities"][idx["C2"]]["n"] == 8

    def test_una_comunidad_en_dos_regiones_da_dos_segmentos(self, datos):
        grid, catalog = datos
        p = build_payload(grid, catalog, region_column="Subregion")
        assert len(p["features"]["features"]) == 3  # C1/oeste, C2/oeste, C2/este

    def test_registra_las_regiones_de_cada_comunidad(self, datos):
        grid, catalog = datos
        p = build_payload(grid, catalog, region_column="Subregion")
        por_id = {c["id"]: c for c in p["communities"]}
        assert por_id["C1"]["reg"] == [1]        # solo oeste
        assert por_id["C2"]["reg"] == [0, 1]     # este y oeste

    def test_sin_columna_de_region(self, datos):
        grid, catalog = datos
        p = build_payload(grid.drop(columns="Subregion"), catalog)
        assert p["regionColumn"] is None
        assert p["regions"] == ["sin región"]

    def test_redondea_las_coordenadas(self, datos):
        grid, catalog = datos
        p = build_payload(grid, catalog, region_column="Subregion", coord_precision=1)
        coords = json.dumps(p["features"]["features"][0]["geometry"])
        assert not re.search(r"\d\.\d{2,}", coords)

    def test_falla_si_falta_la_columna_de_comunidad(self, grid):
        catalog = pd.DataFrame({"community_id": ["C1"], "species_list": ["sp_a"]})
        with pytest.raises(SchemaError, match="community_id"):
            build_payload(grid, catalog)

    def test_falla_si_ninguna_celda_tiene_comunidad(self, grid, datos):
        _, catalog = datos
        g = grid.copy()
        g["community_id"] = None
        with pytest.raises(SchemaError, match="Ninguna celda"):
            build_payload(g, catalog)


class TestHtml:
    def test_escribe_un_html_autonomo(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(
            grid, catalog, tmp_path / "mapa", region_column="Subregion", title="Prueba"
        )
        assert out.suffix == ".html"
        html = out.read_text(encoding="utf-8")

        assert "<title>Prueba</title>" in html
        assert "/*__DATA__*/" not in html  # el marcador fue sustituido
        assert "/*__LEAFLET_CSS__*/" not in html
        assert '"sp_a"' in html            # los datos van embebidos

    def test_cdn_produce_enlaces_externos(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "cdn", leaflet="cdn")
        html = out.read_text(encoding="utf-8")
        assert "unpkg.com/leaflet@" + LEAFLET_VERSION in html
        assert "L.Icon" not in html        # el código no va embebido

    def test_leaflet_propio_se_incrusta(self, datos, tmp_path):
        grid, catalog = datos
        assets = tmp_path / "leaflet"
        assets.mkdir()
        (assets / "leaflet.css").write_text(".leaflet-marcador{}", encoding="utf-8")
        (assets / "leaflet.js").write_text("var LEAFLET_LOCAL=1;", encoding="utf-8")

        out = build_webmap(grid, catalog, tmp_path / "propio", leaflet=assets)
        html = out.read_text(encoding="utf-8")

        assert "LEAFLET_LOCAL" in html
        assert "unpkg.com" not in html

    def test_falla_si_faltan_los_assets_locales(self, datos, tmp_path):
        grid, catalog = datos
        vacio = tmp_path / "vacio"
        vacio.mkdir()
        with pytest.raises(FileNotFoundError, match="leaflet"):
            build_webmap(grid, catalog, tmp_path / "x", leaflet=vacio)


class TestOffline:
    """El mapa debe abrir y renderizarse sin ninguna petición de red."""

    def test_la_copia_incluida_existe_y_esta_completa(self):
        assert (BUNDLED_LEAFLET / "leaflet.js").exists()
        assert (BUNDLED_LEAFLET / "leaflet.css").exists()
        assert (BUNDLED_LEAFLET / "LICENSE").exists()
        for img in ("layers.png", "layers-2x.png", "marker-icon.png"):
            assert (BUNDLED_LEAFLET / "images" / img).exists()

    def test_bundled_no_deja_referencias_externas(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(
            grid, catalog, tmp_path / "off", region_column="Subregion", basemap="none"
        )
        html = out.read_text(encoding="utf-8")

        assert "unpkg.com" not in html
        assert "cartocdn" not in html
        assert "tile.openstreetmap" not in html
        # Ninguna URL http(s) fuera de los enlaces de atribución/licencia.
        externas = [
            u for u in re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
            if "leafletjs.com" not in u and "openstreetmap.org/copyright" not in u
        ]
        assert externas == []

    def test_las_imagenes_del_css_quedan_como_data_uri(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "off2")
        html = out.read_text(encoding="utf-8")
        assert "url(images/" not in html
        assert "url(data:image/png;base64," in html

    def test_sin_source_map_colgante(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "off3")
        assert "sourceMappingURL" not in out.read_text(encoding="utf-8")

    def test_capa_de_contexto_embebida(self, datos, tmp_path, regiones_ctx):
        grid, catalog = datos
        out = build_webmap(
            grid, catalog, tmp_path / "ctx", basemap="none", context=regiones_ctx
        )
        html = out.read_text(encoding="utf-8")
        assert '"context":{"type":"FeatureCollection"' in html

    def test_sin_contexto_el_campo_queda_nulo(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "noctx")
        assert '"context":null' in out.read_text(encoding="utf-8")


class TestContexto:
    def test_reproyecta_y_simplifica(self, regiones_ctx):
        fc = context_geojson(regiones_ctx, simplify_tolerance=0.01, coord_precision=2)
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 1
        coords = json.dumps(fc["features"][0]["geometry"])
        assert not re.search(r"\d\.\d{3,}", coords)

    def test_none_devuelve_none(self):
        assert context_geojson(None) is None

    def test_capa_vacia_devuelve_none(self, grid):
        vacia = gpd.GeoDataFrame(geometry=[], crs=grid.crs)
        assert context_geojson(vacia) is None


class TestAtribucion:
    def test_la_plantilla_no_anade_atribucion_propia(self):
        """Leaflet ya rotula su prefijo; añadirlo otra vez daba 'Leaflet | Leaflet'.

        Se comprueba sobre la plantilla, no sobre el HTML final: el propio
        Leaflet define `addAttribution` como método de su API y aparecería
        siempre en el archivo generado.
        """
        from spatialcom.viz.webmap import _TEMPLATE

        assert "attributionControl" not in _TEMPLATE.read_text(encoding="utf-8")
