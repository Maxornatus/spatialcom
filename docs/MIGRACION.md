# Migración: notebook → librería

Equivalencia entre cada celda del flujo original y su reemplazo.

## `clasificacion_comunidades_espacial.ipynb`

| Celda | Función original | Reemplazo |
|---|---|---|
| 1-2 | `clasificacion_composicion_especies_espacial` | `core.composition.delineate_communities` + `Pipeline.step_delineate` |
| 3 | filtro por especie (código suelto) | `core.masking.filter_by_species` |
| 4 | eliminar comunidades urbanas | `core.masking.apply_exclusion_mask` |
| 5 | recalcular conteos | `core.masking.recount_communities` |
| 6-7 | `analizar_deforestacion_por_ano`, `_parse_histogram_categorial` | `core.zonal.zonal_loss_by_year` |
| 8-9 | `clasificar_nivel_deforestacion` | `core.zonal.classify_disturbance_levels` |
| 10-11 | `agregar_niveles_al_csv` | `core.zonal.level_counts_by_community` |
| 13-14 | `crear_dendrograma_comunidades` | `cluster.distance` + `cluster.hierarchical` + `viz.dendrogram.plot_dendrogram` |
| 16 | `analizar_clusters_dendrograma` | `cluster.hierarchical.cluster_communities` |
| 18-19 | `visualizar_clusters_academico` | `cluster.ordination.ordinate` + `viz.dendrogram.plot_ordination` + `viz.tables` |
| 21 | verificación manual de variables | `PipelineState.require` |
| 22, 37 | instrucciones de "reiniciar kernel" | innecesarias: sin estado global |
| 24-25 | `crear_grafo_relaciones` | `viz.network.build_similarity_graph` + `plot_similarity_graph` |
| 27 | `crear_tabla_articulo` (PNG) | `viz.tables.cluster_summary_table` + `export_table` |
| 30 | `vincular_regiones_naturales` | `regions.join.assign_regions` |
| 31 | `analizar_clusters_por_region` | `regions.join.cluster_region_crosstab` |
| 32 | `visualizar_clusters_por_region` | `viz.dendrogram.plot_ordination` por región |
| 33 | `crear_mapa_clusters_por_region` | `regions.join.dominant_cluster_by_region` + `viz.maps.plot_choropleth` |
| 39 | `diagnosticar_vincular_regiones` | `spatialcom validate` |

## Otros archivos

| Origen | Reemplazo |
|---|---|
| `binary_map.py` | `io.rasters.binarize_directory` / `spatialcom binarize` |
| `final_fix.py` | sin equivalente: parcheaba el JSON del notebook |
| `graficas.ipynb::abbreviate_species` | `viz.theme.italic_binomial` |
| `graficas.ipynb::generar_graficos_top6` | `viz.maps.plot_community_panel` |
| `graficas.ipynb::generar_grafico_top_deforestacion` | `viz.tables` + barras sobre `pct_loss_total` |
| `analisis_vectores.ipynb::calcular_exposicion_mosquitos` | `core.indices.point_exposure_index` |
| `dilu_fa/dilucion.ipynb::generar_dataset_riesgo` | `core.indices.trait_weighted_index` |
| `dilu_fa/dilucion.ipynb::generar_tiff_desde_csv_corregido` | pendiente: `io.rasters.rasterize_field` |

## Renombrado de columnas

Los nombres pasan a inglés, en `snake_case` y sin límite de 10 caracteres.

| Antes | Ahora |
|---|---|
| `guid` | `community_id` |
| `lista_especies` | `species_list` |
| `numsp` | `richness` |
| `numero_celdas` | `n_cells` |
| `cell_total_pixels` / `cell_total` | `cell_pixels_total` |
| `cell_deforested_pixels` / `cell_defor` | `cell_pixels_disturbed` |
| `defor_2001` … | `loss_2001` … |
| `perc_2001` … | `pct_2001` … |
| `perc_deforested_total` | `pct_loss_total` |
| `nivel_defor` / `nivel_defo` | `disturbance_level` |
| `defor_perc_celda` | `cell_pct_loss` |
| `celdas_nivel_N` | `cells_level_N` |

Para releer resultados antiguos:

```python
RENAMES = {
    "guid": "community_id", "lista_especies": "species_list",
    "numsp": "richness", "numero_celdas": "n_cells",
    "perc_deforested_total": "pct_loss_total", "nivel_defo": "disturbance_level",
}
df = pd.read_csv("resultados/prueba_10/composicion_especies.csv").rename(columns=RENAMES)
```

Los `guid` antiguos (UUID v4) **no** se pueden reconstruir. Para enlazar resultados
previos, mapee por `species_list`:

```python
from spatialcom import community_id
viejo_a_nuevo = {
    row.guid: community_id(row.lista_especies.split(", "))
    for row in df_viejo.itertuples()
}
```

## Orden de ejecución

El notebook lo documentaba en prosa (celdas 20, 28, 34) y lo verificaba a mano (celda 21).
Ahora lo impone el código:

```
step_delineate → step_exclude → step_disturbance → step_cluster → step_regions → step_ordination
```

`Pipeline.run_all()` los encadena; `spatialcom step --only cluster` ejecuta uno solo y
falla con un mensaje explícito si faltan sus dependencias.
