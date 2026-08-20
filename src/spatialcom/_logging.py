"""Logging centralizado. Reemplaza los `print()` dispersos de los notebooks."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger del namespace `spatialcom`."""
    return logging.getLogger(name if name.startswith("spatialcom") else f"spatialcom.{name}")


def setup_logging(level: int | str = logging.INFO, logfile: str | None = None) -> None:
    """Configura el logging del paquete una sola vez.

    Se llama desde la CLI y desde `Pipeline`; en uso interactivo el usuario
    puede llamarla explícitamente.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger("spatialcom")
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%H:%M:%S")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    if logfile:
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    root.propagate = False
    _CONFIGURED = True
