"""Inventario y diagnóstico de los datos de entrada.

Responde, antes de gastar minutos de cómputo, a la pregunta práctica: *¿tengo lo
que hace falta y es utilizable?* Revisa presencia, CRS, resolución, alineación y
solape real entre capas, que son los cuatro motivos por los que este tipo de
análisis falla o —peor— produce resultados silenciosamente erróneos.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
import rasterio.crs

from ._logging import get_logger
from .config import Config

log = get_logger(__name__)

OK, AVISO, FALTA, ERROR = "ok", "aviso", "falta", "error"


@dataclass(slots=True)
class Hallazgo:
    """Estado de un insumo del análisis."""

    dataset: str
    obligatorio: bool
    estado: str
    detalle: str

    def as_row(self) -> dict:
        return {
            "dataset": self.dataset,
            "obligatorio": "sí" if self.obligatorio else "opcional",
            "estado": self.estado,
            "detalle": self.detalle,
        }


def _describe_vector(path: Path) -> tuple[str, str, gpd.GeoDataFrame | None]:
    try:
        gdf = gpd.read_file(path, rows=1)
        full = gpd.read_file(path)
    except Exception as exc:  # noqa: BLE001 - se reporta, no se propaga
        return ERROR, f"no se pudo leer: {exc}", None
    if gdf.crs is None:
        return ERROR, "sin CRS definido", full
    return OK, f"{len(full)} geometrías, {gdf.crs}", full


def inventory(cfg: Config) -> pd.DataFrame:
    """Revisa todos los insumos declarados en la configuración.

    Returns
    -------
    DataFrame con una fila por insumo: dataset, si es obligatorio, estado
    (`ok`, `aviso`, `falta`, `error`) y un detalle legible.
    """
    hallazgos: list[Hallazgo] = []
    grid_crs = None
    grid_bounds = None

    # --- cuadrícula ---
    if not cfg.grid.path.exists():
        hallazgos.append(Hallazgo("cuadrícula", True, FALTA, f"no existe: {cfg.grid.path}"))
    else:
        estado, detalle, gdf = _describe_vector(cfg.grid.path)
        if gdf is not None and estado == OK:
            grid_crs, grid_bounds = gdf.crs, gdf.total_bounds
            if cfg.grid.id_column not in gdf.columns:
                detalle += f"; se generará '{cfg.grid.id_column}'"
        hallazgos.append(Hallazgo("cuadrícula", True, estado, detalle))

    # --- rásters de especie ---
    try:
        from .io.rasters import discover_species_rasters

        rasters = discover_species_rasters(
            cfg.species.raster_dir, cfg.species.pattern, cfg.species.name_strip_suffixes
        )
    except Exception as exc:  # noqa: BLE001
        rasters = []
        hallazgos.append(Hallazgo("rásters de especie", True, FALTA, str(exc)))

    if rasters:
        asumido = cfg.species.assume_crs
        perfiles = []
        sin_crs = 0
        for r in rasters:
            with r.open() as src:
                crs = src.crs
                if crs is None:
                    sin_crs += 1
                    if asumido:
                        crs = rasterio.crs.CRS.from_string(asumido)
                perfiles.append((r.species, crs, src.res, src.bounds, src.dtypes[0]))

        if sin_crs and not asumido:
            hallazgos.append(
                Hallazgo(
                    "CRS de los rásters", True, ERROR,
                    f"{sin_crs} de {len(rasters)} rásters no declaran CRS. Indique cuál "
                    "es con species.assume_crs, o asígnelo con 'gdal_edit.py -a_srs'.",
                )
            )
        elif sin_crs:
            hallazgos.append(
                Hallazgo(
                    "CRS de los rásters", True, AVISO,
                    f"{sin_crs} rásters sin CRS; se asume {asumido} por configuración.",
                )
            )

        crs_distintos = {str(p[1]) for p in perfiles}
        res_distintas = {tuple(round(v, 10) for v in p[2]) for p in perfiles}

        detalle = f"{len(rasters)} especies, {perfiles[0][2][0]:.6g} de resolución"
        estado = OK
        if len(crs_distintos) > 1:
            estado, detalle = ERROR, f"CRS distintos entre rásters: {sorted(crs_distintos)}"
        elif len(res_distintas) > 1:
            estado, detalle = ERROR, f"resoluciones distintas: {sorted(res_distintas)}"
        elif grid_crs is not None and str(perfiles[0][1]) != str(grid_crs):
            estado = ERROR
            detalle = f"CRS {perfiles[0][1]} distinto del de la cuadrícula ({grid_crs})"
        hallazgos.append(Hallazgo("rásters de especie", True, estado, detalle))

        # Valores: deben ser binarios.
        with rasters[0].open() as src:
            muestra = src.read(1, out_shape=(1, min(512, src.height), min(512, src.width)))
        valores = set(pd.unique(muestra.ravel()))
        no_binarios = valores - {0, 1, src.nodata if src.nodata is not None else 0}
        if no_binarios:
            hallazgos.append(
                Hallazgo(
                    "binarización",
                    True,
                    AVISO,
                    f"{rasters[0].species} contiene valores fuera de 0/1 "
                    f"({sorted(no_binarios)[:5]}). Ejecute 'spatialcom binarize'.",
                )
            )
        else:
            hallazgos.append(Hallazgo("binarización", True, OK, "valores 0/1"))

        # Alineación de enrejado entre extensiones distintas.
        ref_res, ref_bounds = perfiles[0][2], perfiles[0][3]
        if len(crs_distintos) == 1 and len(res_distintas) == 1:
            desviacion = 0.0
            for _, _, _, b, _ in perfiles:
                dx = (b.left - ref_bounds.left) / ref_res[0]
                dy = (ref_bounds.top - b.top) / ref_res[1]
                desviacion = max(desviacion, abs(dx - round(dx)), abs(dy - round(dy)))
            if desviacion > 1e-3:
                hallazgos.append(
                    Hallazgo(
                        "alineación de rásters",
                        True,
                        ERROR,
                        f"desviación de {desviacion:.3f} px; realinee con 'gdalwarp -tap'",
                    )
                )
            else:
                extensiones = len({tuple(round(v, 6) for v in p[3]) for p in perfiles})
                hallazgos.append(
                    Hallazgo(
                        "alineación de rásters",
                        True,
                        OK,
                        f"{extensiones} extensiones distintas, todas sobre el mismo enrejado",
                    )
                )

    # --- capas opcionales ---
    opcionales = [
        ("máscara de exclusión", cfg.mask.path),
        ("regiones", cfg.regions.path),
    ]
    for nombre, path in opcionales:
        if path is None:
            hallazgos.append(Hallazgo(nombre, False, AVISO, "no configurada; se omitirá el paso"))
            continue
        if not Path(path).exists():
            hallazgos.append(Hallazgo(nombre, False, FALTA, f"no existe: {path}"))
            continue
        estado, detalle, gdf = _describe_vector(Path(path))
        if gdf is not None and grid_bounds is not None and estado == OK:
            try:
                otras = gdf.to_crs(grid_crs) if str(gdf.crs) != str(grid_crs) else gdf
                if not _bounds_overlap(grid_bounds, otras.total_bounds):
                    estado = ERROR
                    detalle += "; NO se solapa con la cuadrícula"
            except Exception:  # noqa: BLE001
                pass
        hallazgos.append(Hallazgo(nombre, False, estado, detalle))

    # --- ráster de perturbación ---
    if cfg.deforestation.raster is None:
        hallazgos.append(
            Hallazgo("perturbación", False, AVISO, "no configurada; se omitirá el paso")
        )
    elif not Path(cfg.deforestation.raster).exists():
        hallazgos.append(
            Hallazgo("perturbación", False, FALTA, f"no existe: {cfg.deforestation.raster}")
        )
    else:
        try:
            with rasterio.open(cfg.deforestation.raster) as src:
                detalle = f"{src.count} banda(s), {src.res[0]:.6g} de resolución, {src.crs}"
                estado = OK
                if grid_bounds is not None and not _bounds_overlap(
                    grid_bounds, tuple(src.bounds)
                ):
                    estado, detalle = ERROR, detalle + "; NO se solapa con la cuadrícula"
        except Exception as exc:  # noqa: BLE001
            estado, detalle = ERROR, f"no se pudo abrir: {exc}"
        hallazgos.append(Hallazgo("perturbación", False, estado, detalle))

    return pd.DataFrame([h.as_row() for h in hallazgos])


def _bounds_overlap(a, b) -> bool:
    """Solape de dos envolventes (minx, miny, maxx, maxy)."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def is_runnable(informe: pd.DataFrame) -> bool:
    """`True` si no hay ningún insumo obligatorio en estado de fallo."""
    fallos = informe[
        (informe["obligatorio"] == "sí") & (informe["estado"].isin([FALTA, ERROR]))
    ]
    return fallos.empty
