"""Matrices de distancia y similitud sobre datos de incidencia binaria."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform

from .._logging import get_logger

log = get_logger(__name__)

#: Métricas apropiadas para datos de presencia/ausencia.
BINARY_METRICS = ("jaccard", "dice", "rogerstanimoto", "sokalsneath", "russellrao")


def composition_distance(incidence: pd.DataFrame, metric: str = "jaccard") -> np.ndarray:
    """Distancia por pares entre comunidades, en forma condensada.

    Notas
    -----
    `scipy` devuelve `NaN` para pares de vectores todo-cero con métricas
    binarias. Aquí se detecta la situación y se sustituye por distancia máxima,
    en vez de dejar que el `NaN` se propague silenciosamente al `linkage`.
    """
    matrix = incidence.to_numpy(dtype=bool)

    empty = ~matrix.any(axis=1)
    if empty.any():
        log.warning(
            "%d comunidades sin especies presentes; se les asigna distancia máxima.",
            int(empty.sum()),
        )

    if metric not in BINARY_METRICS and metric != "euclidean":
        log.warning("Métrica '%s' no es estándar para datos binarios.", metric)

    d = pdist(matrix, metric=metric)
    if np.isnan(d).any():
        log.warning("Se sustituyen %d distancias NaN por 1.0.", int(np.isnan(d).sum()))
        d = np.nan_to_num(d, nan=1.0)
    return d


def similarity_matrix(incidence: pd.DataFrame, metric: str = "jaccard") -> pd.DataFrame:
    """Matriz cuadrada de similitud (1 - distancia), etiquetada por comunidad."""
    d = composition_distance(incidence, metric=metric)
    sim = 1.0 - squareform(d)
    return pd.DataFrame(sim, index=incidence.index, columns=incidence.index)
