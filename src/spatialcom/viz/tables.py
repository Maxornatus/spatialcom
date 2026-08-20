"""Tablas de resultados listas para el manuscrito.

Genera un `DataFrame` con la estructura final y lo exporta a CSV, LaTeX o
Markdown. En el notebook la "tabla ejecutiva" se dibujaba como imagen PNG, lo
que impide copiarla, corregirla o enviarla a una revista.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .theme import italic_binomial


def cluster_summary_table(
    catalog: pd.DataFrame,
    labels: pd.Series,
    id_column: str = "community_id",
    extra_means: list[str] | None = None,
) -> pd.DataFrame:
    """Una fila por cluster: nº de comunidades, extensión, riqueza y variables extra."""
    df = catalog.copy()
    df["cluster"] = df[id_column].map(labels)
    df = df.dropna(subset=["cluster"])

    agg = {
        "n_communities": (id_column, "nunique"),
        "cells_total": ("n_cells", "sum"),
        "richness_mean": ("richness", "mean"),
        "richness_min": ("richness", "min"),
        "richness_max": ("richness", "max"),
    }
    for col in extra_means or []:
        if col in df.columns:
            agg[f"{col}_mean"] = (col, "mean")

    table = df.groupby("cluster").agg(**agg).round(2)
    table["cells_pct"] = (table["cells_total"] / table["cells_total"].sum() * 100).round(1)
    return table.reset_index()


def indicator_species_table(
    profiles: pd.DataFrame, top_n: int = 5, min_frequency: float = 0.5
) -> pd.DataFrame:
    """Especies más frecuentes en cada cluster, con su frecuencia relativa."""
    rows = []
    for cluster in profiles.columns:
        top = profiles[cluster].sort_values(ascending=False).head(top_n)
        top = top[top >= min_frequency]
        rows.append(
            {
                "cluster": cluster.replace("cluster_", ""),
                "indicator_species": "; ".join(
                    f"{sp} ({freq:.0%})" for sp, freq in top.items()
                ),
            }
        )
    return pd.DataFrame(rows)


def export_table(
    df: pd.DataFrame,
    path: str | Path,
    fmt: str = "csv",
    italicize: str | None = None,
    caption: str | None = None,
) -> Path:
    """Exporta una tabla a `csv`, `md` o `tex`."""
    out = df.copy()
    if italicize and italicize in out.columns:
        out[italicize] = out[italicize].astype(str).map(
            lambda s: ", ".join(italic_binomial(x) for x in s.split(", "))
        )

    path = Path(path).with_suffix("." + fmt)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "csv":
        out.to_csv(path, index=False, encoding="utf-8")
    elif fmt == "md":
        path.write_text(out.to_markdown(index=False), encoding="utf-8")
    elif fmt == "tex":
        path.write_text(
            out.to_latex(index=False, escape=False, caption=caption, longtable=len(out) > 40),
            encoding="utf-8",
        )
    else:
        raise ValueError(f"Formato de tabla no soportado: {fmt}")
    return path
