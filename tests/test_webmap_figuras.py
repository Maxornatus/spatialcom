"""Pruebas de las figuras estáticas incrustadas en el mapa web."""
from __future__ import annotations

import base64

import pandas as pd
import pytest

from spatialcom.viz.webmap import FIGURE_CAPTIONS, build_webmap, collect_figures


@pytest.fixture
def datos(grid):
    g = grid.copy()
    g["community_id"] = ["C1"] * 8 + ["C2"] * 8
    g["Subregion"] = ["oeste"] * 12 + ["este"] * 4
    catalog = pd.DataFrame(
        {
            "community_id": ["C1", "C2"],
            "species_list": ["sp_a, sp_b", "sp_b, sp_c"],
            "richness": [2, 2],
            "n_cells": [8, 8],
        }
    )
    return g, catalog


SVG_MINIMO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    '<rect width="10" height="10" fill="red"/></svg>'
)


@pytest.fixture
def carpeta_figuras(tmp_path):
    """Carpeta con figuras conocidas y una desconocida."""
    d = tmp_path / "figuras"
    d.mkdir()
    for slug in ("fig_dendrograma", "fig_heatmap_incidencia", "figS_diagnostico_k"):
        (d / f"{slug}.svg").write_text(SVG_MINIMO, encoding="utf-8")
    (d / "fig_inventada.svg").write_text(SVG_MINIMO, encoding="utf-8")
    return d


class TestCollectFigures:
    def test_lee_todas_las_figuras_de_la_carpeta(self, carpeta_figuras):
        figuras = collect_figures(carpeta_figuras)
        assert len(figuras) == 4
        assert all(f["mime"] == "image/svg+xml" for f in figuras)

    def test_codifica_en_base64_recuperable(self, carpeta_figuras):
        figuras = collect_figures(carpeta_figuras)
        recuperado = base64.b64decode(figuras[0]["data"]).decode("utf-8")
        assert recuperado == SVG_MINIMO

    def test_orden_narrativo_no_alfabetico(self, carpeta_figuras):
        """Ordenar por nombre pondría la suplementaria (figS_) la primera."""
        slugs = [f["slug"] for f in collect_figures(carpeta_figuras)]
        assert slugs[0] == "fig_dendrograma"
        assert slugs[1] == "fig_heatmap_incidencia"
        # La conocida-suplementaria va antes que la desconocida, y ambas al final.
        assert slugs.index("figS_diagnostico_k") > slugs.index("fig_heatmap_incidencia")
        assert slugs[-1] == "fig_inventada"

    def test_las_conocidas_llevan_titulo_y_pie(self, carpeta_figuras):
        por_slug = {f["slug"]: f for f in collect_figures(carpeta_figuras)}
        titulo, pie = FIGURE_CAPTIONS["fig_dendrograma"]
        assert por_slug["fig_dendrograma"]["title"] == titulo
        assert por_slug["fig_dendrograma"]["caption"] == pie

    def test_las_desconocidas_reciben_titulo_derivado(self, carpeta_figuras):
        por_slug = {f["slug"]: f for f in collect_figures(carpeta_figuras)}
        assert por_slug["fig_inventada"]["title"] == "Fig inventada"
        assert por_slug["fig_inventada"]["caption"] == ""

    def test_prefiere_svg_sobre_el_png_gemelo(self, carpeta_figuras):
        """`spatialcom figures` puede dejar ambos; incrustar los dos duplicaría."""
        (carpeta_figuras / "fig_dendrograma.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        figuras = collect_figures(carpeta_figuras)

        dendro = [f for f in figuras if f["slug"] == "fig_dendrograma"]
        assert len(dendro) == 1
        assert dendro[0]["mime"] == "image/svg+xml"

    def test_carpeta_inexistente_devuelve_lista_vacia(self, tmp_path):
        assert collect_figures(tmp_path / "no_existe") == []

    def test_acepta_una_lista_de_rutas(self, carpeta_figuras):
        rutas = [carpeta_figuras / "fig_dendrograma.svg"]
        assert [f["slug"] for f in collect_figures(rutas)] == ["fig_dendrograma"]

    def test_omite_rutas_que_no_existen(self, carpeta_figuras):
        rutas = [carpeta_figuras / "fig_dendrograma.svg", carpeta_figuras / "fantasma.svg"]
        assert len(collect_figures(rutas)) == 1


class TestPestanaDeFiguras:
    def test_el_html_incluye_las_figuras(self, datos, carpeta_figuras, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "conf", figures=carpeta_figuras)
        html = out.read_text(encoding="utf-8")

        assert 'id="tab-figuras"' in html
        assert "function renderFiguras(" in html
        assert '"slug":"fig_dendrograma"' in html

    def test_sin_figuras_el_payload_queda_vacio(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "sinfig")
        assert '"figures":[]' in out.read_text(encoding="utf-8")

    def test_las_figuras_no_anaden_peticiones_externas(
        self, datos, carpeta_figuras, tmp_path
    ):
        """Van como data URI: el archivo sigue abriendo sin conexión."""
        import re

        grid, catalog = datos
        out = build_webmap(
            grid, catalog, tmp_path / "off", figures=carpeta_figuras, basemap="none"
        )
        html = out.read_text(encoding="utf-8")

        externas = [
            u for u in re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
            if "leafletjs.com" not in u
        ]
        assert externas == []

    def test_la_plantilla_avisa_que_no_reaccionan_a_los_filtros(self):
        from spatialcom.viz.webmap import _TEMPLATE

        plantilla = _TEMPLATE.read_text(encoding="utf-8")
        assert "NO reaccionan a los" in plantilla
        assert 'id="figuras-aviso"' in plantilla
