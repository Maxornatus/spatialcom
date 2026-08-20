"""Entrada/salida: lectura y validación de rásters y vectores, escritura de resultados."""
from .grid import make_grid, make_grid_from_file
from .rasters import SpeciesRaster, binarize_directory, discover_species_rasters
from .vectors import ensure_crs, load_grid, load_layer
from .writers import write_table, write_vector

__all__ = [
    "SpeciesRaster",
    "make_grid",
    "make_grid_from_file",
    "binarize_directory",
    "discover_species_rasters",
    "load_grid",
    "load_layer",
    "ensure_crs",
    "write_table",
    "write_vector",
]
