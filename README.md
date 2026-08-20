# spatialcom

[![tests](https://github.com/Maxornatus/spatialcom/actions/workflows/tests.yml/badge.svg)](https://github.com/Maxornatus/spatialcom/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/spatialcom.svg)](https://pypi.org/project/spatialcom/)
[![Python](https://img.shields.io/pypi/pyversions/spatialcom.svg)](https://pypi.org/project/spatialcom/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Delineación, clasificación y caracterización de **comunidades espaciales de especies** a
partir de modelos de distribución (SDM) binarios sobre una cuadrícula regular.

Reorganiza como librería instalable y comprobable el flujo desarrollado en
`clasificacion_comunidades_espacial.ipynb`, `graficas.ipynb`, `analisis_vectores.ipynb`,
`dilu_fa/dilucion.ipynb`, `binary_map.py` y `final_fix.py`.

---

## Instalación

Requiere Python 3.10 o superior.

```bash
pip install spatialcom
```

Con figuras y mapa web (recomendado — es lo que usan `run`, `figures` y `webmap`):

```bash
pip install "spatialcom[viz]"
```

En Windows, las dependencias geoespaciales (`geopandas`, `rasterio`, `rasterstats`)
instalan de forma más fiable desde conda-forge; después se instala la librería con pip
dentro de ese entorno:

```bash
conda create -n spatialcom -c conda-forge python=3.11 geopandas rasterio rasterstats
conda activate spatialcom
pip install "spatialcom[viz]"
```

Para trabajar sobre el código (ver [CONTRIBUTING.md](CONTRIBUTING.md)):

```bash
git clone https://github.com/Maxornatus/spatialcom.git
cd spatialcom
pip install -e ".[viz,dev]"
```

---

## Empezar desde cero

```bash
spatialcom init mi_proyecto
```

Crea la estructura de carpetas y un `config.yaml` comentado que documenta qué va en cada
una. A partir de ahí:

```bash
spatialcom make-grid --boundary mi_proyecto/datos/limite/pais.shp \
                     --cell-size 0.1 --out mi_proyecto/datos/cuadricula.gpkg
```

```bash
spatialcom binarize --src mi_proyecto/datos/sdm_continuos \
                    --dst mi_proyecto/datos/sdm_binarios \
                    --thresholds-csv mi_proyecto/datos/umbrales.csv
```

```bash
spatialcom check mi_proyecto/config.yaml
```

```bash
spatialcom run mi_proyecto/config.yaml
```

---

## Datos necesarios

Guía completa —de dónde sale cada capa, cómo descargarla y en qué estado debe llegar— en
**[docs/DATOS.md](docs/DATOS.md)**. Resumen:

| Dato | ¿Obligatorio? | Fuente típica |
|---|---|---|
| Área de estudio | para generar la cuadrícula | GADM, Natural Earth |
| Cuadrícula de análisis | **sí** | `spatialcom make-grid` |
| Modelos de distribución (uno por especie) | **sí** | BioModelos, IUCN, o modelado propio desde GBIF |
| Capa de exclusión (urbano, agua) | no | ESA WorldCover, GHSL |
| Pérdida de cobertura | no | Hansen Global Forest Change |
| Regiones biogeográficas | no | ecorregiones RESOLVE, cartografía nacional |
| Ocurrencias puntuales | no | GBIF |
| Rasgos por especie | no | PanTHERIA, EltonTraits, literatura |

Dos requisitos atraviesan todo: **un solo CRS** para todas las capas, y que los rásters de
especie compartan **resolución y enrejado**. Las extensiones sí pueden diferir entre
especies — cada modelo viene recortado a su propia área.

`spatialcom check` verifica las dos cosas y termina con código 1 si algo obligatorio
falta o no sirve, de modo que funciona como puerta previa en un script.

---

## Comandos

| Comando | Para qué |
|---|---|
| `init <dir>` | Estructura de proyecto y `config.yaml` comentado |
| `make-grid` | Cuadrícula de análisis desde un área de estudio |
| `binarize` | Rásters de idoneidad → presencia/ausencia, con umbral por especie |
| `check <config>` | Inventario de insumos: presencia, CRS, resolución, alineación, solape |
| `validate <config>` | Coherencia de la configuración, sin tocar los datos |
| `run <config>` | Análisis completo |
| `step <config> --only <paso>` | Un paso suelto, reanudando desde disco |
| `figures <config>` | Regenerar solo las figuras estáticas |
| `webmap <config>` | Regenerar solo el mapa HTML |

---

## API

```python
from spatialcom import Config, Pipeline

cfg = Config.from_yaml("mi_proyecto/config.yaml")
pipe = Pipeline(cfg).run_all()
print(pipe.summary())

catalogo = pipe.state.catalog          # una fila por comunidad
clusters = pipe.state.clusters         # linkage, etiquetas, diagnóstico de k
```

### Por componentes, en un notebook exploratorio

```python
from spatialcom.io import load_grid, discover_species_rasters, make_grid_from_file
from spatialcom.core import delineate_communities
from spatialcom.cluster import cluster_communities
from spatialcom.viz.dendrogram import plot_dendrogram
from spatialcom.viz.theme import apply_theme, save_figure

apply_theme()
grid = load_grid("datos/cuadricula.gpkg")
rasters = discover_species_rasters("datos/sdm_binarios")

com = delineate_communities(grid, rasters, cfg.species)
clu = cluster_communities(
    com.incidence, cfg.cluster,
    weights=com.catalog.set_index("community_id")["n_cells"],
)

fig, ax = plot_dendrogram(clu)
save_figure(fig, "figuras/dendrograma", fmt="svg")
```

---

## Figuras

`spatialcom run` genera seis figuras en `figuras/`; `spatialcom figures <config>` las
regenera sin repetir el análisis. Con el extra `viz` ausente el paso se omite con un
aviso, no rompe la corrida.

| Figura | Qué muestra |
|---|---|
| `fig_riqueza_vs_perturbacion` | Riqueza frente a pérdida de cobertura; área del punto = extensión. La recta de tendencia **solo se dibuja si la correlación es significativa** |
| `fig_heatmap_incidencia` | Matriz comunidad x especie con las filas en el orden del dendrograma: hace visibles los bloques de coocurrencia que el árbol solo resume |
| `fig_perturbacion_por_region` | Barras apiladas al 100 % de los niveles de perturbación, contadas por celda |
| `fig_perturbacion_por_cluster` | Lo mismo, por grupo de comunidades |
| `fig_dendrograma` | Dendrograma con el corte y la r cofenética |
| `figS_diagnostico_k` | Silueta frente a k, para justificar el número de grupos |

---

## Mapa interactivo

El paso 7 produce un HTML autónomo que **abre sin conexión** (Leaflet va incrustado, cero
peticiones de red):

- **Pestaña Mapa** — filtros por especie (modo *contiene alguna* / *contiene todas*),
  región, cluster y rango de riqueza. Colorear por riqueza, extensión, cluster, región o
  pérdida de cobertura. Descarga a PNG en 1x/2x/3x, con el encuadre actual, los filtros
  aplicados escritos en la cabecera y la leyenda incluida.
- **Pestaña Gráficas** — top 10 de comunidades por riqueza y por extensión, recalculadas
  con los filtros activos y descargables en SVG o PNG.
- **Pestaña Tabla** — el catálogo de comunidades, ordenable y buscable, con un mínimo de
  celdas propio (2 por omisión, que descarta las de una sola celda) y exportación a CSV.
- **Pestaña Figuras** — las seis figuras estáticas del análisis incrustadas en el propio
  archivo, con pie explicativo y descarga. No reaccionan a los filtros, y el panel se
  atenúa para dejarlo claro. Se desactiva con `webmap.embed_figures: false`.

Detalle en **[docs/MAPA_WEB.md](docs/MAPA_WEB.md)**.

---

## Arquitectura

```
src/spatialcom/
├── config.py        Configuración declarativa validada (YAML -> dataclasses)
├── exceptions.py    Errores tipados; ninguna función devuelve None ante un fallo
├── _logging.py      Logging con niveles, en lugar de print()
│
├── diagnostics.py   Inventario de insumos: presencia, CRS, alineación, solape
│
├── io/              Frontera con el disco
│   ├── grid.py        generación de la cuadrícula desde un área de estudio
│   ├── rasters.py     descubrimiento, validación de stack, binarización
│   ├── vectors.py     carga de cuadrícula y capas, control de CRS
│   └── writers.py     escritura GPKG/Parquet/CSV, validación de esquema
│
├── core/            Análisis, sin efectos de E/S ni gráficos
│   ├── composition.py delineación de comunidades e identificador determinista
│   ├── masking.py     exclusión de celdas y recuento coherente
│   ├── zonal.py       pérdida de cobertura por año y niveles de perturbación
│   └── indices.py     exposición a puntos, índices ponderados por rasgos
│
├── cluster/         Clasificación de comunidades
│   ├── distance.py      distancias Jaccard y matriz de similitud
│   ├── hierarchical.py  enlace, selección de k por silueta, r cofenética
│   └── ordination.py    PCoA, NMDS, PCA, t-SNE
│
├── regions/join.py  Vinculación con regiones naturales (área máxima)
│
├── viz/             Figuras; devuelven (fig, ax), no guardan ni muestran
│   ├── theme.py, dendrogram.py, maps.py, network.py, tables.py
│   ├── charts.py    Riqueza vs perturbación; composición de niveles
│   ├── heatmap.py   Incidencia comunidad x especie ordenada por el dendrograma
│   ├── webmap.py    Mapa HTML autónomo con filtros interactivos
│   └── assets/      Leaflet 1.9.4 incrustado (BSD 2-Clause) para uso offline
│
├── pipeline.py      Orquestación por pasos, con estado explícito
└── cli.py           init / make-grid / binarize / check / validate / run / step / webmap
```

**Regla de dependencias:** `io` → `core` → `cluster` → `viz` → `pipeline` → `cli`.
Ninguna capa importa hacia arriba. `core` y `cluster` no conocen matplotlib ni rutas
de archivo, lo que los hace comprobables sin datos reales.

---

## Salidas del pipeline

Todo se escribe en `output.dir / run_id`, junto a `config_efectiva.yaml` (procedencia).

| Archivo | Contenido |
|---|---|
| `01_cuadricula_comunidades.gpkg` | Celdas con `community_id`, `richness`, `n_pixels` |
| `01_catalogo_comunidades.csv` | Una fila por composición única |
| `02_*` | Versiones tras excluir zonas urbanas |
| `03_cuadricula_perturbacion.gpkg` | `loss_YYYY`, `cell_pct_loss`, `disturbance_level` |
| `03_comunidades_perturbacion.csv` | Agregado por comunidad + `pct_loss_total` |
| `04_comunidades_con_clusters.csv` | Catálogo con la etiqueta de cluster |
| `04_diagnostico_k.csv` | Silueta por k: justifica la elección |
| `04_perfiles_cluster.csv` | Frecuencia de cada especie en cada cluster |
| `05_region_x_cluster.csv` | Tabla región natural x cluster |
| `06_ordenacion.csv` | Coordenadas PCoA por comunidad |
| `07_perturbacion_por_region.csv` | Proporción de celdas en cada nivel de perturbación, por región |
| `07_perturbacion_por_cluster.csv` | Lo mismo, por grupo de comunidades |
| `figuras/` | Figuras del manuscrito en el formato de `output.figure_format` |
| `07_mapa_comunidades.html` | Mapa interactivo con filtros, exportación a PNG y pestaña de gráficas top 10. Abre sin conexión |

---

## Pruebas

```bash
pytest
```

146 pruebas. Construyen rásters y cuadrículas sintéticos en `tmp_path`: se ejecutan en
segundos y no necesitan los datos del proyecto. Incluyen regresiones de los tres defectos
que solo aparecieron al correr sobre los datos reales (ver `docs/VALIDACION.md`).

---

## Documentación adicional

- `docs/DATOS.md` — **qué datos hacen falta y cómo obtenerlos** (GBIF, SDM, Hansen, límites).
- `docs/REVISION_METODOLOGICA.md` — hallazgos de la revisión del flujo original.
- `docs/MIGRACION.md` — equivalencia celda de notebook → función de la librería.
- `docs/VALIDACION.md` — corrida sobre los datos reales y comparación con el notebook.
- `docs/MURCIELAGOS.md` — segunda corrida con 196 especies: dónde deja de discriminar el método.
- `docs/MAPA_WEB.md` — controles del mapa interactivo, tamaño del archivo y modo offline.
- `docs/comparar_con_notebook.py` — script de comparación, reejecutable.
- `configs/` — las configuraciones reales de las dos corridas; ver [`configs/README.md`](configs/README.md).
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — entorno de desarrollo y convenciones del código.
- [`CHANGELOG.md`](CHANGELOG.md) — cambios por versión.
- [`CITATION.cff`](CITATION.cff) — cómo citar la librería.

La corrida `primates_v1` reproduce **exactamente** el resultado del notebook (447
composiciones, 9.568 celdas, sin discrepancias de conteo) en 3 min 30 s, de los cuales la
delineación son 2 segundos.
