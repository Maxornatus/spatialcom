"""Delineación de comunidades: composición de especies por unidad espacial.

Reimplementación del algoritmo del notebook `clasificacion_comunidades_espacial`
con dos cambios sustantivos:

1. **Coste computacional.** El original abría cada ráster dentro del bucle de
   celdas: `n_celdas x n_especies` aperturas de archivo y recortes
   (~6.000 x 40 = 240.000 operaciones de E/S). Aquí la cuadrícula se rasteriza
   una vez sobre la malla de referencia y cada ráster se recorre **una sola
   vez** por bloques, acumulando conteos por celda con `np.bincount`. El
   resultado es equivalente; el orden de magnitud del tiempo, no.

2. **Reproducibilidad.** El identificador de comunidad era `uuid.uuid4()`, es
   decir aleatorio: dos ejecuciones sobre los mismos datos producían
   identificadores distintos, lo que impide comparar corridas, versionar
   resultados o citar una comunidad concreta en una publicación. Ahora es un
   hash determinista de la composición ordenada.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.coords
import rasterio.transform
import rasterio.windows
from rasterio import features

from .._logging import get_logger
from ..config import SpeciesConfig
from ..exceptions import RasterError
from ..io.rasters import SpeciesRaster, validate_raster_stack

log = get_logger(__name__)

ID_PREFIX = "C"
ID_LENGTH = 12


def community_id(species: Iterable[str]) -> str:
    """Identificador determinista y estable de una composición de especies.

    El mismo conjunto de especies produce siempre el mismo identificador, en
    cualquier máquina y en cualquier ejecución.

    >>> community_id(["Ateles_hybridus", "Alouatta_seniculus"]) == community_id(
    ...     ["Alouatta_seniculus", "Ateles_hybridus"])
    True
    """
    key = "|".join(sorted(species))
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=16).hexdigest()
    return ID_PREFIX + digest[:ID_LENGTH]


@dataclass(frozen=True, slots=True)
class ReferenceGrid:
    """Malla común sobre la que se superponen rásters de extensiones distintas."""

    transform: rasterio.Affine
    width: int
    height: int
    res: tuple[float, float]


@dataclass(slots=True)
class CommunityResult:
    """Producto de la delineación.

    Attributes
    ----------
    grid:
        Cuadrícula con `community_id`, `richness` y `n_pixels`.
    catalog:
        Una fila por composición única: identificador, lista de especies,
        riqueza y número de celdas ocupadas.
    incidence:
        Matriz booleana comunidad x especie; base del clustering.
    species:
        Nombres de especie en el orden de las columnas de `incidence`.
    """

    grid: gpd.GeoDataFrame
    catalog: pd.DataFrame
    incidence: pd.DataFrame
    species: list[str]

    def __len__(self) -> int:
        return len(self.catalog)


def _presence_mask(counts: np.ndarray, totals: np.ndarray, cfg: SpeciesConfig) -> np.ndarray:
    """Traduce conteos de píxeles a presencia según la regla configurada.

    La regla `any` reproduce el comportamiento del notebook original (un solo
    píxel basta para declarar presencia). Se conserva por comparabilidad, pero
    `min_pixels` o `min_fraction` son defendibles ante un revisor.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        fraction = np.where(totals > 0, counts / totals, 0.0)

    if cfg.presence_rule == "any":
        return counts > 0
    if cfg.presence_rule == "min_pixels":
        return counts >= max(1, cfg.min_pixels)
    if cfg.presence_rule == "min_fraction":
        return fraction >= cfg.min_fraction
    if cfg.presence_rule == "majority":
        return fraction > 0.5
    raise ValueError("Regla de presencia desconocida: " + str(cfg.presence_rule))


def build_reference_grid(
    rasters: list[SpeciesRaster], clip_bounds: tuple | None = None
) -> ReferenceGrid:
    """Malla común que cubre la unión de las extensiones de todos los rásters.

    Los modelos de distribución individuales rara vez comparten extensión: cada
    uno viene recortado a su propia área de estudio. Comparten en cambio
    resolución y alineación de píxel, de modo que existe una malla común a la
    que todos se pueden referir. Trabajar sobre esa malla —y no sobre la del
    primer ráster— es lo que permite superponer especies con recortes distintos.
    """
    lefts, bottoms, rights, tops = [], [], [], []
    with rasters[0].open() as ref:
        res_x, res_y = ref.res
        origin_x, origin_y = ref.transform.c, ref.transform.f

    for r in rasters:
        with r.open() as src:
            b = src.bounds
            lefts.append(b.left)
            bottoms.append(b.bottom)
            rights.append(b.right)
            tops.append(b.top)

    left, bottom = min(lefts), min(bottoms)
    right, top = max(rights), max(tops)

    if clip_bounds is not None:
        left = max(left, clip_bounds[0])
        bottom = max(bottom, clip_bounds[1])
        right = min(right, clip_bounds[2])
        top = min(top, clip_bounds[3])
        if right <= left or top <= bottom:
            raise RasterError(
                "La cuadrícula no se solapa con la extensión de los rásters de especies."
            )

    # Alinear la malla común al enrejado del primer ráster.
    left = origin_x + np.floor((left - origin_x) / res_x) * res_x
    top = origin_y - np.floor((origin_y - top) / res_y) * res_y
    width = int(np.ceil((right - left) / res_x))
    height = int(np.ceil((top - bottom) / res_y))

    transform = rasterio.transform.from_origin(left, top, res_x, res_y)
    log.info(
        "Malla de referencia: %d x %d px, resolución %.6f, extensión (%.4f, %.4f, %.4f, %.4f).",
        height,
        width,
        res_x,
        left,
        top - height * res_y,
        left + width * res_x,
        top,
    )
    return ReferenceGrid(transform=transform, width=width, height=height, res=(res_x, res_y))


def _aligned_window(src, bounds) -> rasterio.windows.Window:
    """Ventana de `src` correspondiente a unos límites geográficos.

    Redondea los desplazamientos al píxel: los rásters están alineados al mismo
    enrejado salvo error de coma flotante (~1e-8 px en este conjunto de datos),
    de modo que el redondeo es exacto y no introduce desplazamiento.
    """
    win = rasterio.windows.from_bounds(*bounds, transform=src.transform)
    return rasterio.windows.Window(
        col_off=int(round(win.col_off)),
        row_off=int(round(win.row_off)),
        width=int(round(win.width)),
        height=int(round(win.height)),
    )


def _cell_pixel_counts(
    grid: gpd.GeoDataFrame,
    rasters: list[SpeciesRaster],
    cfg: SpeciesConfig,
    block_size: int = 1024,
):
    """Cuenta, por celda, píxeles totales y píxeles de presencia de cada especie.

    Recorre la malla común por bloques. Para cada bloque rasteriza una sola vez
    los identificadores de celda y lee de cada especie la ventana correspondiente
    a los **límites geográficos** del bloque, no a un índice de fila/columna: los
    rásters tienen extensiones distintas y un índice compartido los desalinearía.

    Returns
    -------
    counts : ndarray (n_celdas, n_especies) int64
    totals : ndarray (n_celdas,) int64
    """
    n_cells = len(grid)
    # 0 se reserva como "fuera de cuadrícula"; las celdas ocupan 1..n_cells.
    burn_values = np.arange(1, n_cells + 1, dtype=np.int64)
    shapes = list(zip(grid.geometry.to_numpy(), burn_values, strict=True))

    totals = np.zeros(n_cells, dtype=np.int64)
    counts = np.zeros((n_cells, len(rasters)), dtype=np.int64)

    reference = build_reference_grid(rasters, clip_bounds=tuple(grid.total_bounds))

    blocks = [
        (row, col, min(block_size, reference.height - row), min(block_size, reference.width - col))
        for row in range(0, reference.height, block_size)
        for col in range(0, reference.width, block_size)
    ]

    log.info(
        "Delineando comunidades: %d celdas x %d especies en %d bloques.",
        n_cells,
        len(rasters),
        len(blocks),
    )

    open_rasters = [rasterio.open(r.path) for r in rasters]
    try:
        for bi, (row, col, height, width) in enumerate(blocks, start=1):
            block_window = rasterio.windows.Window(col, row, width, height)
            block_transform = rasterio.windows.transform(block_window, reference.transform)
            block_bounds = rasterio.windows.bounds(block_window, reference.transform)

            cell_raster = features.rasterize(
                shapes,
                out_shape=(height, width),
                transform=block_transform,
                fill=0,
                all_touched=cfg.all_touched,
                dtype="int64",
            )
            flat_cells = cell_raster.ravel()
            inside = flat_cells > 0
            if not inside.any():
                log.info("  bloque %d/%d sin celdas, omitido", bi, len(blocks))
                continue

            idx = flat_cells[inside] - 1
            totals += np.bincount(idx, minlength=n_cells)

            for si, src in enumerate(open_rasters):
                if rasterio.coords.disjoint_bounds(block_bounds, src.bounds):
                    continue  # el recorte de esta especie no toca el bloque
                band = src.read(
                    1,
                    window=_aligned_window(src, block_bounds),
                    boundless=True,
                    fill_value=0,
                    out_shape=(height, width),
                )
                present = band.ravel()[inside] == 1
                if present.any():
                    counts[:, si] += np.bincount(idx[present], minlength=n_cells)

            log.info("  bloque %d/%d", bi, len(blocks))
    finally:
        for src in open_rasters:
            src.close()

    if totals.sum() == 0:
        raise RasterError(
            "Ningún píxel cayó dentro de la cuadrícula: revise CRS y extensiones."
        )

    return counts, totals


def delineate_communities(
    grid: gpd.GeoDataFrame,
    rasters: list[SpeciesRaster],
    cfg: SpeciesConfig,
    id_column: str = "community_id",
) -> CommunityResult:
    """Asigna a cada celda la comunidad definida por su composición de especies.

    Parameters
    ----------
    grid:
        Cuadrícula indexada por identificador de celda (ver `io.load_grid`).
    rasters:
        Rásters binarios de presencia/ausencia.
    cfg:
        Regla de presencia y opciones de rasterización.
    id_column:
        Nombre de la columna de identificador de comunidad.
    """
    validate_raster_stack(rasters, target_crs=grid.crs, assume_crs=cfg.assume_crs)

    counts, totals = _cell_pixel_counts(grid, rasters, cfg)
    presence = _presence_mask(counts, totals[:, None], cfg)

    species_names = [r.species for r in rasters]
    species_arr = np.array(species_names)

    compositions = [tuple(species_arr[row].tolist()) for row in presence]
    ids = [community_id(c) if c else None for c in compositions]

    out_grid = grid.copy()
    out_grid[id_column] = ids
    out_grid["richness"] = presence.sum(axis=1).astype("int32")
    out_grid["n_pixels"] = totals

    # --- catálogo de composiciones únicas ---
    seen: dict[str, tuple] = {}
    for cid, comp in zip(ids, compositions, strict=True):
        if comp and cid is not None and cid not in seen:
            seen[cid] = comp

    occupancy = out_grid[id_column].value_counts()
    catalog = (
        pd.DataFrame(
            {
                id_column: list(seen.keys()),
                "species_list": [", ".join(c) for c in seen.values()],
                "richness": [len(c) for c in seen.values()],
            }
        )
        .assign(n_cells=lambda d: d[id_column].map(occupancy).fillna(0).astype(int))
        .sort_values(["richness", "n_cells"], ascending=[False, False])
        .reset_index(drop=True)
    )

    incidence = pd.DataFrame(
        {sp: [sp in seen[cid] for cid in catalog[id_column]] for sp in species_names},
        index=pd.Index(catalog[id_column], name=id_column),
    )

    log.info(
        "Comunidades delineadas: %d composiciones únicas sobre %d celdas ocupadas.",
        len(catalog),
        int(out_grid[id_column].notna().sum()),
    )

    return CommunityResult(
        grid=out_grid, catalog=catalog, incidence=incidence, species=species_names
    )
