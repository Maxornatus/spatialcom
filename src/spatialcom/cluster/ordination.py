"""Ordenación de comunidades para visualización en dos dimensiones.

PCA sobre incidencia binaria es aceptable como resumen exploratorio, pero para
datos de presencia/ausencia con distancia de Jaccard la opción correcta es un
escalamiento multidimensional (PCoA / NMDS) sobre la matriz de distancias, que
preserva la métrica realmente usada en el clustering. Ambas están disponibles;
`method='pcoa'` es la recomendada para figuras que acompañen al dendrograma.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from scipy.spatial.distance import squareform
from sklearn.decomposition import PCA
from sklearn.manifold import MDS, TSNE

from .._logging import get_logger

log = get_logger(__name__)

Method = Literal["pcoa", "pca", "nmds", "tsne"]


@dataclass(slots=True)
class Ordination:
    """Coordenadas de ordenación y su diagnóstico asociado."""

    coords: pd.DataFrame
    method: str
    explained: np.ndarray | None = None
    stress: float | None = None

    def axis_label(self, axis: int) -> str:
        """Etiqueta de eje lista para la figura, con varianza explicada si aplica."""
        name = {"pcoa": "PCoA", "pca": "PC", "nmds": "NMDS", "tsne": "t-SNE"}[self.method]
        if self.explained is not None and axis < len(self.explained):
            return f"{name}{axis + 1} ({self.explained[axis] * 100:.1f} %)"
        return f"{name}{axis + 1}"


def ordinate(
    incidence: pd.DataFrame,
    distance: np.ndarray | None = None,
    method: Method = "pcoa",
    n_components: int = 2,
    random_state: int = 42,
) -> Ordination:
    """Proyecta las comunidades en `n_components` dimensiones.

    Parameters
    ----------
    incidence:
        Matriz comunidad x especie.
    distance:
        Distancias condensadas ya calculadas (requeridas por `pcoa` y `nmds`).
    method:
        `pcoa` (recomendada), `pca`, `nmds` o `tsne`.
    """
    index = incidence.index

    if distance is not None:
        n = len(index)
        esperado = n * (n - 1) // 2
        if distance.size != esperado:
            raise ValueError(
                f"La matriz de distancias corresponde a otro conjunto de comunidades: "
                f"{distance.size} pares para {n} filas de incidencia (se esperaban "
                f"{esperado}). Si el clustering excluyó comunidades con "
                f"cluster.min_cells, pase solo las agrupadas: "
                f"incidence.loc[result.labels.index]."
            )

    if method == "pca":
        model = PCA(n_components=n_components, random_state=random_state)
        coords = model.fit_transform(incidence.to_numpy(dtype="float64"))
        return Ordination(
            coords=pd.DataFrame(coords, index=index),
            method="pca",
            explained=model.explained_variance_ratio_,
        )

    if distance is None:
        raise ValueError(f"El método '{method}' requiere la matriz de distancias.")
    square = squareform(distance)

    if method == "pcoa":
        n = square.shape[0]
        j = np.eye(n) - np.ones((n, n)) / n
        b = -0.5 * j @ (square**2) @ j
        eigvals, eigvecs = np.linalg.eigh(b)
        order = np.argsort(eigvals)[::-1]
        eigvals, eigvecs = eigvals[order], eigvecs[:, order]
        positive = eigvals > 0
        coords = eigvecs[:, positive][:, :n_components] * np.sqrt(
            eigvals[positive][:n_components]
        )
        explained = eigvals[positive] / eigvals[positive].sum()
        return Ordination(
            coords=pd.DataFrame(coords, index=index),
            method="pcoa",
            explained=explained[:n_components],
        )

    if method == "nmds":
        model = MDS(
            n_components=n_components,
            dissimilarity="precomputed",
            metric=False,
            random_state=random_state,
            normalized_stress="auto",
            n_init=10,
        )
        coords = model.fit_transform(square)
        log.info("NMDS stress: %.4f", model.stress_)
        return Ordination(
            coords=pd.DataFrame(coords, index=index), method="nmds", stress=float(model.stress_)
        )

    if method == "tsne":
        perplexity = min(30, max(5, (len(index) - 1) // 3))
        model = TSNE(
            n_components=n_components,
            metric="precomputed",
            init="random",
            perplexity=perplexity,
            random_state=random_state,
        )
        coords = model.fit_transform(square)
        return Ordination(coords=pd.DataFrame(coords, index=index), method="tsne")

    raise ValueError(f"Método de ordenación desconocido: {method}")
