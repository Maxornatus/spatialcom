"""Pruebas de las gráficas de relación y del mapa de calor de incidencia."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from spatialcom.cluster.hierarchical import cluster_communities
from spatialcom.config import ClusterConfig
from spatialcom.exceptions import SchemaError
from spatialcom.viz.charts import (
    disturbance_composition,
    plot_disturbance_composition,
    plot_richness_vs_disturbance,
)
from spatialcom.viz.heatmap import plot_incidence_heatmap


@pytest.fixture(autouse=True)
def cerrar_figuras():
    yield
    plt.close("all")


@pytest.fixture
def catalogo():
    """Doce comunidades con riqueza, extensión y pérdida."""
    rng = np.random.default_rng(0)
    n = 12
    return pd.DataFrame(
        {
            "community_id": [f"C{i}" for i in range(n)],
            "species_list": ["sp_a, sp_b"] * n,
            "richness": rng.integers(1, 10, n),
            "n_cells": rng.integers(1, 500, n),
            "pct_loss_total": rng.uniform(0, 40, n),
            "cluster": rng.integers(1, 4, n),
        }
    )


@pytest.fixture
def grid_niveles():
    """Cuadrícula con región y nivel de perturbación por celda."""
    return pd.DataFrame(
        {
            "community_id": ["C1"] * 10 + ["C2"] * 10,
            "Subregion": ["oeste"] * 10 + ["este"] * 10,
            "disturbance_level": [0, 1, 1, 1, 2, 2, 3, 4, 5, 1] + [1] * 10,
        }
    )


class TestRiquezaVsPerturbacion:
    def test_devuelve_figura_y_ejes(self, catalogo):
        fig, ax = plot_richness_vs_disturbance(catalogo)
        assert ax.get_xlabel().startswith("Pérdida")
        assert ax.get_ylabel().startswith("Riqueza")

    def test_dibuja_un_punto_por_comunidad(self, catalogo):
        fig, ax = plot_richness_vs_disturbance(catalogo, color_by=None)
        assert sum(c.get_offsets().shape[0] for c in ax.collections) == len(catalogo)

    def test_el_area_del_punto_sigue_la_extension(self, catalogo):
        """El área debe crecer con `n_cells`, no el radio: sesga la lectura."""
        fig, ax = plot_richness_vs_disturbance(catalogo, color_by=None)
        areas = ax.collections[0].get_sizes()
        orden_areas = np.argsort(areas)
        orden_celdas = np.argsort(catalogo["n_cells"].to_numpy())
        assert (orden_areas == orden_celdas).all()

    def test_sin_asociacion_no_dibuja_tendencia(self):
        """Regresión: una recta junto a un p-valor no significativo engaña."""
        rng = np.random.default_rng(1)
        n = 60
        catalogo = pd.DataFrame(
            {
                "richness": rng.integers(1, 10, n),
                "n_cells": rng.integers(1, 100, n),
                "pct_loss_total": rng.uniform(0, 40, n),
            }
        )
        fig, ax = plot_richness_vs_disturbance(catalogo, color_by=None, fit="auto")
        assert len(ax.lines) == 0
        textos = " ".join(t.get_text() for t in ax.texts)
        assert "sin asociación" in textos

    def test_con_asociacion_clara_si_dibuja_tendencia(self):
        n = 60
        x = np.linspace(0, 40, n)
        catalogo = pd.DataFrame(
            {"richness": x * 0.2 + 1, "n_cells": np.full(n, 10), "pct_loss_total": x}
        )
        fig, ax = plot_richness_vs_disturbance(catalogo, color_by=None, fit="auto")
        assert len(ax.lines) == 1

    def test_fit_never_nunca_dibuja(self):
        n = 60
        x = np.linspace(0, 40, n)
        catalogo = pd.DataFrame(
            {"richness": x * 0.2 + 1, "n_cells": np.full(n, 10), "pct_loss_total": x}
        )
        fig, ax = plot_richness_vs_disturbance(catalogo, color_by=None, fit="never")
        assert len(ax.lines) == 0

    def test_falla_si_falta_una_columna(self, catalogo):
        with pytest.raises(SchemaError, match="pct_loss_total"):
            plot_richness_vs_disturbance(catalogo.drop(columns="pct_loss_total"))


class TestComposicionDePerturbacion:
    def test_las_filas_suman_uno_al_normalizar(self, grid_niveles):
        tabla = disturbance_composition(grid_niveles, "Subregion")
        assert np.allclose(tabla.sum(axis=1), 1.0)

    def test_cuenta_celdas_no_comunidades(self, grid_niveles):
        """Agregar por comunidad daría el mismo peso a una de 2 y otra de 954."""
        tabla = disturbance_composition(grid_niveles, "Subregion", normalize=False)
        assert tabla.sum().sum() == len(grid_niveles)
        assert tabla.attrs["cells_per_group"] == {"este": 10, "oeste": 10}

    def test_conserva_el_orden_ordinal_de_los_niveles(self, grid_niveles):
        tabla = disturbance_composition(grid_niveles, "Subregion")
        assert list(tabla.columns) == sorted(tabla.columns)

    def test_la_grafica_apila_todos_los_niveles(self, grid_niveles):
        tabla = disturbance_composition(grid_niveles, "Subregion")
        fig, ax = plot_disturbance_composition(tabla)
        # Un contenedor de barras por nivel presente.
        assert len(ax.containers) == tabla.shape[1]
        assert ax.get_xlim() == (0, 1)

    def test_falla_sin_la_columna_de_nivel(self, grid_niveles):
        with pytest.raises(SchemaError, match="disturbance_level"):
            disturbance_composition(
                grid_niveles.drop(columns="disturbance_level"), "Subregion"
            )

    def test_tabla_vacia_es_error_explicito(self):
        with pytest.raises(ValueError, match="vacía"):
            plot_disturbance_composition(pd.DataFrame())


class TestHeatmapIncidencia:
    @pytest.fixture
    def incidencia(self):
        """Dos bloques separados: {a,b} frente a {c,d}."""
        data = {
            "sp_a": [1, 1, 1, 0, 0, 0],
            "sp_b": [1, 1, 0, 0, 0, 0],
            "sp_c": [0, 0, 0, 1, 1, 1],
            "sp_d": [0, 0, 0, 1, 1, 0],
        }
        return pd.DataFrame(data, index=[f"C{i}" for i in range(6)]).astype(bool)

    @pytest.fixture
    def resultado(self, incidencia):
        return cluster_communities(
            incidencia, ClusterConfig(selection="fixed", n_clusters=2)
        )

    def test_la_matriz_tiene_la_forma_de_la_incidencia(self, incidencia, resultado):
        fig, axes = plot_incidence_heatmap(incidencia, resultado, show_cluster_strip=False)
        imagen = axes[0].images[0].get_array()
        assert imagen.shape == incidencia.shape

    def test_las_filas_siguen_el_orden_del_dendrograma(self, incidencia, resultado):
        """Comunidades del mismo grupo deben quedar contiguas."""
        from scipy.cluster.hierarchy import leaves_list

        orden = leaves_list(resultado.linkage_matrix)
        etiquetas = resultado.labels.iloc[orden].to_numpy()
        cambios = int((etiquetas[1:] != etiquetas[:-1]).sum())
        assert cambios == resultado.k - 1

    def test_la_franja_de_grupo_anade_un_eje(self, incidencia, resultado):
        sin_franja = plot_incidence_heatmap(
            incidencia, resultado, show_cluster_strip=False
        )[1]
        con_franja = plot_incidence_heatmap(
            incidencia, resultado, show_cluster_strip=True
        )[1]
        assert len(con_franja) == len(sin_franja) + 1

    def test_la_barra_de_extension_anade_otro_eje(self, incidencia, resultado):
        pesos = pd.Series(range(1, 7), index=incidencia.index)
        axes = plot_incidence_heatmap(incidencia, resultado, weights=pesos)[1]
        assert len(axes) == 3   # franja + matriz + extensión

    @pytest.mark.parametrize("modo", ["cluster", "prevalence", "alphabetic"])
    def test_los_ordenes_de_especie_conservan_todas(self, incidencia, resultado, modo):
        from spatialcom.viz.heatmap import _orden_especies

        orden = _orden_especies(incidencia, modo, resultado.metric)
        assert sorted(orden) == sorted(incidencia.columns)

    def test_especies_ubicuas_no_rompen_el_orden_por_cluster(self, incidencia, resultado):
        """Una especie presente en todas no tiene distancia definida con ninguna."""
        from spatialcom.viz.heatmap import _orden_especies

        con_ubicua = incidencia.copy()
        con_ubicua["sp_ubicua"] = True
        con_ubicua["sp_ausente"] = False

        orden = _orden_especies(con_ubicua, "cluster", resultado.metric)
        assert sorted(orden) == sorted(con_ubicua.columns)
