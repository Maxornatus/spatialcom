"""Pruebas del clustering y sus guardas metodológicas."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from spatialcom.cluster.distance import composition_distance, similarity_matrix
from spatialcom.cluster.hierarchical import cluster_communities, cluster_profiles
from spatialcom.cluster.ordination import ordinate
from spatialcom.config import ClusterConfig
from spatialcom.exceptions import ConfigError


@pytest.fixture
def incidence():
    """Dos grupos claramente separados: {a,b} frente a {c,d}."""
    data = {
        "sp_a": [1, 1, 1, 0, 0, 0],
        "sp_b": [1, 1, 0, 0, 0, 0],
        "sp_c": [0, 0, 0, 1, 1, 1],
        "sp_d": [0, 0, 0, 1, 1, 0],
    }
    return pd.DataFrame(data, index=[f"C{i}" for i in range(6)]).astype(bool)


class TestDistance:
    def test_reemplaza_nan_de_filas_vacias(self):
        df = pd.DataFrame({"a": [0, 0, 1], "b": [0, 1, 1]}).astype(bool)
        d = composition_distance(df, metric="jaccard")
        assert not np.isnan(d).any()

    def test_similitud_es_simetrica_con_diagonal_unitaria(self, incidence):
        sim = similarity_matrix(incidence)
        assert np.allclose(sim.to_numpy(), sim.to_numpy().T)
        assert np.allclose(np.diag(sim.to_numpy()), 1.0)


class TestClustering:
    def test_rechaza_ward_sobre_jaccard(self, incidence):
        cfg = ClusterConfig(metric="jaccard", linkage="ward")
        with pytest.raises(ConfigError, match="ward"):
            cluster_communities(incidence, cfg)

    def test_recupera_los_dos_grupos_reales(self, incidence):
        cfg = ClusterConfig(linkage="average", selection="fixed", n_clusters=2)
        result = cluster_communities(incidence, cfg)
        etiquetas = result.labels
        assert etiquetas.loc["C0"] == etiquetas.loc["C1"]
        assert etiquetas.loc["C3"] == etiquetas.loc["C4"]
        assert etiquetas.loc["C0"] != etiquetas.loc["C3"]

    def test_la_seleccion_por_silueta_produce_diagnostico(self, incidence):
        result = cluster_communities(incidence, ClusterConfig(selection="silhouette"))
        assert not result.diagnostics.empty
        assert {"k", "silhouette"} <= set(result.diagnostics.columns)
        assert 2 <= result.k <= 5

    def test_min_cells_excluye_comunidades_raras(self, incidence):
        weights = pd.Series([100, 100, 1, 100, 100, 1], index=incidence.index)
        cfg = ClusterConfig(selection="fixed", n_clusters=2, min_cells=10)
        result = cluster_communities(incidence, cfg, weights=weights)
        assert len(result.labels) == 4

    def test_perfiles_dan_frecuencias_entre_0_y_1(self, incidence):
        result = cluster_communities(
            incidence, ClusterConfig(selection="fixed", n_clusters=2)
        )
        profiles = cluster_profiles(incidence, result.labels)
        assert profiles.to_numpy().min() >= 0
        assert profiles.to_numpy().max() <= 1


class TestOrdination:
    def test_pcoa_devuelve_dos_ejes_y_varianza(self, incidence):
        d = composition_distance(incidence)
        result = ordinate(incidence, distance=d, method="pcoa")
        assert result.coords.shape == (len(incidence), 2)
        assert result.explained is not None
        assert "PCoA1" in result.axis_label(0)

    def test_pca_no_requiere_distancias(self, incidence):
        result = ordinate(incidence, method="pca")
        assert result.coords.shape[1] == 2


class TestReconstruccionDeIncidencia:
    """La reanudación rehace la matriz de incidencia desde el CSV del catálogo."""

    def test_ida_y_vuelta_conserva_las_composiciones(self):
        from spatialcom.pipeline import _incidence_from_catalog

        catalog = pd.DataFrame(
            {
                "community_id": ["C1", "C2", "C3"],
                "species_list": ["sp_a, sp_b", "sp_b", "sp_a, sp_b, sp_c"],
            }
        )
        inc = _incidence_from_catalog(catalog)
        assert list(inc.columns) == ["sp_a", "sp_b", "sp_c"]
        assert inc.loc["C1"].tolist() == [True, True, False]
        assert inc.loc["C2"].tolist() == [False, True, False]
        assert inc.loc["C3"].all()

    def test_tolera_composiciones_vacias(self):
        from spatialcom.pipeline import _incidence_from_catalog

        catalog = pd.DataFrame(
            {"community_id": ["C1", "C2"], "species_list": ["sp_a", float("nan")]}
        )
        inc = _incidence_from_catalog(catalog)
        assert not inc.loc["C2"].any()


class TestSubconjuntoAgrupado:
    """Con `min_cells > 1` el clustering usa menos comunidades que el catálogo.

    Todo lo que consume la matriz de distancias —ordenación, mapa de calor,
    matriz de similitud— debe restringirse a ese subconjunto. Pasarle el
    catálogo completo produce un desajuste de tamaños.
    """

    @pytest.fixture
    def incidencia_grande(self):
        rng = np.random.default_rng(0)
        datos = rng.integers(0, 2, size=(20, 6)).astype(bool)
        return pd.DataFrame(
            datos, index=[f"C{i}" for i in range(20)],
            columns=[f"sp_{c}" for c in "abcdef"],
        )

    def test_las_etiquetas_solo_cubren_las_agrupadas(self, incidencia_grande):
        pesos = pd.Series([10] * 8 + [1] * 12, index=incidencia_grande.index)
        cfg = ClusterConfig(selection="fixed", n_clusters=2, min_cells=5)
        result = cluster_communities(incidencia_grande, cfg, weights=pesos)

        assert len(result.labels) == 8
        assert set(result.labels.index) <= set(incidencia_grande.index)

    def test_la_distancia_corresponde_al_subconjunto(self, incidencia_grande):
        pesos = pd.Series([10] * 8 + [1] * 12, index=incidencia_grande.index)
        cfg = ClusterConfig(selection="fixed", n_clusters=2, min_cells=5)
        result = cluster_communities(incidencia_grande, cfg, weights=pesos)

        n = len(result.labels)
        assert result.distance.size == n * (n - 1) // 2

    def test_ordinate_rechaza_el_conjunto_equivocado(self, incidencia_grande):
        """Regresión: pasar el catálogo completo daba un error de forma de pandas."""
        from spatialcom.cluster.ordination import ordinate

        pesos = pd.Series([10] * 8 + [1] * 12, index=incidencia_grande.index)
        cfg = ClusterConfig(selection="fixed", n_clusters=2, min_cells=5)
        result = cluster_communities(incidencia_grande, cfg, weights=pesos)

        with pytest.raises(ValueError, match="otro conjunto de comunidades"):
            ordinate(incidencia_grande, distance=result.distance, method="pcoa")

    def test_ordinate_acepta_el_subconjunto(self, incidencia_grande):
        from spatialcom.cluster.ordination import ordinate

        pesos = pd.Series([10] * 8 + [1] * 12, index=incidencia_grande.index)
        cfg = ClusterConfig(selection="fixed", n_clusters=2, min_cells=5)
        result = cluster_communities(incidencia_grande, cfg, weights=pesos)

        agrupadas = incidencia_grande.loc[result.labels.index]
        ord_result = ordinate(agrupadas, distance=result.distance, method="pcoa")
        assert list(ord_result.coords.index) == list(result.labels.index)
