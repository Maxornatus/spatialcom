"""Estilo tipográfico y de color común a todas las figuras."""
from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt

from .._logging import get_logger

log = get_logger(__name__)

#: Paleta categórica segura para daltonismo (Okabe-Ito), como lista de strings.
#: El notebook pasaba a seaborn una paleta que no siempre era de cadenas de
#: color, lo que producía `TypeError: all palette list elements must be color
#: strings` y obligaba a reiniciar el kernel.
CLUSTER_PALETTE: list[str] = [
    "#0072B2", "#D55E00", "#009E73", "#CC79A7",
    "#E69F00", "#56B4E9", "#F0E442", "#000000",
]

_RC = {
    "figure.dpi": 110,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.labelsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "legend.frameon": False,
    "svg.fonttype": "none",  # texto editable en Illustrator/Inkscape
}


def apply_theme(**overrides) -> None:
    """Aplica el estilo del paquete a matplotlib."""
    mpl.rcParams.update({**_RC, **overrides})


def cluster_colors(n: int) -> list[str]:
    """Devuelve `n` colores categóricos, reciclando la paleta si hace falta."""
    return [CLUSTER_PALETTE[i % len(CLUSTER_PALETTE)] for i in range(n)]


def italic_binomial(name: str) -> str:
    """`Alouatta_seniculus_con` -> `$\\it{A.\\ seniculus}$`.

    Port de `abbreviate_species` de `graficas.ipynb`, con retorno seguro cuando
    el nombre no sigue el patrón género_epíteto.
    """
    parts = [p for p in name.split("_") if p]
    if len(parts) < 2:
        return name.replace("_", " ")
    genus, epithet = parts[0][0].upper(), parts[1].lower()
    return rf"$\it{{{genus}.\ {epithet}}}$"


def save_figure(fig, path: str | Path, fmt: str = "svg", dpi: int = 300) -> Path:
    """Guarda una figura y la cierra, evitando fugas de memoria en lotes largos."""
    path = Path(path).with_suffix("." + fmt.lstrip("."))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    log.info("Figura guardada: %s", path.name)
    return path
