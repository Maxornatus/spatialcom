"""Orquestación del análisis completo.

Un `Pipeline` sustituye a la secuencia de celdas del notebook y a su dependencia
de variables globales (`Z`, `mlb`, `matriz_especies`, `pca_model`...). Cada paso
declara sus entradas y persiste sus salidas, de modo que el orden de ejecución
queda garantizado por el código en lugar de por una celda de comprobación y una
instrucción de "reiniciar el kernel".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from ._logging import get_logger, setup_logging
from .cluster.distance import similarity_matrix
from .cluster.hierarchical import ClusterResult, cluster_communities, cluster_profiles
from .cluster.ordination import ordinate
from .config import Config
from .core.composition import delineate_communities
from .core.masking import apply_exclusion_mask, recount_communities
from .core.zonal import (
    classify_disturbance_levels,
    level_counts_by_community,
    zonal_loss_by_year,
)
from .io.rasters import discover_species_rasters
from .io.vectors import load_grid, load_layer
from .io.writers import write_table, write_vector
from .regions.join import assign_regions, cluster_region_crosstab, dominant_cluster_by_region

log = get_logger(__name__)

ID_COLUMN = "community_id"

#: Por encima de este número de comunidades no se escribe la matriz de
#: similitud completa: su tamaño crece con el cuadrado y deja de ser un
#: artefacto útil para convertirse en un problema de disco.
MAX_SIMILARITY_MATRIX = 2000


def _incidence_from_catalog(
    catalog: pd.DataFrame, id_column: str = ID_COLUMN, species_column: str = "species_list"
) -> pd.DataFrame:
    """Reconstruye la matriz de incidencia a partir de las listas de especies."""
    listas = [
        [] if pd.isna(v) else [s.strip() for s in str(v).split(",") if s.strip()]
        for v in catalog[species_column]
    ]
    especies = sorted({s for lista in listas for s in lista})
    data = {sp: [sp in lista for lista in listas] for sp in especies}
    return pd.DataFrame(data, index=pd.Index(catalog[id_column], name=id_column))


@dataclass
class PipelineState:
    """Artefactos producidos por el pipeline, disponibles para inspección."""

    grid: gpd.GeoDataFrame | None = None
    catalog: pd.DataFrame | None = None
    incidence: pd.DataFrame | None = None
    species: list[str] = field(default_factory=list)
    clusters: ClusterResult | None = None
    regions: gpd.GeoDataFrame | None = None
    webmap: Path | None = None
    figures: list[Path] = field(default_factory=list)
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)

    def require(self, *names: str) -> None:
        missing = [n for n in names if getattr(self, n, None) is None]
        if missing:
            raise RuntimeError(
                f"Faltan artefactos {missing}: ejecute antes los pasos que los producen."
            )


class Pipeline:
    """Ejecuta el análisis por pasos, cada uno independiente y reanudable.

    Examples
    --------
    >>> from spatialcom import Config, Pipeline
    >>> cfg = Config.from_yaml("configs/primates_colombia.yaml")  # doctest: +SKIP
    >>> pipe = Pipeline(cfg).run_all()                            # doctest: +SKIP
    >>> pipe.state.catalog.head()                                 # doctest: +SKIP
    """

    def __init__(self, config: Config, log_level: str = "INFO"):
        self.config = config
        self.state = PipelineState()
        setup_logging(log_level)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config.dump(self.run_dir / "config_efectiva.yaml")

    # -- utilidades ------------------------------------------------------
    @property
    def run_dir(self) -> Path:
        return self.config.run_dir

    def _vector(self, gdf: gpd.GeoDataFrame, name: str) -> Path:
        return write_vector(
            gdf,
            self.run_dir / name,
            fmt=self.config.output.vector_format,
            overwrite=True,
        )

    def _table(self, df: pd.DataFrame, name: str) -> Path:
        self.state.tables[name] = df
        return write_table(df, self.run_dir / f"{name}.csv")

    # -- reanudación -----------------------------------------------------
    def resume(self) -> Pipeline:
        """Reconstruye el estado desde los artefactos ya escritos en `run_dir`.

        Permite ejecutar un paso suelto sin repetir la delineación, que es el
        paso caro. Toma siempre la versión más avanzada de cada artefacto: si
        existe `03_cuadricula_perturbacion`, se usa esa y no la `01_`.
        """
        ext = "gpkg" if self.config.output.vector_format == "gpkg" else "parquet"

        grid_candidates = sorted(self.run_dir.glob(f"0*cuadricula*.{ext}"))
        catalog_candidates = sorted(
            list(self.run_dir.glob("0*catalogo*.csv"))
            + list(self.run_dir.glob("0*comunidades*.csv"))
        )
        if not grid_candidates or not catalog_candidates:
            raise RuntimeError(
                f"No hay artefactos que reanudar en {self.run_dir}: ejecute primero "
                "'spatialcom run' o 'spatialcom step --only delineate'."
            )

        grid_path, catalog_path = grid_candidates[-1], catalog_candidates[-1]
        grid = gpd.read_file(grid_path)
        if self.config.grid.id_column in grid.columns:
            grid = grid.set_index(self.config.grid.id_column, drop=False)
        catalog = pd.read_csv(catalog_path)

        self.state.grid = grid
        self.state.catalog = catalog
        self.state.incidence = _incidence_from_catalog(catalog)
        self.state.species = list(self.state.incidence.columns)

        log.info(
            "Estado reanudado desde %s y %s (%d celdas, %d comunidades).",
            grid_path.name,
            catalog_path.name,
            len(grid),
            len(catalog),
        )

        if "cluster" in catalog.columns:
            # El clustering es barato frente a la delineación: se recalcula para
            # recuperar la matriz de enlace y las distancias, que no se persisten.
            log.info("Recalculando el clustering a partir del catálogo reanudado.")
            self.step_cluster()
        return self

    # -- pasos -----------------------------------------------------------
    def step_delineate(self) -> Pipeline:
        """Paso 1. Composición de especies por celda y catálogo de comunidades."""
        cfg = self.config
        grid = load_grid(
            cfg.grid.path,
            id_column=cfg.grid.id_column,
            target_crs=cfg.grid.crs,
            layer=cfg.grid.layer,
        )
        rasters = discover_species_rasters(
            cfg.species.raster_dir, cfg.species.pattern, cfg.species.name_strip_suffixes
        )
        result = delineate_communities(grid, rasters, cfg.species, id_column=ID_COLUMN)

        self.state.grid = result.grid
        self.state.catalog = result.catalog
        self.state.incidence = result.incidence
        self.state.species = result.species

        self._vector(result.grid, "01_cuadricula_comunidades")
        self._table(result.catalog, "01_catalogo_comunidades")
        return self

    def step_exclude(self) -> Pipeline:
        """Paso 2. Exclusión de celdas (zonas urbanas) y recuento coherente.

        Se aplica **antes** del clustering, de modo que dendrograma y análisis
        de perturbación describan exactamente el mismo conjunto de comunidades.
        """
        self.state.require("grid", "catalog")
        if self.config.mask.path is None:
            log.info("Sin capa de exclusión configurada; se omite el paso 2.")
            return self

        mask_layer = load_layer(self.config.mask.path)
        grid = apply_exclusion_mask(
            self.state.grid,
            mask_layer,
            id_column=ID_COLUMN,
            predicate=self.config.mask.predicate,
        )
        grid, catalog = recount_communities(grid, self.state.catalog, id_column=ID_COLUMN)

        self.state.grid, self.state.catalog = grid, catalog
        self.state.incidence = self.state.incidence.loc[catalog[ID_COLUMN]]

        self._vector(grid, "02_cuadricula_filtrada")
        self._table(catalog, "02_catalogo_filtrado")
        return self

    def step_disturbance(self) -> Pipeline:
        """Paso 3. Pérdida de cobertura por año, agregada por comunidad."""
        self.state.require("grid", "catalog")
        if self.config.deforestation.raster is None:
            log.info("Sin ráster de perturbación configurado; se omite el paso 3.")
            return self

        grid, summary = zonal_loss_by_year(
            self.state.grid, self.state.catalog, self.config.deforestation, id_column=ID_COLUMN
        )
        grid = classify_disturbance_levels(grid, self.config.deforestation)
        summary = level_counts_by_community(grid, summary, id_column=ID_COLUMN)

        self.state.grid, self.state.catalog = grid, summary
        self._vector(grid, "03_cuadricula_perturbacion")
        self._table(summary, "03_comunidades_perturbacion")
        return self

    def step_cluster(self) -> Pipeline:
        """Paso 4. Clustering jerárquico con selección diagnosticada de k."""
        self.state.require("incidence", "catalog")
        weights = self.state.catalog.set_index(ID_COLUMN)["n_cells"]
        result = cluster_communities(self.state.incidence, self.config.cluster, weights=weights)
        self.state.clusters = result

        catalog = self.state.catalog.copy()
        catalog["cluster"] = catalog[ID_COLUMN].map(result.labels)
        self.state.catalog = catalog

        profiles = cluster_profiles(self.state.incidence, result.labels, weights=weights)

        self._table(catalog, "04_comunidades_con_clusters")
        self._table(result.diagnostics, "04_diagnostico_k")
        self._table(profiles.reset_index(), "04_perfiles_cluster")

        # La matriz de similitud crece con el cuadrado del número de comunidades:
        # con 7.000 ocupa ~850 MB en CSV y tarda minutos en escribirse. Se emite
        # solo para el subconjunto realmente agrupado y por debajo de un umbral.
        agrupadas = self.state.incidence.loc[result.labels.index]
        if len(agrupadas) <= MAX_SIMILARITY_MATRIX:
            self._table(
                similarity_matrix(agrupadas, self.config.cluster.metric).reset_index(),
                "04_matriz_similitud",
            )
        else:
            log.warning(
                "Matriz de similitud omitida: %d comunidades darían un archivo de "
                "~%.0f MB. Calcúlela bajo demanda con cluster.similarity_matrix, o "
                "suba cluster.min_cells.",
                len(agrupadas), (len(agrupadas) ** 2) * 17 / 1e6,
            )
        return self

    def step_regions(self) -> Pipeline:
        """Paso 5. Vinculación con regiones naturales y tabla región x cluster."""
        self.state.require("grid", "clusters")
        if self.config.regions.path is None:
            log.info("Sin capa de regiones configurada; se omite el paso 5.")
            return self

        regions = load_layer(self.config.regions.path)
        grid = assign_regions(
            self.state.grid,
            regions,
            region_column=self.config.regions.name_column,
            id_column=ID_COLUMN,
        )
        region_column = grid.attrs["region_column"]

        crosstab = cluster_region_crosstab(
            grid, self.state.clusters.labels, region_column, id_column=ID_COLUMN
        )
        dominant = dominant_cluster_by_region(regions, crosstab, region_column)

        self.state.grid = grid
        self.state.regions = dominant

        self._vector(grid, "05_cuadricula_regiones")
        self._vector(dominant, "05_regiones_cluster_dominante")
        self._table(crosstab.reset_index(), "05_region_x_cluster")
        return self

    def step_ordination(self) -> Pipeline:
        """Paso 6. Coordenadas de ordenación para las figuras."""
        self.state.require("incidence", "clusters")
        # Solo las comunidades que entraron al clustering: la matriz de
        # distancias se calculó sobre ese subconjunto, no sobre el catálogo.
        agrupadas = self.state.incidence.loc[self.state.clusters.labels.index]
        ord_result = ordinate(
            agrupadas,
            distance=self.state.clusters.distance,
            method="pcoa",
            random_state=self.config.cluster.random_state,
        )
        coords = ord_result.coords.rename(columns={0: "axis1", 1: "axis2"}).reset_index()
        coords["cluster"] = coords[ID_COLUMN].map(self.state.clusters.labels)
        self._table(coords, "06_ordenacion")
        return self

    def step_figures(self) -> Pipeline:
        """Paso 7. Figuras estáticas para el manuscrito.

        `viz` es una dependencia opcional: si matplotlib no está instalado el
        paso se omite con un aviso en lugar de romper el análisis completo.
        """
        self.state.require("catalog")
        try:
            from .viz.charts import (
                disturbance_composition,
                plot_disturbance_composition,
                plot_richness_vs_disturbance,
            )
            from .viz.dendrogram import plot_dendrogram, plot_k_diagnostics
            from .viz.heatmap import plot_incidence_heatmap
            from .viz.theme import apply_theme, save_figure
        except ImportError as exc:
            log.warning(
                "Figuras omitidas (falta el extra 'viz': pip install 'spatialcom[viz]'): %s",
                exc,
            )
            return self

        apply_theme()
        destino = self.run_dir / "figuras"
        fmt = self.config.output.figure_format
        catalog = self.state.catalog
        generadas: list[Path] = []

        def guardar(fig, nombre: str) -> None:
            generadas.append(save_figure(fig, destino / nombre, fmt=fmt,
                                         dpi=self.config.output.dpi))

        # Riqueza frente a perturbación.
        if "pct_loss_total" in catalog.columns:
            fig, _ = plot_richness_vs_disturbance(
                catalog,
                color_by="cluster" if "cluster" in catalog.columns else None,
                annotate_top=3,
            )
            guardar(fig, "fig_riqueza_vs_perturbacion")

        if self.state.clusters is not None:
            pesos = catalog.set_index(ID_COLUMN)["n_cells"]

            fig, _ = plot_dendrogram(self.state.clusters, truncate_at=40)
            guardar(fig, "fig_dendrograma")

            fig, _ = plot_k_diagnostics(self.state.clusters)
            guardar(fig, "figS_diagnostico_k")

            # Solo las comunidades agrupadas: el orden de filas sale del
            # dendrograma, que se construyó sobre ese subconjunto.
            fig, _ = plot_incidence_heatmap(
                self.state.incidence.loc[self.state.clusters.labels.index],
                self.state.clusters,
                weights=pesos,
            )
            guardar(fig, "fig_heatmap_incidencia")

        # Composición de la perturbación, contada por celda.
        grid = self.state.grid
        if grid is not None and "disturbance_level" in grid.columns:
            # Solo celdas con comunidad: es el hábitat que describe el análisis.
            ocupadas = grid[grid[ID_COLUMN].notna()]

            region_column = grid.attrs.get("region_column") or next(
                (c for c in grid.columns if "region" in c.lower()), None
            )
            if region_column:
                tabla = disturbance_composition(ocupadas, region_column)
                fig, _ = plot_disturbance_composition(
                    tabla, title="Perturbación por región natural"
                )
                guardar(fig, "fig_perturbacion_por_region")
                self._table(tabla.reset_index(), "07_perturbacion_por_region")

            if self.state.clusters is not None:
                por_cluster = ocupadas.copy()
                por_cluster["cluster"] = por_cluster[ID_COLUMN].map(
                    self.state.clusters.labels
                )
                tabla = disturbance_composition(por_cluster, "cluster")
                fig, _ = plot_disturbance_composition(
                    tabla, title="Perturbación por grupo de comunidades"
                )
                guardar(fig, "fig_perturbacion_por_cluster")
                self._table(tabla.reset_index(), "07_perturbacion_por_cluster")

        self.state.figures = generadas
        log.info("Figuras generadas: %d en %s", len(generadas), destino)
        return self

    def step_webmap(self) -> Pipeline:
        """Paso 8. Mapa HTML interactivo con filtros por especie, región y cluster."""
        self.state.require("grid", "catalog")
        cfg = self.config.webmap
        if not cfg.enabled:
            log.info("Mapa web desactivado en la configuración; se omite el paso 7.")
            return self

        from .viz.webmap import build_webmap  # viz es opcional

        # `attrs` no sobrevive a una ida y vuelta por disco, así que al reanudar
        # el nombre de la columna de región se vuelve a deducir de la cuadrícula.
        region_column = self.state.grid.attrs.get("region_column")
        if region_column is None:
            region_column = self.config.regions.name_column
        if region_column is None:
            candidates = [c for c in self.state.grid.columns if "region" in c.lower()]
            region_column = candidates[0] if candidates else None
        if region_column is None:
            log.info("Sin columna de región: el mapa se genera sin filtro regional.")

        # Contorno de referencia: la capa indicada, o las regiones naturales si
        # ya están configuradas. Es lo que da contexto geográfico sin teselas.
        context_path = cfg.context_path or self.config.regions.path
        context = None
        if context_path is not None and Path(context_path).exists():
            context = load_layer(context_path)

        path = build_webmap(
            self.state.grid,
            self.state.catalog,
            self.run_dir / cfg.filename,
            id_column=ID_COLUMN,
            region_column=region_column,
            title=cfg.title,
            subtitle=cfg.subtitle
            or f"{len(self.state.catalog)} comunidades · {self.config.run_id}",
            simplify_tolerance=cfg.simplify_tolerance,
            coord_precision=cfg.coord_precision,
            basemap=cfg.basemap,
            leaflet=cfg.leaflet,
            context=context,
            # Las figuras del paso 7 se incrustan como tercera pestaña.
            figures=(self.run_dir / "figuras") if cfg.embed_figures else None,
        )
        self.state.webmap = path
        return self

    def run_all(self) -> Pipeline:
        """Ejecuta la secuencia completa en el orden correcto."""
        log.info("=== Inicio del análisis '%s' ===", self.config.run_id)
        (
            self.step_delineate()
            .step_exclude()
            .step_disturbance()
            .step_cluster()
            .step_regions()
            .step_ordination()
            .step_figures()
            .step_webmap()
        )
        log.info("=== Análisis completado. Resultados en %s ===", self.run_dir)
        return self

    def summary(self) -> dict[str, Any]:
        """Métricas de cierre, útiles para el apartado de resultados."""
        s = self.state
        out: dict[str, Any] = {"run_id": self.config.run_id, "output_dir": str(self.run_dir)}
        if s.catalog is not None:
            out |= {
                "n_communities": len(s.catalog),
                "n_species": len(s.species),
                "cells_occupied": int(s.catalog["n_cells"].sum()),
                "richness_max": int(s.catalog["richness"].max()),
            }
        if s.clusters is not None:
            out |= {"k": s.clusters.k, "cophenetic_r": round(s.clusters.cophenetic_r, 3)}
        if s.webmap is not None:
            out["webmap"] = str(s.webmap)
        if s.figures:
            out["figures"] = len(s.figures)
        return out
