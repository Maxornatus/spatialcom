"""Gráficas de relación entre composición y perturbación.

Dos figuras que responden a preguntas del análisis y no del método:

* `plot_richness_vs_disturbance` — ¿están las comunidades más ricas más
  perturbadas?
* `plot_disturbance_composition` — ¿cómo se reparte la intensidad de la
  perturbación dentro de cada región o grupo?
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from scipy import stats

from .._logging import get_logger
from ..io.writers import require_columns
from .theme import cluster_colors

log = get_logger(__name__)

#: Paleta ordinal para los niveles de perturbación (claro = intacto).
DISTURBANCE_COLORS = [
    "#1a7d3f", "#a8d08d", "#ffe08a", "#f9a03f", "#e2552a", "#8c1d18",
]


# ---------------------------------------------------------------------------
# 2. Riqueza frente a perturbación
# ---------------------------------------------------------------------------
def plot_richness_vs_disturbance(
    catalog: pd.DataFrame,
    x: str = "pct_loss_total",
    y: str = "richness",
    size: str = "n_cells",
    color_by: str | None = "cluster",
    fit: str = "auto",
    weighted_fit: bool = True,
    annotate_top: int = 0,
    label_column: str = "species_list",
    figsize: tuple[float, float] = (7.5, 5.5),
    xlabel: str | None = None,
    ylabel: str | None = None,
):
    """Dispersión de riqueza frente a pérdida de cobertura.

    Cada punto es una comunidad; el área del punto es proporcional a su
    extensión, de modo que una comunidad de 954 celdas no pesa visualmente lo
    mismo que una de 2.

    Parameters
    ----------
    catalog:
        Catálogo de comunidades con las columnas `x`, `y` y `size`.
    color_by:
        Columna categórica para el color (`cluster`, una región...). `None`
        pinta todos los puntos igual.
    fit:
        `auto` (por omisión) dibuja la recta de tendencia solo si la correlación
        de Spearman es significativa; `always` la dibuja siempre; `never` nunca.
        El valor por omisión evita la figura engañosa más común: una recta con
        pendiente visible junto a un p-valor que dice que no hay asociación.
    weighted_fit:
        Ponderar la recta por `size`. Sin ponderar, los cientos de comunidades
        diminutas dominan un ajuste que describe una fracción mínima del
        territorio.
    annotate_top:
        Rotula las `n` comunidades con mayor valor de `x`.

    Notes
    -----
    El coeficiente de Spearman que se anota describe la asociación **entre
    comunidades**, que no son observaciones independientes: comparten especies y
    son contiguas en el espacio. Sirve como descriptor de la figura, no como
    prueba de hipótesis. Para inferencia hace falta un modelo que trate la
    autocorrelación espacial explícitamente.
    """
    require_columns(catalog, [x, y, size], "catálogo")

    df = catalog.dropna(subset=[x, y, size]).copy()
    if df.empty:
        raise ValueError(f"No hay filas con {x}, {y} y {size} definidos.")

    pesos = df[size].to_numpy(dtype="float64")
    # Área proporcional a la extensión: el radio va con la raíz.
    areas = 18 + 320 * np.sqrt(pesos / pesos.max())

    fig, ax = plt.subplots(figsize=figsize)

    handles_color: list[Line2D] = []
    titulo_color = ""
    if color_by and color_by in df.columns:
        grupos = sorted(df[color_by].dropna().unique())
        colores = dict(zip(grupos, cluster_colors(len(grupos)), strict=True))
        titulo_color = color_by.capitalize()
        for g in grupos:
            sel = df[color_by] == g
            etiqueta = f"Grupo {int(g)}" if isinstance(g, (int, float)) else str(g)
            ax.scatter(
                df.loc[sel, x], df.loc[sel, y],
                s=areas[sel.to_numpy()], c=colores[g],
                alpha=.65, edgecolor="white", linewidth=.6,
            )
            handles_color.append(
                Line2D([], [], marker="o", linestyle="", markersize=8,
                       markerfacecolor=colores[g], markeredgecolor="white",
                       label=f"{etiqueta} (n = {int(sel.sum())})")
            )
    else:
        ax.scatter(df[x], df[y], s=areas, c="#0072B2", alpha=.6,
                   edgecolor="white", linewidth=.6)

    # --- tendencia ---
    xv, yv = df[x].to_numpy(dtype="float64"), df[y].to_numpy(dtype="float64")
    if len(df) >= 3 and np.ptp(xv) > 0:
        rho, pval = stats.spearmanr(xv, yv)
        significativa = pval < 0.05
        dibujar = fit == "always" or (fit == "auto" and significativa)

        if dibujar:
            w = pesos if weighted_fit else np.ones_like(pesos)
            pendiente, intercepto = np.polyfit(xv, yv, 1, w=np.sqrt(w))
            xs = np.linspace(xv.min(), xv.max(), 100)
            ax.plot(xs, pendiente * xs + intercepto, color="#333333",
                    linestyle="--", linewidth=1.2, zorder=1)

        nota = f"Spearman ρ = {rho:.2f}   p = {pval:.3g}\nn = {len(df)} comunidades"
        if dibujar and weighted_fit:
            nota += "  ·  ajuste ponderado por extensión"
        elif not significativa:
            nota += "\nsin asociación monótona detectable"
        ax.annotate(
            nota, xy=(.02, .98), xycoords="axes fraction", va="top",
            fontsize=9, color="#555555",
        )
        log.info("Spearman rho=%.3f p=%.4g (n=%d)", rho, pval, len(df))

    # --- rótulos de los extremos ---
    if annotate_top and label_column in df.columns:
        from .theme import italic_binomial

        for fila in df.nlargest(annotate_top, x).itertuples():
            especies = str(getattr(fila, label_column)).split(", ")
            etiqueta = italic_binomial(especies[0]) + (
                f" +{len(especies) - 1}" if len(especies) > 1 else ""
            )
            ax.annotate(
                etiqueta, (getattr(fila, x), getattr(fila, y)),
                textcoords="offset points", xytext=(6, 6), fontsize=8,
                color="#444444",
            )

    ax.set_xlabel(xlabel or "Pérdida de cobertura (% de la comunidad)")
    ax.set_ylabel(ylabel or "Riqueza (nº de especies)")
    ax.set_title("Riqueza de la comunidad frente a pérdida de cobertura")

    # Leyenda de tamaño. `markersize` va en puntos de diámetro mientras que el
    # `s` de scatter va en puntos al cuadrado: sin la raíz, los círculos de la
    # leyenda no coinciden con los del gráfico.
    referencias = sorted({int(pesos.min()), int(np.median(pesos)), int(pesos.max())})
    handles_tam = [
        Line2D([], [], marker="o", linestyle="", markerfacecolor="#bbbbbb",
               markeredgecolor="white",
               markersize=np.sqrt(18 + 320 * np.sqrt(v / pesos.max())),
               label=f"{v:,} celdas".replace(",", " "))
        for v in referencias
    ]
    leyenda_tam = ax.legend(
        handles=handles_tam, title="Extensión", loc="lower right",
        fontsize=8, title_fontsize=9, labelspacing=1.8, borderpad=1.1,
        handletextpad=1.4,
    )
    if handles_color:
        ax.add_artist(leyenda_tam)
        ax.legend(handles=handles_color, title=titulo_color, loc="upper right",
                  fontsize=9, title_fontsize=9)

    return fig, ax


# ---------------------------------------------------------------------------
# 4. Composición de niveles de perturbación
# ---------------------------------------------------------------------------
def disturbance_composition(
    grid: pd.DataFrame,
    group_column: str,
    level_column: str = "disturbance_level",
    normalize: bool = True,
) -> pd.DataFrame:
    """Tabla grupo x nivel de perturbación, contada **por celda**.

    La celda es la unidad correcta aquí: agregar por comunidad daría el mismo
    peso a una comunidad de 2 celdas que a una de 954.

    Returns
    -------
    DataFrame con una fila por grupo y una columna por nivel. Con
    `normalize=True` las filas suman 1; el número de celdas queda en el atributo
    `.attrs["cells_per_group"]`.
    """
    require_columns(grid, [group_column, level_column], "cuadrícula")

    subset = grid[[group_column, level_column]].dropna()
    tabla = pd.crosstab(subset[group_column], subset[level_column])
    tabla = tabla.reindex(sorted(tabla.columns), axis=1)

    totales = tabla.sum(axis=1)
    if normalize:
        tabla = tabla.div(totales, axis=0)

    tabla.attrs["cells_per_group"] = totales.to_dict()
    tabla.attrs["normalized"] = normalize
    return tabla


def plot_disturbance_composition(
    tabla: pd.DataFrame,
    figsize: tuple[float, float] = (8, 4.5),
    level_labels: list[str] | None = None,
    sort_by_intact: bool = True,
    title: str = "Composición de la perturbación",
):
    """Barras horizontales apiladas de los niveles de perturbación.

    Es la forma honesta de presentar la perturbación: decir que el 99 % de las
    celdas registra *alguna* pérdida es cierto y poco informativo, porque basta
    un píxel de 30 m. Lo que importa es cuánta superficie está en cada nivel.
    """
    if tabla.empty:
        raise ValueError("La tabla de composición está vacía.")

    datos = tabla.copy()
    if sort_by_intact and datos.columns.size:
        datos = datos.sort_values(datos.columns[0], ascending=True)

    etiquetas = level_labels or [
        "0 · sin pérdida", "1 · < 10 %", "2 · 10-25 %",
        "3 · 25-45 %", "4 · 45-75 %", "5 · > 75 %",
    ]

    fig, ax = plt.subplots(figsize=figsize)
    izquierda = np.zeros(len(datos))
    y = np.arange(len(datos))

    for i, nivel in enumerate(datos.columns):
        valores = datos[nivel].to_numpy(dtype="float64")
        ax.barh(
            y, valores, left=izquierda, height=.68,
            color=DISTURBANCE_COLORS[i % len(DISTURBANCE_COLORS)],
            edgecolor="white", linewidth=.6,
            label=etiquetas[int(nivel)] if int(nivel) < len(etiquetas) else str(nivel),
        )
        izquierda += valores

    normalizado = tabla.attrs.get("normalized", True)
    celdas = tabla.attrs.get("cells_per_group", {})

    ax.set_yticks(y)
    ax.set_yticklabels([
        f"{g}\n{celdas.get(g, 0):,} celdas".replace(",", " ") if celdas else str(g)
        for g in datos.index
    ], fontsize=9)
    ax.set_xlabel("Proporción de celdas" if normalizado else "Celdas")
    if normalizado:
        ax.set_xlim(0, 1)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title(title)
    ax.grid(axis="y", visible=False)
    ax.legend(
        title="Nivel de perturbación", bbox_to_anchor=(1.01, 1), loc="upper left",
        fontsize=8, title_fontsize=9,
    )
    fig.tight_layout()
    return fig, ax
