"""Estadísticas zonales sobre rásters categóricos de perturbación.

Cubre las celdas 6-11 del notebook (Hansen Global Forest Change, `lossyear`):
histograma categórico por celda, agregación por comunidad, porcentajes anuales
y clasificación en niveles.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterstats import zonal_stats

from .._logging import get_logger
from ..config import DeforestationConfig
from ..io.writers import require_columns

log = get_logger(__name__)


def _parse_histogram(hist: dict | None, cfg: DeforestationConfig) -> dict[str, int]:
    """Convierte el histograma categórico de una celda en conteos por año."""
    out: dict[str, int] = {}
    total = 0
    disturbed = 0

    if not isinstance(hist, dict):
        return {"cell_pixels_total": 0, "cell_pixels_disturbed": 0}

    lo, hi = cfg.value_range
    for value, count in hist.items():
        try:
            val = float(value)
        except (TypeError, ValueError):
            continue
        total += count
        if lo <= val <= hi:
            out[f"loss_{cfg.year_offset + int(val)}"] = count
            disturbed += count

    out["cell_pixels_total"] = total
    out["cell_pixels_disturbed"] = disturbed
    return out


def zonal_loss_by_year(
    grid: gpd.GeoDataFrame,
    catalog: pd.DataFrame,
    cfg: DeforestationConfig,
    id_column: str = "community_id",
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Calcula pérdida de cobertura por celda y la agrega por comunidad.

    Returns
    -------
    grid : cuadrícula con conteos por celda (`loss_YYYY`, `cell_pixels_*`)
    summary : catálogo con conteos, porcentajes anuales y `pct_loss_total`
    """
    if cfg.raster is None or not Path(cfg.raster).exists():
        raise FileNotFoundError(f"Ráster de perturbación no encontrado: {cfg.raster}")

    log.info("Calculando histogramas zonales sobre %s", Path(cfg.raster).name)
    stats = zonal_stats(
        grid,
        str(cfg.raster),
        stats="count",
        categorical=True,
        band=cfg.band,
        all_touched=cfg.all_touched,
        geojson_out=False,
        nodata=None,
    )

    per_cell = pd.DataFrame(
        [_parse_histogram(s, cfg) for s in stats], index=grid.index
    ).fillna(0).astype("int64")

    out_grid = grid.join(per_cell)

    # --- agregación por comunidad ---
    occupied = out_grid[out_grid[id_column].notna()]
    agg_cols = list(per_cell.columns)
    by_community = occupied.groupby(id_column, observed=True)[agg_cols].sum().reset_index()
    by_community = by_community.rename(
        columns={
            "cell_pixels_total": "pixels_total",
            "cell_pixels_disturbed": "pixels_disturbed",
        }
    )

    # Copia explícita: en el notebook `denominator = df['col']` seguido de
    # `denominator[...] = np.nan` mutaba el DataFrame de origen.
    denominator = by_community["pixels_total"].astype("float64").copy()
    denominator[denominator == 0] = np.nan

    year_cols = [c for c in by_community.columns if c.startswith("loss_")]
    for col in year_cols:
        by_community["pct_" + col.split("_")[1]] = by_community[col] / denominator * 100

    by_community["pct_loss_total"] = (
        by_community["pixels_disturbed"] / denominator * 100
    ).fillna(0)

    require_columns(catalog, [id_column], "catálogo de comunidades")
    summary = catalog.merge(by_community, on=id_column, how="left")

    fill_cols = [c for c in summary.columns if c.startswith(("loss_", "pct_", "pixels_"))]
    summary[fill_cols] = summary[fill_cols].fillna(0)

    affected = int((per_cell["cell_pixels_disturbed"] > 0).sum())
    log.info(
        "Celdas con pérdida detectada: %d de %d (%.2f%%).",
        affected,
        len(out_grid),
        100 * affected / max(len(out_grid), 1),
    )

    return out_grid, summary


def classify_disturbance_levels(
    grid: gpd.GeoDataFrame,
    cfg: DeforestationConfig,
    pct_column: str = "cell_pct_loss",
    level_column: str = "disturbance_level",
) -> gpd.GeoDataFrame:
    """Clasifica cada celda en niveles ordinales de perturbación.

    Nivel 0 = sin pérdida; los niveles siguientes se derivan de
    `cfg.level_bins` (por defecto 0-10, 10-25, 25-45, 45-75, >75 %).
    """
    require_columns(grid, ["cell_pixels_disturbed", "cell_pixels_total"], "cuadrícula zonal")

    out = grid.copy()
    total = out["cell_pixels_total"].to_numpy(dtype="float64")
    disturbed = out["cell_pixels_disturbed"].to_numpy(dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(total > 0, disturbed / total * 100.0, 0.0)
    out[pct_column] = np.nan_to_num(pct)

    bins = [-np.inf, *cfg.level_bins, np.inf]
    labels = list(range(len(bins) - 1))
    out[level_column] = pd.cut(
        out[pct_column], bins=bins, labels=labels, right=True, include_lowest=True
    ).astype("Int8")

    log.info(
        "Distribución de niveles de perturbación:\n%s",
        out[level_column].value_counts().sort_index().to_string(),
    )
    return out


def level_counts_by_community(
    grid: gpd.GeoDataFrame,
    summary: pd.DataFrame,
    id_column: str = "community_id",
    level_column: str = "disturbance_level",
) -> pd.DataFrame:
    """Añade al resumen el número de celdas de cada nivel por comunidad."""
    require_columns(grid, [id_column, level_column], "cuadrícula clasificada")

    subset = grid[[id_column, level_column]].dropna(subset=[id_column])
    crosstab = pd.crosstab(subset[id_column], subset[level_column])
    crosstab.columns = [f"cells_level_{c}" for c in crosstab.columns]
    crosstab = crosstab.reset_index()

    out = summary.merge(crosstab, on=id_column, how="left")
    level_cols = [c for c in out.columns if c.startswith("cells_level_")]
    out[level_cols] = out[level_cols].fillna(0).astype(int)
    return out
