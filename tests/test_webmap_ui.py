"""Pruebas estructurales de la plantilla del mapa web.

La plantilla es HTML+JS generado desde Python, así que no hay comprobador de
tipos que atrape un identificador mal escrito. Estas pruebas cubren los errores
que sí se pueden detectar estáticamente: `$("id")` que no corresponde a ningún
elemento, marcadores de sustitución sin reemplazar y controles ausentes.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

from spatialcom.viz.webmap import _TEMPLATE, build_webmap


@pytest.fixture
def datos(grid):
    """Dos comunidades sobre dos regiones (igual que en test_webmap)."""
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


@pytest.fixture
def plantilla() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


class TestIntegridadDeLaPlantilla:
    def test_todo_id_usado_en_js_existe_en_el_html(self, plantilla):
        usados = set(re.findall(r'\$\("([a-z0-9-]+)"\)', plantilla))
        definidos = set(re.findall(r'id="([a-z0-9-]+)"', plantilla))
        assert usados, "no se detectó ningún uso de $(...)"
        assert usados <= definidos, f"ids sin elemento: {sorted(usados - definidos)}"

    def test_los_contenedores_de_graficas_existen(self, plantilla):
        for elemento in ("chart-riqueza", "chart-area", "sub-riqueza", "sub-area",
                         "filtros-activos", "charts"):
            assert f'id="{elemento}"' in plantilla

    def test_los_controles_de_descarga_existen(self, plantilla):
        assert 'id="export-png"' in plantilla
        assert 'id="export-scale"' in plantilla
        assert 'data-chart="riqueza"' in plantilla
        assert 'data-chart="area"' in plantilla

    def test_las_pestanas_existen(self, plantilla):
        assert 'id="tab-mapa"' in plantilla
        assert 'id="tab-graficas"' in plantilla

    def test_las_funciones_clave_estan_definidas(self, plantilla):
        for fn in ("renderCharts", "exportMapPNG", "activarPestana", "filterSummary",
                   "etiquetasComparativas", "barChartSvg", "descargar", "svgToPng"):
            assert f"function {fn}(" in plantilla, f"falta {fn}"

    def test_la_descarga_no_depende_de_la_red(self, plantilla):
        """El PNG se compone en un canvas local, sin servicios de render."""
        assert "toBlob" in plantilla
        assert "createObjectURL" in plantilla
        assert "fetch(" not in plantilla


class TestHtmlGenerado:
    def test_incluye_graficas_y_exportacion(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "ui", region_column="Subregion")
        html = out.read_text(encoding="utf-8")

        assert 'id="chart-riqueza"' in html
        assert "function exportMapPNG(" in html
        assert "function renderCharts(" in html

    def test_sin_marcadores_sin_sustituir(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "ui2")
        html = out.read_text(encoding="utf-8")

        for marcador in ("__TITLE__", "__SUBTITLE__", "/*__DATA__*/",
                         "/*__LEAFLET_CSS__*/", "/*__LEAFLET_JS__*/"):
            assert marcador not in html, f"marcador sin sustituir: {marcador}"


class TestEtiquetasComparativas:
    """El algoritmo de etiquetas replicado en Python, para fijar su contrato.

    Las comunidades más ricas comparten casi siempre el mismo núcleo de especies
    generalistas; rotular cada barra con ese núcleo no distingue nada. La
    plantilla extrae el núcleo común y rotula cada barra con lo que añade.
    """

    @staticmethod
    def nucleo(composiciones: list[list[str]]) -> list[str]:
        nucleo = list(composiciones[0])
        for comp in composiciones:
            nucleo = [sp for sp in nucleo if sp in comp]
        return nucleo

    def test_extrae_el_nucleo_compartido(self):
        comps = [["a", "b", "c"], ["a", "b", "d"], ["a", "b", "e"]]
        assert self.nucleo(comps) == ["a", "b"]

    def test_las_diferencias_distinguen_cada_comunidad(self):
        comps = [["a", "b", "c"], ["a", "b", "d"], ["a", "b", "e"]]
        nucleo = self.nucleo(comps)
        propias = [[sp for sp in c if sp not in nucleo] for c in comps]
        assert propias == [["c"], ["d"], ["e"]]
        assert len({tuple(p) for p in propias}) == len(comps)  # todas distintas

    def test_sin_nucleo_no_hay_prefijo_repetido(self):
        comps = [["a"], ["b"], ["c"]]
        assert self.nucleo(comps) == []


class TestComunidadesSinCluster:
    """Regresión: `cluster.min_cells` deja comunidades con `k` nulo.

    El filtro de cluster las descartaba en silencio, de modo que el mapa se
    abría mostrando solo una fracción de los datos. Con 196 especies y
    `min_cells: 2` eran 6.128 de 7.010 comunidades invisibles por omisión.
    """

    def test_la_plantilla_define_la_categoria_sin_cluster(self, plantilla):
        assert "const SIN_CLUSTER" in plantilla
        assert "claveCluster" in plantilla
        assert "Sin grupo asignado" in plantilla

    def test_el_filtro_usa_la_clave_y_no_el_valor_crudo(self, plantilla):
        """`state.clusters.has(com.k)` con k nulo devolvía siempre false."""
        assert "state.clusters.has(claveCluster(com))" in plantilla
        assert "state.clusters.has(com.k)" not in plantilla

    def test_el_estado_inicial_incluye_las_sin_cluster(self, plantilla):
        assert "clusters: new Set(clavesCluster)" in plantilla

    def test_el_reset_las_vuelve_a_marcar(self, plantilla):
        assert "clavesCluster.forEach(k => state.clusters.add(k))" in plantilla

    def test_el_payload_admite_cluster_nulo(self, grid, tmp_path):
        """Una comunidad sin cluster debe llegar al mapa con `k` nulo, no ausente."""
        import pandas as pd

        from spatialcom.viz.webmap import build_payload

        g = grid.copy()
        g["community_id"] = ["C1"] * 8 + ["C2"] * 8
        catalog = pd.DataFrame(
            {
                "community_id": ["C1", "C2"],
                "species_list": ["sp_a", "sp_b"],
                "richness": [1, 1],
                "n_cells": [8, 8],
                "cluster": [1, float("nan")],   # C2 excluida por min_cells
            }
        )
        payload = build_payload(g, catalog)
        por_id = {c["id"]: c for c in payload["communities"]}

        assert por_id["C1"]["k"] == 1
        assert por_id["C2"]["k"] is None

    def test_el_rango_de_riqueza_se_muestra_al_usuario(self, plantilla):
        """El mínimo del control es el mínimo observado; conviene decirlo.

        Sin ese aviso, un control que no baja de 8 se lee como un filtro activo
        en lugar de como el límite real de los datos.
        """
        assert 'id="r-hint"' in plantilla
        assert "rango observado en los datos" in plantilla


class TestTablaDeComunidades:
    """Cuarta pestaña: la tabla comparte filtros con el mapa y añade el suyo."""

    def test_la_pestana_y_sus_controles_existen(self, plantilla):
        for elemento in ("tab-tabla", "tabla", "t-min", "t-buscar", "t-csv",
                         "t-cabecera", "t-cuerpo", "t-cuenta"):
            assert f'id="{elemento}"' in plantilla

    def test_las_funciones_de_tabla_estan_definidas(self, plantilla):
        for fn in ("renderTabla", "filasDeLaTabla", "tablaCsv"):
            assert f"function {fn}(" in plantilla, f"falta {fn}"

    def test_excluye_por_omision_las_de_una_sola_celda(self, plantilla):
        """El valor por defecto del control debe ser 2, no 1."""
        assert 'id="t-min" min="1" step="1" value="2"' in plantilla
        assert "minCeldas: 2" in plantilla

    def test_filtra_sobre_las_comunidades_visibles(self, plantilla):
        """Debe partir de `visibles`, no del catálogo completo: así respeta
        los filtros de especie, región, cluster y riqueza del panel."""
        assert "visibles.filter(f => f.cells >= tablaEstado.minCeldas)" in plantilla

    def test_se_refresca_al_cambiar_los_filtros(self, plantilla):
        assert '$("tabla").classList.contains("active")) renderTabla()' in plantilla

    def test_las_columnas_esperadas_estan_declaradas(self, plantilla):
        for clave in ("riqueza", "celdas", "total", "cluster", "perdida",
                      "region", "especies", "id"):
            assert f'clave: "{clave}"' in plantilla

    def test_el_csv_lleva_bom_para_excel(self, plantilla):
        """Sin BOM, Excel lee el CSV como ANSI y rompe los acentos."""
        assert "\ufeff" in plantilla
        assert "text/csv;charset=utf-8" in plantilla

    def test_el_csv_escapa_separadores_y_comillas(self, plantilla):
        """La composición lleva comas: sin escapar, rompería las columnas."""
        assert 'replace(/"/g' in plantilla

    def test_el_html_generado_incluye_la_tabla(self, datos, tmp_path):
        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "tab", region_column="Subregion")
        html = out.read_text(encoding="utf-8")

        assert 'id="tab-tabla"' in html
        assert "function renderTabla(" in html


class TestAperturaLocal:
    """El archivo debe abrirse con doble clic (`file://`), no solo servido.

    Bajo `file://` el documento vive en un origen opaco: cualquier recurso
    externo o cualquier imagen que contamine el canvas rompe funciones que sí
    andan al servirlo por HTTP.
    """

    def test_ninguna_ruta_relativa_en_la_plantilla(self, plantilla):
        """Una ruta relativa obligaría a copiar archivos vecinos junto al HTML."""
        import re

        refs = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', plantilla)
        relativas = [
            r for r in refs
            if not r.startswith(("data:", "http:", "https:", "#", "javascript:"))
            and "__LEAFLET" not in r
        ]
        assert relativas == [], f"referencias relativas: {relativas}"

    def test_sin_peticiones_en_tiempo_de_ejecucion(self, plantilla):
        """`fetch` y `XMLHttpRequest` fallan sobre file:// por política de origen."""
        for prohibido in ("fetch(", "XMLHttpRequest", "importScripts", 'type="module"'):
            assert prohibido not in plantilla, f"la plantilla usa {prohibido}"

    def test_el_png_de_las_graficas_no_usa_blob_en_el_canvas(self, plantilla):
        """Regresión: una imagen blob: contamina el canvas en un origen opaco.

        `toBlob` lanzaría entonces SecurityError al exportar las gráficas desde
        un archivo abierto con doble clic.
        """
        inicio = plantilla.index("function svgToPng(")
        cuerpo = plantilla[inicio:plantilla.index("\n}", inicio)]

        assert "createObjectURL" not in cuerpo
        assert "data:image/svg+xml;charset=utf-8," in cuerpo
        assert "encodeURIComponent(svg)" in cuerpo

    def test_la_exportacion_del_png_avisa_si_falla(self, plantilla):
        assert "SecurityError" in plantilla or "err.name" in plantilla

    def test_el_html_generado_no_referencia_archivos_vecinos(self, datos, tmp_path):
        import re

        grid, catalog = datos
        out = build_webmap(grid, catalog, tmp_path / "local", region_column="Subregion")
        html = out.read_text(encoding="utf-8")

        refs = re.findall(r'(?:src|href)=["\']([^"\']+)["\']', html)
        relativas = [
            r for r in refs
            if not r.startswith(("data:", "http:", "https:", "#", "javascript:"))
        ]
        assert relativas == []
