"""Clustering jerárquico de comunidades y selección justificada del número de grupos.

Dos correcciones metodológicas respecto al notebook:

* **Ward sobre Jaccard.** El notebook usaba `linkage(pdist(..., 'jaccard'),
  method='ward')`. El criterio de Ward minimiza la varianza intra-grupo y está
  definido solo para distancias euclidianas; `scipy` no lo impide, pero el
  resultado no es la solución de Ward y las alturas del dendrograma no son
  interpretables. Para incidencia binaria corresponde UPGMA (`average`) o
  `complete`. `cluster_communities` rechaza la combinación inválida.

* **k arbitrario.** `num_clusters=4` estaba fijado sin criterio. `evaluate_k`
  calcula silueta y correlación cofenética sobre un rango de k para que la
  elección sea defendible y reportable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import silhouette_score

from .._logging import get_logger
from ..config import ClusterConfig
from ..exceptions import ConfigError
from .distance import composition_distance

log = get_logger(__name__)


@dataclass(slots=True)
class ClusterResult:
    """Resultado del clustering jerárquico."""

    linkage_matrix: np.ndarray
    labels: pd.Series
    k: int
    distance: np.ndarray
    diagnostics: pd.DataFrame
    cophenetic_r: float
    metric: str
    method: str

    @property
    def distance_matrix(self) -> np.ndarray:
        return squareform(self.distance)


#: A partir de este número de comunidades la silueta se estima sobre una
#: muestra. La matriz cuadrada de distancias crece con el cuadrado de n: con
#: 10.000 comunidades ocuparía 800 MB y habría que recorrerla una vez por cada k.
SILHOUETTE_SAMPLE_THRESHOLD = 3000


def evaluate_k(
    distance: np.ndarray,
    linkage_matrix: np.ndarray,
    k_range: tuple[int, int] = (2, 12),
    random_state: int = 42,
) -> pd.DataFrame:
    """Silueta media para cada k del rango, sobre la matriz de distancias precomputada.

    Con muchos elementos la silueta se estima sobre una submuestra aleatoria en
    lugar de sobre la matriz completa; la columna `sampled` indica cuándo ha
    ocurrido, para que el diagnóstico no se lea como exacto cuando no lo es.
    """
    square = squareform(distance)
    n = square.shape[0]
    lo, hi = k_range
    hi = min(hi, n - 1)

    muestreado = n > SILHOUETTE_SAMPLE_THRESHOLD
    if muestreado:
        log.warning(
            "%d comunidades: la silueta se estima sobre una muestra de %d "
            "para acotar memoria y tiempo.",
            n, SILHOUETTE_SAMPLE_THRESHOLD,
        )

    rows = []
    for k in range(lo, hi + 1):
        labels = fcluster(linkage_matrix, k, criterion="maxclust")
        if len(np.unique(labels)) < 2:
            continue
        rows.append(
            {
                "k": k,
                "silhouette": float(
                    silhouette_score(
                        square, labels, metric="precomputed",
                        sample_size=SILHOUETTE_SAMPLE_THRESHOLD if muestreado else None,
                        random_state=random_state,
                    )
                ),
                "n_singletons": int((pd.Series(labels).value_counts() == 1).sum()),
                "sampled": muestreado,
            }
        )
    return pd.DataFrame(rows)


def cluster_communities(
    incidence: pd.DataFrame,
    cfg: ClusterConfig,
    weights: pd.Series | None = None,
) -> ClusterResult:
    """Agrupa comunidades por similitud de composición.

    Parameters
    ----------
    incidence:
        Matriz comunidad x especie (booleana), indexada por `community_id`.
    cfg:
        Métrica, método de enlace y estrategia de selección de k.
    weights:
        Extensión (nº de celdas) de cada comunidad. Si se aporta junto con
        `cfg.min_cells > 1`, las composiciones muy raras se excluyen del
        clustering: pesan igual que una comunidad extensa y desestabilizan el
        dendrograma sin aportar señal biogeográfica.
    """
    if cfg.linkage == "ward" and cfg.metric != "euclidean":
        raise ConfigError(
            "linkage='ward' requiere metric='euclidean'. Para incidencia binaria "
            "use linkage='average' (UPGMA) o 'complete'."
        )

    work = incidence
    if weights is not None and cfg.min_cells > 1:
        keep = weights.reindex(incidence.index).fillna(0) >= cfg.min_cells
        dropped = int((~keep).sum())
        if dropped:
            log.info(
                "Excluidas %d comunidades con menos de %d celdas del clustering.",
                dropped,
                cfg.min_cells,
            )
        work = incidence[keep.to_numpy()]

    if len(work) < 3:
        raise ConfigError(f"Insuficientes comunidades para agrupar: {len(work)}")

    distance = composition_distance(work, metric=cfg.metric)
    log.info("Enlace jerárquico: método '%s', métrica '%s'.", cfg.linkage, cfg.metric)
    Z = linkage(distance, method=cfg.linkage)

    coph_r, _ = cophenet(Z, distance)
    log.info("Correlación cofenética: %.3f", coph_r)
    if coph_r < 0.7:
        log.warning(
            "Correlación cofenética baja (%.3f): el dendrograma representa mal "
            "las distancias originales.",
            coph_r,
        )

    diagnostics = evaluate_k(distance, Z, cfg.k_range, cfg.random_state)

    if cfg.selection == "silhouette" and not diagnostics.empty:
        k = int(diagnostics.loc[diagnostics["silhouette"].idxmax(), "k"])
        log.info(
            "k seleccionado por silueta: %d (silueta = %.3f)",
            k,
            diagnostics["silhouette"].max(),
        )
    else:
        if cfg.n_clusters is None:
            raise ConfigError("selection='fixed' requiere n_clusters.")
        k = cfg.n_clusters
        log.info("k fijado por configuración: %d", k)

    labels = pd.Series(
        fcluster(Z, k, criterion="maxclust"), index=work.index, name="cluster", dtype="int32"
    )

    sizes = labels.value_counts().sort_index()
    log.info("Tamaño de los grupos:\n%s", sizes.to_string())

    return ClusterResult(
        linkage_matrix=Z,
        labels=labels,
        k=k,
        distance=distance,
        diagnostics=diagnostics,
        cophenetic_r=float(coph_r),
        metric=cfg.metric,
        method=cfg.linkage,
    )


def cluster_profiles(
    incidence: pd.DataFrame, labels: pd.Series, weights: pd.Series | None = None
) -> pd.DataFrame:
    """Especies indicadoras de cada grupo: frecuencia de ocurrencia por cluster.

    Base para la tabla resumen del artículo: para cada cluster, la proporción
    de sus comunidades en las que aparece cada especie.
    """
    aligned = incidence.loc[labels.index]
    profiles = aligned.groupby(labels.to_numpy()).mean().T
    profiles.columns = [f"cluster_{c}" for c in profiles.columns]
    profiles.index.name = "species"

    if weights is not None:
        w = weights.reindex(labels.index).fillna(0)
        extent = w.groupby(labels.to_numpy()).sum()
        profiles.attrs["cells_per_cluster"] = extent.to_dict()

    return profiles.round(3)
