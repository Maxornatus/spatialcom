"""Figuras con formato de publicación.

Todas las funciones devuelven `(fig, ax)` y **no** llaman a `plt.show()` ni
guardan por su cuenta: la persistencia se decide en la capa que las invoca
(`save_figure`). Esto permite componerlas en paneles y probarlas sin backend
gráfico, algo imposible en el notebook original.
"""
from .charts import (
    disturbance_composition,
    plot_disturbance_composition,
    plot_richness_vs_disturbance,
)
from .heatmap import plot_incidence_heatmap
from .theme import CLUSTER_PALETTE, apply_theme, italic_binomial, save_figure

__all__ = [
    "apply_theme",
    "save_figure",
    "italic_binomial",
    "CLUSTER_PALETTE",
    "plot_richness_vs_disturbance",
    "disturbance_composition",
    "plot_disturbance_composition",
    "plot_incidence_heatmap",
]
