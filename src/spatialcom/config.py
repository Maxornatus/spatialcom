"""Configuración declarativa del análisis.

Todas las rutas absolutas (`D:/modelos_primates/...`) que estaban incrustadas en
cada celda del notebook viven ahora en un único YAML validado.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from .exceptions import ConfigError

PresenceRule = Literal["any", "min_pixels", "min_fraction", "majority"]
LinkageMethod = Literal["average", "complete", "single", "weighted", "ward"]
VectorFormat = Literal["gpkg", "parquet", "shp"]


@dataclass(slots=True)
class GridConfig:
    """Cuadrícula que define unidad y extensión del análisis."""

    path: Path
    id_column: str = "cell_id"          # se genera si no existe
    crs: str | None = None              # EPSG objetivo; None = usar el de la cuadrícula
    layer: str | None = None


@dataclass(slots=True)
class SpeciesConfig:
    """Rásters de distribución (binarios) y regla de presencia."""

    raster_dir: Path
    pattern: str = "*.tif"
    name_strip_suffixes: tuple[str, ...] = ("_binario", "_bin", "_con")
    presence_rule: PresenceRule = "min_pixels"
    min_pixels: int = 1
    min_fraction: float = 0.0
    all_touched: bool = False
    # CRS a asumir para los rásters que NO declaran ninguno. Muchas salidas de
    # MaxEnt se escriben sin CRS. Solo se aplica a los que lo tienen ausente;
    # nunca sobrescribe uno declarado.
    assume_crs: str | None = None
    # Umbral de binarización por especie (nombre -> umbral). Un único float
    # aplica el mismo umbral a todas: aceptable solo como valor por defecto.
    thresholds: dict[str, float] | float = 0.5


@dataclass(slots=True)
class MaskConfig:
    """Capas de exclusión (p.ej. zonas urbanas) aplicadas tras la delineación."""

    path: Path | None = None
    predicate: str = "intersects"
    label: str = "urbano"


@dataclass(slots=True)
class DeforestationConfig:
    """Ráster categórico de pérdida de cobertura (Hansen lossyear)."""

    raster: Path | None = None
    band: int = 1
    year_offset: int = 2000
    value_range: tuple[int, int] = (1, 24)
    all_touched: bool = True
    # Bordes de clasificación en % de la celda. 0 % queda en el nivel 0.
    level_bins: tuple[float, ...] = (0.0, 10.0, 25.0, 45.0, 75.0)


@dataclass(slots=True)
class ClusterConfig:
    """Clustering jerárquico sobre composición de especies."""

    metric: str = "jaccard"
    # `ward` exige distancias euclidianas: no es válido sobre Jaccard.
    linkage: LinkageMethod = "average"
    n_clusters: int | None = None        # None = seleccionar por silueta
    k_range: tuple[int, int] = (2, 12)
    selection: Literal["silhouette", "fixed"] = "silhouette"
    min_cells: int = 1                   # descartar composiciones muy raras
    random_state: int = 42


@dataclass(slots=True)
class RegionsConfig:
    """Regiones naturales para la agregación biogeográfica."""

    path: Path | None = None
    name_column: str | None = None       # None = autodetectar columna con "region"


@dataclass(slots=True)
class WebmapConfig:
    """Mapa HTML interactivo de comunidades."""

    enabled: bool = True
    filename: str = "07_mapa_comunidades"
    title: str = "Comunidades de especies"
    subtitle: str = ""
    # Tolerancia en unidades del CRS (grados en EPSG:4326). 0 = geometría exacta.
    simplify_tolerance: float = 0.002
    coord_precision: int = 4
    basemap: Literal["carto", "osm", "none"] = "carto"
    # "bundled" incrusta la copia del paquete (offline), "cdn" enlaza a unpkg,
    # o la ruta a una carpeta con leaflet.css/leaflet.js propios.
    leaflet: str = "bundled"
    # Capa de contorno embebida como referencia geográfica cuando no hay teselas.
    # None = usar la capa de regiones si está configurada.
    context_path: Path | None = None
    # Incrustar las figuras estáticas del paso 7 como tercera pestaña. Añade
    # aproximadamente el tamaño de las figuras en base64 (~1,3x).
    embed_figures: bool = True


@dataclass(slots=True)
class OutputConfig:
    """Destino y formato de las salidas."""

    dir: Path = Path("outputs")
    # GPKG evita el truncado de nombres de campo a 10 caracteres del Shapefile,
    # origen de los bugs `cell_defor` / `nivel_defo` del notebook original.
    vector_format: VectorFormat = "gpkg"
    figure_format: str = "svg"
    dpi: int = 300
    overwrite: bool = False


@dataclass(slots=True)
class Config:
    """Configuración raíz del análisis."""

    grid: GridConfig
    species: SpeciesConfig
    output: OutputConfig = field(default_factory=OutputConfig)
    mask: MaskConfig = field(default_factory=MaskConfig)
    deforestation: DeforestationConfig = field(default_factory=DeforestationConfig)
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    regions: RegionsConfig = field(default_factory=RegionsConfig)
    webmap: WebmapConfig = field(default_factory=WebmapConfig)
    run_id: str = "run"

    # -- construcción ----------------------------------------------------
    @classmethod
    def from_yaml(cls, path: str | Path, validate_paths: bool = True) -> Config:
        """Carga la configuración desde YAML.

        `validate_paths=False` permite cargar una configuración cuyos datos aún
        no existen. Lo necesita `spatialcom check`, cuyo trabajo es precisamente
        informar de lo que falta: si la carga fallara antes, nunca podría
        reportarlo.
        """
        path = Path(path)
        if not path.exists():
            raise ConfigError(f"No existe el archivo de configuración: {path}")
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls.from_dict(raw, base_dir=path.parent, validate_paths=validate_paths)

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        base_dir: Path | None = None,
        validate_paths: bool = True,
    ) -> Config:
        base_dir = Path(base_dir) if base_dir else Path.cwd()

        def resolve(value: Any) -> Any:
            if value is None:
                return None
            p = Path(value)
            return p if p.is_absolute() else (base_dir / p).resolve()

        try:
            grid_raw = raw["grid"]
            species_raw = raw["species"]
        except KeyError as exc:  # noqa: TRY003
            raise ConfigError(f"Falta la sección obligatoria {exc} en la configuración") from exc

        grid = GridConfig(**{**grid_raw, "path": resolve(grid_raw["path"])})
        species = SpeciesConfig(
            **{**species_raw, "raster_dir": resolve(species_raw["raster_dir"])}
        )

        out_raw = raw.get("output", {})
        output = OutputConfig(**{**out_raw, "dir": resolve(out_raw.get("dir", "outputs"))})

        mask_raw = raw.get("mask", {})
        mask = MaskConfig(**{**mask_raw, "path": resolve(mask_raw.get("path"))})

        def_raw = raw.get("deforestation", {})
        deforestation = DeforestationConfig(
            **{**def_raw, "raster": resolve(def_raw.get("raster"))}
        )

        reg_raw = raw.get("regions", {})
        regions = RegionsConfig(**{**reg_raw, "path": resolve(reg_raw.get("path"))})

        cluster = ClusterConfig(**raw.get("cluster", {}))

        web_raw = dict(raw.get("webmap", {}))
        if web_raw.get("context_path"):
            web_raw["context_path"] = resolve(web_raw["context_path"])
        leaflet = web_raw.get("leaflet", "bundled")
        if leaflet not in ("bundled", "cdn"):
            web_raw["leaflet"] = str(resolve(leaflet))
        webmap = WebmapConfig(**web_raw)

        cfg = cls(
            grid=grid,
            species=species,
            output=output,
            mask=mask,
            deforestation=deforestation,
            cluster=cluster,
            regions=regions,
            webmap=webmap,
            run_id=raw.get("run_id", "run"),
        )
        cfg.validate(paths=validate_paths)
        return cfg

    # -- validación ------------------------------------------------------
    def validate(self, paths: bool = True) -> None:
        """Valida la configuración. Con `paths=False` omite la existencia de datos."""
        if paths:
            if not self.grid.path.exists():
                raise ConfigError(f"Cuadrícula no encontrada: {self.grid.path}")
            if not self.species.raster_dir.is_dir():
                raise ConfigError(
                    f"Directorio de rásters no encontrado: {self.species.raster_dir}"
                )
        if self.cluster.linkage == "ward" and self.cluster.metric != "euclidean":
            raise ConfigError(
                "El criterio de Ward asume distancias euclidianas. "
                f"Con metric='{self.cluster.metric}' use linkage 'average' (UPGMA) o 'complete'."
            )
        lo, hi = self.cluster.k_range
        if lo < 2 or hi <= lo:
            raise ConfigError(f"k_range inválido: {self.cluster.k_range}")
        if self.webmap.simplify_tolerance < 0:
            raise ConfigError("webmap.simplify_tolerance no puede ser negativo.")
        if (
            paths
            and self.webmap.leaflet not in ("bundled", "cdn")
            and not Path(self.webmap.leaflet).is_dir()
        ):
            raise ConfigError(
                f"webmap.leaflet debe ser 'bundled', 'cdn' o una carpeta existente; "
                f"recibido: {self.webmap.leaflet}"
            )
        if (
            paths
            and self.webmap.context_path is not None
            and not self.webmap.context_path.exists()
        ):
            raise ConfigError(f"webmap.context_path no existe: {self.webmap.context_path}")

    # -- utilidades ------------------------------------------------------
    @property
    def run_dir(self) -> Path:
        return self.output.dir / self.run_id

    def to_dict(self) -> dict[str, Any]:
        def convert(obj: Any) -> Any:
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [convert(v) for v in obj]
            return obj

        return convert(asdict(self))

    def dump(self, path: str | Path) -> Path:
        """Escribe la configuración efectiva junto a los resultados (procedencia)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(self.to_dict(), fh, allow_unicode=True, sort_keys=False)
        return path
