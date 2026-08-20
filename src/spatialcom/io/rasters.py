"""Descubrimiento, validación y binarización de rásters de distribución."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling

from .._logging import get_logger
from ..exceptions import RasterError

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SpeciesRaster:
    """Un ráster de distribución asociado a un nombre de especie normalizado."""

    species: str
    path: Path

    def open(self):
        return rasterio.open(self.path)


def normalize_species_name(filename: str, strip_suffixes: tuple[str, ...] = ()) -> str:
    """`Alouatta_seniculus_binario.tif` -> `Alouatta_seniculus`."""
    stem = Path(filename).stem
    for suf in strip_suffixes:
        if stem.endswith(suf):
            stem = stem[: -len(suf)]
    return stem.strip("_")


def discover_species_rasters(
    raster_dir: str | Path,
    pattern: str = "*.tif",
    strip_suffixes: tuple[str, ...] = ("_binario",),
) -> list[SpeciesRaster]:
    """Lista los rásters de especie ordenados alfabéticamente y sin duplicados."""
    raster_dir = Path(raster_dir)
    paths = sorted(p for p in raster_dir.glob(pattern) if p.suffix.lower() in {".tif", ".tiff"})
    if not paths:
        raise RasterError(f"No se encontraron rásters con patrón '{pattern}' en {raster_dir}")

    rasters: list[SpeciesRaster] = []
    seen: dict[str, Path] = {}
    for p in paths:
        name = normalize_species_name(p.name, strip_suffixes)
        if name in seen:
            raise RasterError(
                f"Nombre de especie duplicado '{name}': {seen[name].name} y {p.name}"
            )
        seen[name] = p
        rasters.append(SpeciesRaster(species=name, path=p))

    log.info("Rásters de especie detectados: %d", len(rasters))
    return rasters


def validate_raster_stack(
    rasters: list[SpeciesRaster], target_crs=None, assume_crs: str | None = None
) -> dict:
    """Verifica CRS, resolución y alineación comunes.

    El notebook original solo emitía un aviso y continuaba; una discrepancia de
    CRS invalida por completo la superposición.

    `assume_crs` cubre un caso real y frecuente: los rásters de MaxEnt se
    escriben a menudo sin CRS. Se aplica **solo** a los que no declaran
    ninguno, nunca sobre uno existente, y se comprueba que las coordenadas sean
    plausibles para ese sistema antes de aceptarlo.
    """
    profiles = []
    for r in rasters:
        with r.open() as src:
            crs = src.crs
            if crs is None and assume_crs:
                crs = rasterio.crs.CRS.from_string(assume_crs)
            profiles.append(
                {
                    "species": r.species,
                    "crs": crs,
                    "res": tuple(round(v, 10) for v in src.res),
                    "bounds": tuple(round(v, 6) for v in src.bounds),
                    "dtype": src.dtypes[0],
                    "nodata": src.nodata,
                }
            )

    ref = profiles[0]
    problems = []
    res_x, res_y = ref["res"]

    sin_crs = [p["species"] for p in profiles if p["crs"] is None]
    if sin_crs:
        problems.append(
            f"{len(sin_crs)} ráster(s) sin CRS declarado (p.ej. {sin_crs[0]}). "
            "Declárelo con species.assume_crs si sabe cuál es, o asígnelo con "
            "'gdal_edit.py -a_srs EPSG:XXXX'."
        )
    elif assume_crs:
        # Comprobación de plausibilidad: unas coordenadas fuera del dominio del
        # CRS asumido delatarían una suposición equivocada.
        asumido = rasterio.crs.CRS.from_string(assume_crs)
        if asumido.is_geographic:
            left, bottom, right, top = ref["bounds"]
            if not (-180.5 <= left <= 180.5 and -90.5 <= bottom <= 90.5
                    and -180.5 <= right <= 180.5 and -90.5 <= top <= 90.5):
                problems.append(
                    f"Se asumió {assume_crs} (geográfico) pero la extensión "
                    f"{ref['bounds']} no son grados. Revise species.assume_crs."
                )
        log.warning(
            "CRS asumido para %d ráster(s) sin CRS declarado: %s. "
            "Es una suposición del usuario, no un dato del archivo.",
            len(profiles), assume_crs,
        )
    for prof in profiles[1:]:
        if prof["crs"] != ref["crs"]:
            problems.append(f"{prof['species']}: CRS {prof['crs']} != {ref['crs']}")
        if prof["res"] != ref["res"]:
            problems.append(f"{prof['species']}: resolución {prof['res']} != {ref['res']}")
            continue
        # Las extensiones pueden diferir —cada SDM trae su propio recorte— pero
        # los píxeles deben caer sobre el mismo enrejado, o la superposición
        # quedaría desplazada media celda.
        off_x = (prof["bounds"][0] - ref["bounds"][0]) / res_x
        off_y = (ref["bounds"][3] - prof["bounds"][3]) / res_y
        drift = max(abs(off_x - round(off_x)), abs(off_y - round(off_y)))
        if drift > 1e-3:
            problems.append(
                f"{prof['species']}: píxeles desalineados respecto a {ref['species']} "
                f"({drift:.4f} px). Realinee con gdalwarp -tap."
            )

    if target_crs is not None and str(ref["crs"]) != str(target_crs):
        problems.append(f"CRS de rásters ({ref['crs']}) != CRS de la cuadrícula ({target_crs})")

    if problems:
        raise RasterError(
            "Los rásters no son comparables entre sí:\n  - " + "\n  - ".join(problems)
        )

    log.info("Stack validado: CRS %s, resolución %s", ref["crs"], ref["res"])
    return ref


def binarize_directory(
    src_dir: str | Path,
    dst_dir: str | Path,
    thresholds: dict[str, float] | float = 0.5,
    strip_suffixes: tuple[str, ...] = (),
    suffix: str = "_binario",
    overwrite: bool = False,
) -> list[SpeciesRaster]:
    """Convierte rásters continuos de idoneidad en binarios de presencia/ausencia.

    Sustituye a `binary_map.py`. Diferencias con el script original:

    * Acepta un umbral **por especie** (`{"Alouatta_seniculus": 0.42, ...}`),
      que es lo que exige la práctica estándar en SDM (maxTSS, 10-percentile
      training presence, etc.), en vez de 0.5 para todas.
    * El enmascarado de NoData se aplica **antes** de escribir. En el script
      original la línea que ponía a 0 los píxeles NoData se ejecutaba después
      de `WriteArray`, por lo que no tenía ningún efecto sobre el archivo.
    * Usa rasterio en lugar de bindings de GDAL, eliminando una dependencia.
    """
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)

    out: list[SpeciesRaster] = []
    for src_path in sorted(src_dir.glob("*.tif")) + sorted(src_dir.glob("*.tiff")):
        species = normalize_species_name(src_path.name, strip_suffixes)
        thr = thresholds[species] if isinstance(thresholds, dict) else float(thresholds)
        dst_path = dst_dir / f"{species}{suffix}.tif"

        if dst_path.exists() and not overwrite:
            log.debug("Ya existe, se omite: %s", dst_path.name)
            out.append(SpeciesRaster(species, dst_path))
            continue

        with rasterio.open(src_path) as src:
            data = src.read(1, masked=True)
            binary = np.where(data.filled(np.nan) > thr, 1, 0).astype("uint8")
            # NoData -> ausencia, aplicado antes de escribir.
            binary[np.ma.getmaskarray(data)] = 0

            profile = src.profile
            profile.update(dtype="uint8", count=1, nodata=255, compress="deflate", tiled=True)

        with rasterio.open(dst_path, "w", **profile) as dst:
            dst.write(binary, 1)
            dst.update_tags(species=species, threshold=str(thr), source=src_path.name)

        log.info("Binarizado %s (umbral %.3f) -> %s", src_path.name, thr, dst_path.name)
        out.append(SpeciesRaster(species, dst_path))

    return out


__all__ = [
    "SpeciesRaster",
    "binarize_directory",
    "discover_species_rasters",
    "normalize_species_name",
    "validate_raster_stack",
    "Resampling",
]
