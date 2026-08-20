"""Excepciones del paquete.

Las funciones de los notebooks devolvían `None` ante un fallo y el llamador
seguía adelante con `None`, produciendo errores lejos del origen real. Aquí
todo fallo es explícito.
"""
from __future__ import annotations


class SpatialComError(Exception):
    """Base de todas las excepciones del paquete."""


class ConfigError(SpatialComError):
    """Configuración ausente, incompleta o inconsistente."""


class CRSMismatchError(SpatialComError):
    """Sistemas de referencia incompatibles entre capas."""


class GridError(SpatialComError):
    """Problema con la cuadrícula de análisis (geometrías, id, extensión)."""


class RasterError(SpatialComError):
    """Problema al leer o validar un ráster de especie."""


class SchemaError(SpatialComError):
    """Una tabla no contiene las columnas esperadas."""
