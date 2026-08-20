"""spatialcom — delineación y caracterización de comunidades espaciales de especies.

Flujo mínimo:

    from spatialcom import Config, Pipeline

    cfg = Config.from_yaml("configs/primates_colombia.yaml")
    pipe = Pipeline(cfg).run_all()
    print(pipe.summary())

Uso por componentes (para trabajo exploratorio en notebook):

    from spatialcom.io import load_grid, discover_species_rasters
    from spatialcom.core import delineate_communities
    from spatialcom.cluster import cluster_communities
"""
from ._logging import setup_logging
from .config import (
    ClusterConfig,
    Config,
    DeforestationConfig,
    GridConfig,
    MaskConfig,
    OutputConfig,
    RegionsConfig,
    SpeciesConfig,
    WebmapConfig,
)
from .core.composition import CommunityResult, community_id, delineate_communities
from .exceptions import (
    ConfigError,
    CRSMismatchError,
    GridError,
    RasterError,
    SchemaError,
    SpatialComError,
)
from .pipeline import Pipeline, PipelineState

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Config",
    "GridConfig",
    "SpeciesConfig",
    "MaskConfig",
    "DeforestationConfig",
    "ClusterConfig",
    "RegionsConfig",
    "OutputConfig",
    "WebmapConfig",
    "Pipeline",
    "PipelineState",
    "CommunityResult",
    "delineate_communities",
    "community_id",
    "setup_logging",
    "SpatialComError",
    "ConfigError",
    "CRSMismatchError",
    "GridError",
    "RasterError",
    "SchemaError",
]
