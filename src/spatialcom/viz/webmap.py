"""Mapa web interactivo de comunidades, con filtros por especie, región y cluster.

Produce un único archivo HTML autónomo: los datos van embebidos, de modo que se
puede abrir con doble clic, adjuntar a un correo o subir como material
suplementario sin servidor ni dependencias de datos.

El tamaño se controla en tres pasos: se disuelven las celdas por comunidad (de
~9.700 polígonos a unos cientos), se simplifican las geometrías y se redondean
las coordenadas. Los atributos no se repiten por geometría: cada rasgo apunta
por índice a una tabla de comunidades, y las especies se codifican como índices
sobre una lista única.

Leaflet viene incluido en el paquete y se incrusta en el HTML, así que el mapa
abre sin conexión. `leaflet="cdn"` produce un archivo ~160 KB más pequeño a
cambio de depender de la red al abrirlo.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .._logging import get_logger
from ..exceptions import SchemaError
from .theme import CLUSTER_PALETTE

log = get_logger(__name__)

_TEMPLATE = Path(__file__).with_name("webmap_template.html")

#: Versión de Leaflet incluida en el paquete (ver `assets/leaflet/PROCEDENCIA.md`).
LEAFLET_VERSION = "1.9.4"
BUNDLED_LEAFLET = Path(__file__).parent / "assets" / "leaflet"

#: Proveedores de teselas. La URL solo llega al HTML si se elige un mapa base,
#: de modo que con `basemap="none"` el archivo no contiene ninguna dirección
#: externa que un revisor pueda confundir con una dependencia de red.
TILE_PROVIDERS = {
    "carto": {
        "url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attribution": "&copy; OpenStreetMap, &copy; CARTO",
        "maxZoom": 12,
    },
    "osm": {
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": (
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        ),
        "maxZoom": 12,
    },
}

#: Rampas secuenciales para las variables continuas (ColorBrewer / viridis).
COLOR_RAMPS = {
    "richness": ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"],
    "loss": ["#ffffb2", "#fed976", "#feb24c", "#fd8d3c", "#f03b20", "#bd0026"],
    "cells": ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
}


def _round_coords(obj, precision: int):
    """Redondea recursivamente las coordenadas de una geometría GeoJSON.

    `__geo_interface__` devuelve un diccionario cuyo campo `coordinates` anida
    tuplas: hay que descender por el diccionario, no solo por las secuencias.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return round(obj, precision)
    if isinstance(obj, dict):
        return {k: _round_coords(v, precision) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_coords(v, precision) for v in obj]
    return obj


def build_payload(
    grid: gpd.GeoDataFrame,
    catalog: pd.DataFrame,
    id_column: str = "community_id",
    region_column: str | None = None,
    simplify_tolerance: float = 0.002,
    coord_precision: int = 4,
) -> dict:
    """Construye la estructura de datos que se incrusta en el HTML.

    Las celdas se disuelven por pareja (comunidad, región): así el filtro
    regional recorta la geometría realmente contenida en esa región, en vez de
    mostrar la comunidad entera cuando solo una parte cae dentro.
    """
    if id_column not in grid.columns:
        raise SchemaError(f"La cuadrícula no tiene la columna '{id_column}'.")
    if "species_list" not in catalog.columns:
        raise SchemaError("El catálogo no tiene la columna 'species_list'.")

    work = grid[grid[id_column].notna()].copy()
    if work.empty:
        raise SchemaError("Ninguna celda tiene comunidad asignada.")

    if region_column and region_column in work.columns:
        work["_region"] = work[region_column].fillna("sin región")
    else:
        work["_region"] = "sin región"
        region_column = None

    if work.crs is not None and work.crs.to_epsg() != 4326:
        log.info("Reproyectando a EPSG:4326 para el mapa web.")
        work = work.to_crs(4326)

    # --- tabla de comunidades ---
    cat = catalog.copy()
    species_lists = [
        [] if pd.isna(v) else [s.strip() for s in str(v).split(",") if s.strip()]
        for v in cat["species_list"]
    ]
    species = sorted({s for lst in species_lists for s in lst})
    species_index = {s: i for i, s in enumerate(species)}

    cells_by_community = work.groupby(id_column).size()
    regions_present = work.groupby(id_column)["_region"].unique()

    region_names = sorted(work["_region"].unique())
    region_index = {r: i for i, r in enumerate(region_names)}

    communities = []
    community_index: dict[str, int] = {}
    for pos, (cid, sp_list) in enumerate(zip(cat[id_column], species_lists, strict=True)):
        community_index[cid] = pos
        entry = {
            "id": str(cid),
            "sp": [species_index[s] for s in sp_list],
            "r": int(len(sp_list)),
            "n": int(cells_by_community.get(cid, 0)),
            "reg": sorted(region_index[r] for r in regions_present.get(cid, [])),
        }
        if "cluster" in cat.columns:
            value = cat["cluster"].iloc[pos]
            entry["k"] = None if pd.isna(value) else int(value)
        if "pct_loss_total" in cat.columns:
            value = cat["pct_loss_total"].iloc[pos]
            entry["loss"] = None if pd.isna(value) else round(float(value), 2)
        communities.append(entry)

    # --- geometrías disueltas ---
    dissolved = work.dissolve(by=[id_column, "_region"]).reset_index()
    if simplify_tolerance > 0:
        dissolved["geometry"] = dissolved.geometry.simplify(
            simplify_tolerance, preserve_topology=True
        )
    dissolved = dissolved[~dissolved.geometry.is_empty & dissolved.geometry.notna()]

    # Celdas de cada segmento (comunidad ∩ región). Sin esto, al filtrar por
    # región el contador sumaría la extensión completa de cada comunidad,
    # incluida la parte que cae fuera de la región seleccionada.
    segment_cells = work.groupby([id_column, "_region"]).size()

    features = []
    for cid, region, geom in zip(
        dissolved[id_column], dissolved["_region"], dissolved.geometry
    , strict=True):
        if cid not in community_index:
            continue  # comunidad presente en la cuadrícula pero no en el catálogo
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "c": community_index[cid],
                    "g": region_index[region],
                    "n": int(segment_cells.get((cid, region), 0)),
                },
                "geometry": _round_coords(geom.__geo_interface__, coord_precision),
            }
        )

    bounds = dissolved.total_bounds
    payload = {
        "species": species,
        "regions": region_names,
        "regionColumn": region_column,
        "communities": communities,
        "features": {"type": "FeatureCollection", "features": features},
        "bounds": [
            [float(bounds[1]), float(bounds[0])],
            [float(bounds[3]), float(bounds[2])],
        ],
        "palette": CLUSTER_PALETTE,
        "ramps": COLOR_RAMPS,
        "hasCluster": "cluster" in cat.columns,
        "hasLoss": "pct_loss_total" in cat.columns,
    }
    log.info(
        "Datos del mapa: %d comunidades, %d segmentos, %d especies, %d regiones.",
        len(communities),
        len(features),
        len(species),
        len(region_names),
    )
    return payload


#: Títulos y pies legibles para las figuras conocidas. **El orden de este
#: diccionario es el orden en que se presentan**: primero cómo se construyeron
#: los grupos, luego qué contienen, luego cómo se relacionan con la
#: perturbación. Las suplementarias van al final. Una figura que no esté aquí
#: recibe un título derivado del nombre de archivo y se ordena después.
FIGURE_CAPTIONS: dict[str, tuple[str, str]] = {
    "fig_dendrograma": (
        "Dendrograma jerárquico",
        "Agrupación de comunidades por similitud de composición; la línea discontinua "
        "marca el corte.",
    ),
    "fig_heatmap_incidencia": (
        "Incidencia por comunidad",
        "Matriz comunidad x especie con las filas en el orden del dendrograma. Los "
        "bloques de color son los grupos del clustering.",
    ),
    "fig_riqueza_vs_perturbacion": (
        "Riqueza frente a pérdida de cobertura",
        "Cada punto es una comunidad; el área del punto es su extensión. La recta de "
        "tendencia solo aparece si la correlación de Spearman es significativa.",
    ),
    "fig_perturbacion_por_region": (
        "Perturbación por región natural",
        "Proporción de celdas en cada nivel de pérdida de cobertura, contada por celda.",
    ),
    "fig_perturbacion_por_cluster": (
        "Perturbación por grupo de comunidades",
        "La misma composición, agrupada por el cluster de cada comunidad.",
    ),
    "figS_diagnostico_k": (
        "Suplementaria · selección del número de grupos",
        "Silueta media para cada k. Justifica el número de clusters elegido.",
    ),
}

#: Extensiones admitidas, en orden de preferencia.
FIGURE_FORMATS = (".svg", ".png", ".jpg", ".jpeg", ".webp")


def collect_figures(
    source: str | Path | list, max_total_mb: float = 8.0
) -> list[dict]:
    """Prepara las figuras estáticas para incrustarlas en el HTML.

    Cada figura se codifica como data URI dentro de un `<img>`, no como SVG en
    línea: así cada una conserva su propio espacio de identificadores y su
    propio CSS. Matplotlib genera identificadores de glifo y de recorte que
    colisionarían entre figuras al fusionarlas en un mismo documento.

    Parameters
    ----------
    source:
        Carpeta con las figuras, o una lista de rutas.
    max_total_mb:
        Aviso si el conjunto supera este tamaño; no se interrumpe, porque el
        usuario puede querer un archivo grande a propósito.

    Returns
    -------
    Lista de diccionarios con `slug`, `title`, `caption`, `mime`, `data`
    (base64) y `filename`.
    """
    if isinstance(source, (str, Path)):
        directorio = Path(source)
        if not directorio.is_dir():
            log.info("Sin carpeta de figuras en %s; el mapa no llevará pestaña.", directorio)
            return []
        rutas = [
            p for ext in FIGURE_FORMATS for p in sorted(directorio.glob(f"*{ext}"))
        ]
    else:
        rutas = [Path(p) for p in source]

    # Una sola versión por figura: si existe el SVG, se descarta el PNG gemelo.
    por_nombre: dict[str, Path] = {}
    for ruta in rutas:
        if not ruta.exists():
            log.warning("Figura no encontrada, se omite: %s", ruta)
            continue
        actual = por_nombre.get(ruta.stem)
        if actual is None or FIGURE_FORMATS.index(
            ruta.suffix.lower()
        ) < FIGURE_FORMATS.index(actual.suffix.lower()):
            por_nombre[ruta.stem] = ruta

    # Orden narrativo: el de FIGURE_CAPTIONS primero, el resto alfabético al
    # final. Ordenar por nombre de archivo pondría la suplementaria la primera.
    orden = list(FIGURE_CAPTIONS)

    def posicion(slug: str) -> tuple[int, str]:
        return (orden.index(slug) if slug in orden else len(orden), slug)

    figuras: list[dict] = []
    total = 0
    for slug, ruta in sorted(por_nombre.items(), key=lambda kv: posicion(kv[0])):
        datos = ruta.read_bytes()
        total += len(datos)
        titulo, pie = FIGURE_CAPTIONS.get(
            slug, (slug.replace("_", " ").capitalize(), "")
        )
        figuras.append(
            {
                "slug": slug,
                "title": titulo,
                "caption": pie,
                "filename": ruta.name,
                "mime": mimetypes.guess_type(ruta.name)[0] or "image/png",
                "data": base64.b64encode(datos).decode("ascii"),
            }
        )

    if total / 1e6 > max_total_mb:
        log.warning(
            "Las figuras suman %.1f MB; el HTML resultante será grande. "
            "Genere las figuras en PNG (output.figure_format) o reduzca cuáles se "
            "incrustan.",
            total / 1e6,
        )
    log.info("Figuras incrustadas: %d (%.1f MB)", len(figuras), total / 1e6)
    return figuras


def _inline_css_images(css: str, base_dir: Path) -> str:
    """Sustituye `url(images/x.png)` por data URI.

    La hoja de estilos de Leaflet referencia tres imágenes. Al incrustar el CSS
    en un `<style>`, esas rutas relativas se resolverían respecto al HTML y
    provocarían peticiones fallidas; como data URI el archivo queda cerrado
    sobre sí mismo.
    """

    def replace(match: re.Match) -> str:
        ref = match.group(1).strip("'\"")
        if ref.startswith(("data:", "http:", "https:", "#")):
            return match.group(0)
        asset = base_dir / ref
        if not asset.exists():
            log.warning("Recurso de Leaflet no encontrado, se omite: %s", ref)
            return "none"
        mime = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        data = base64.b64encode(asset.read_bytes()).decode("ascii")
        return f"url(data:{mime};base64,{data})"

    return re.sub(r"url\(([^)]+)\)", replace, css)


def _leaflet_assets(source: str | Path) -> tuple[str, str]:
    """Devuelve las etiquetas de estilo y script de Leaflet.

    `source` acepta:

    * ``"bundled"`` — la copia incluida en el paquete (por omisión). El HTML
      resultante no necesita conexión para cargar Leaflet.
    * ``"cdn"`` — enlaces a unpkg; archivo más pequeño, pero requiere conexión
      al abrirlo.
    * una ruta a una carpeta con `leaflet.css` y `leaflet.js` propios.
    """
    if str(source).lower() == "cdn":
        base = f"https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/"
        log.info("Leaflet desde CDN: el mapa requerirá conexión al abrirse.")
        return (
            f'<link rel="stylesheet" href="{base}leaflet.css">',
            f'<script src="{base}leaflet.js"></script>',
        )

    directory = BUNDLED_LEAFLET if str(source).lower() == "bundled" else Path(source)
    css_path, js_path = directory / "leaflet.css", directory / "leaflet.js"
    missing = [p.name for p in (css_path, js_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Faltan {missing} en {directory}")

    css = _inline_css_images(css_path.read_text(encoding="utf-8"), directory)
    # El comentario sourceMappingURL apunta a leaflet.js.map, que no se incluye:
    # dejarlo provocaría una petición fallida al abrir las herramientas del navegador.
    js = re.sub(r"//# sourceMappingURL=\S+\s*$", "", js_path.read_text(encoding="utf-8"))

    log.info("Leaflet incrustado desde %s: el mapa funciona sin conexión.", directory)
    return ("<style>" + css + "</style>", "<script>" + js + "</script>")


def context_geojson(
    layers: gpd.GeoDataFrame | None,
    simplify_tolerance: float = 0.01,
    coord_precision: int = 3,
) -> dict | None:
    """Contorno de referencia embebido, para que el mapa se lea sin teselas.

    Sin conexión no hay mapa base, y las comunidades quedarían flotando sobre un
    fondo vacío. Un contorno simplificado de las regiones o del país da la
    referencia geográfica mínima sin ninguna petición externa.
    """
    if layers is None or layers.empty:
        return None

    ctx = layers[["geometry"]].copy()
    if ctx.crs is not None and ctx.crs.to_epsg() != 4326:
        ctx = ctx.to_crs(4326)
    if simplify_tolerance > 0:
        ctx["geometry"] = ctx.geometry.simplify(simplify_tolerance, preserve_topology=True)
    ctx = ctx[~ctx.geometry.is_empty & ctx.geometry.notna()]

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": _round_coords(geom.__geo_interface__, coord_precision),
            }
            for geom in ctx.geometry
        ],
    }


def build_webmap(
    grid: gpd.GeoDataFrame,
    catalog: pd.DataFrame,
    path: str | Path,
    id_column: str = "community_id",
    region_column: str | None = None,
    title: str = "Comunidades de especies",
    subtitle: str = "",
    simplify_tolerance: float = 0.002,
    coord_precision: int = 4,
    basemap: str = "carto",
    leaflet: str | Path = "bundled",
    context: gpd.GeoDataFrame | None = None,
    figures: str | Path | list | None = None,
) -> Path:
    """Escribe el mapa interactivo y devuelve la ruta del HTML generado.

    Parameters
    ----------
    grid, catalog:
        Cuadrícula con comunidad asignada y catálogo de comunidades.
    region_column:
        Columna de región para el filtro; `None` desactiva ese filtro.
    simplify_tolerance:
        Tolerancia de simplificación en unidades del CRS (grados para EPSG:4326).
        0 conserva la geometría exacta a costa del tamaño del archivo.
    basemap:
        `carto`, `osm` o `none`. Con `none` no se solicitan teselas.
    leaflet:
        `bundled` (por omisión) incrusta la copia que trae el paquete y el mapa
        abre sin conexión; `cdn` enlaza a unpkg y produce un archivo ~160 KB más
        pequeño pero dependiente de la red; también acepta la ruta a una carpeta
        con `leaflet.css` y `leaflet.js` propios.
    context:
        Capa de contorno (regiones, país) que se embebe como referencia
        geográfica. Es lo que hace legible el mapa cuando no hay teselas.
    figures:
        Carpeta o lista de figuras estáticas a incrustar como tercera pestaña.
        `None` omite la pestaña.
    """
    payload = build_payload(
        grid,
        catalog,
        id_column=id_column,
        region_column=region_column,
        simplify_tolerance=simplify_tolerance,
        coord_precision=coord_precision,
    )
    if basemap not in TILE_PROVIDERS and basemap != "none":
        raise ValueError(
            f"Mapa base desconocido: {basemap}. Use {sorted(TILE_PROVIDERS)} o 'none'."
        )
    payload["tiles"] = TILE_PROVIDERS.get(basemap)
    payload["figures"] = collect_figures(figures) if figures is not None else []
    payload["context"] = context_geojson(context)
    payload["offline"] = str(leaflet).lower() != "cdn" and basemap == "none"

    css_tag, js_tag = _leaflet_assets(leaflet)
    html = _TEMPLATE.read_text(encoding="utf-8")
    html = (
        html.replace("/*__LEAFLET_CSS__*/", css_tag)
        .replace("/*__LEAFLET_JS__*/", js_tag)
        .replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace(
            "/*__DATA__*/",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    )

    path = Path(path).with_suffix(".html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    log.info(
        "Mapa web escrito: %s (%.1f MB)%s",
        path.name,
        path.stat().st_size / 1e6,
        " — sin peticiones externas" if payload["offline"] else "",
    )
    return path
