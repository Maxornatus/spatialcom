"""Interfaz de línea de comandos.

Flujo típico, de la carpeta vacía al mapa:

    spatialcom init       mi_proyecto            # estructura + config comentada
    spatialcom make-grid  --boundary limite.shp --cell-size 0.1 --out cuadricula.gpkg
    spatialcom binarize   --src sdm_continuos --dst sdm_binarios
    spatialcom check      mi_proyecto/config.yaml   # ¿están los datos y sirven?
    spatialcom run        mi_proyecto/config.yaml

Comandos sueltos sobre una corrida ya hecha:

    spatialcom step    config.yaml --only cluster
    spatialcom figures config.yaml
    spatialcom webmap  config.yaml
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ._logging import setup_logging
from .config import Config
from .diagnostics import inventory, is_runnable
from .io.rasters import binarize_directory, discover_species_rasters
from .pipeline import Pipeline

app = typer.Typer(add_completion=False, help="Análisis espacial de comunidades de especies.")
console = Console()


@app.command()
def init(
    directorio: Path = typer.Argument(..., help="Carpeta del nuevo proyecto"),
    force: bool = typer.Option(False, help="Sobrescribir un config.yaml existente"),
) -> None:
    """Crea la estructura de carpetas y un config.yaml comentado.

    No inventa datos: deja los directorios donde colocarlos y un archivo de
    configuración que documenta qué va en cada uno.
    """
    setup_logging("INFO")
    plantilla = Path(__file__).parent / "assets" / "config_template.yaml"

    subcarpetas = [
        ("datos/limite", "Área de estudio: país, cuenca o región (shapefile / GPKG)."),
        ("datos/sdm_continuos", "Modelos de distribución sin binarizar, uno por especie."),
        ("datos/sdm_binarios", "Salida de 'spatialcom binarize': rásters 0/1."),
        ("datos/uso_suelo", "Capas de exclusión: urbano, agua, cultivos."),
        ("datos/cobertura", "Ráster de pérdida de cobertura (Hansen lossyear)."),
        ("datos/regiones", "Unidades biogeográficas para agregar resultados."),
        ("resultados", "Salidas del análisis. No versionar."),
    ]

    directorio.mkdir(parents=True, exist_ok=True)
    for sub, descripcion in subcarpetas:
        carpeta = directorio / sub
        carpeta.mkdir(parents=True, exist_ok=True)
        leeme = carpeta / "LEEME.txt"
        if not leeme.exists():
            leeme.write_text(descripcion + "\n", encoding="utf-8")

    destino = directorio / "config.yaml"
    if destino.exists() and not force:
        console.print(f"[yellow]Ya existe {destino}; use --force para sobrescribir.[/yellow]")
    else:
        destino.write_text(plantilla.read_text(encoding="utf-8"), encoding="utf-8")

    console.print(f"[green]Proyecto creado en {directorio}[/green]")
    console.print("\nSiguientes pasos:")
    console.print("  1. Coloque su área de estudio en datos/limite/")
    console.print("  2. spatialcom make-grid --boundary <limite> --cell-size <lado> "
                  f"--out {directorio}/datos/cuadricula.gpkg")
    console.print("  3. Coloque los modelos de distribución en datos/sdm_continuos/")
    console.print(f"  4. spatialcom binarize --src {directorio}/datos/sdm_continuos "
                  f"--dst {directorio}/datos/sdm_binarios")
    console.print(f"  5. spatialcom check {destino}")
    console.print(f"  6. spatialcom run {destino}")


@app.command(name="make-grid")
def make_grid_cmd(
    boundary: Path = typer.Option(..., help="Capa vectorial del área de estudio"),
    cell_size: float = typer.Option(
        ..., help="Lado de la celda en unidades del CRS (grados si es geográfico)"
    ),
    out: Path = typer.Option(..., help="Archivo de salida (.gpkg recomendado)"),
    crs: str = typer.Option(None, help="CRS de trabajo, p.ej. EPSG:4326"),
    clip: bool = typer.Option(True, help="Recortar las celdas al área de estudio"),
    min_area_fraction: float = typer.Option(
        0.0, help="Descartar celdas de borde con menos de esta fracción de área"
    ),
    layer: str = typer.Option(None, help="Capa dentro del archivo de límite"),
) -> None:
    """Genera la cuadrícula de análisis a partir de un área de estudio."""
    setup_logging("INFO")
    from .io.grid import make_grid_from_file
    from .io.writers import write_vector

    grid = make_grid_from_file(
        boundary,
        cell_size=cell_size,
        crs=crs,
        clip=clip,
        min_area_fraction=min_area_fraction,
        layer=layer,
    )
    fmt = out.suffix.lstrip(".").lower() or "gpkg"
    destino = write_vector(grid, out, fmt=fmt, overwrite=True)
    console.print(f"[green]{len(grid)} celdas escritas en {destino}[/green]")


@app.command()
def check(config: Path = typer.Argument(..., help="Ruta al YAML de configuración")) -> None:
    """Inventario de los datos de entrada: presencia, CRS, resolución, solape.

    Termina con código 1 si falta o falla algún insumo obligatorio, de modo que
    sirve como puerta previa en un script o en integración continua.
    """
    setup_logging("WARNING")
    # Sin validar rutas: informar de lo que falta es justamente el objetivo.
    cfg = Config.from_yaml(config, validate_paths=False)
    informe = inventory(cfg)

    colores = {"ok": "green", "aviso": "yellow", "falta": "red", "error": "red"}
    tabla = Table(title=f"Insumos de '{cfg.run_id}'")
    tabla.add_column("Dataset")
    tabla.add_column("Requisito")
    tabla.add_column("Estado")
    tabla.add_column("Detalle", overflow="fold")
    for fila in informe.itertuples():
        color = colores.get(fila.estado, "white")
        tabla.add_row(
            fila.dataset,
            fila.obligatorio,
            f"[{color}]{fila.estado}[/{color}]",
            fila.detalle,
        )
    console.print(tabla)

    if is_runnable(informe):
        console.print("[green]Los insumos obligatorios están completos.[/green]")
    else:
        console.print(
            "[red]Faltan insumos obligatorios o no son utilizables: "
            "el análisis no puede ejecutarse.[/red]"
        )
        raise typer.Exit(code=1)


@app.command()
def validate(config: Path = typer.Argument(..., help="Ruta al YAML de configuración")) -> None:
    """Comprueba rutas, CRS y coherencia de la configuración sin ejecutar nada."""
    setup_logging("INFO")
    cfg = Config.from_yaml(config)
    rasters = discover_species_rasters(
        cfg.species.raster_dir, cfg.species.pattern, cfg.species.name_strip_suffixes
    )

    table = Table(title="Configuración validada")
    table.add_column("Elemento")
    table.add_column("Valor")
    table.add_row("run_id", cfg.run_id)
    table.add_row("cuadrícula", str(cfg.grid.path))
    table.add_row("especies", f"{len(rasters)}")
    table.add_row("regla de presencia", cfg.species.presence_rule)
    table.add_row("clustering", f"{cfg.cluster.linkage} / {cfg.cluster.metric}")
    table.add_row("salida", str(cfg.run_dir))
    console.print(table)


@app.command()
def binarize(
    src: Path = typer.Option(..., help="Directorio con rásters continuos de idoneidad"),
    dst: Path = typer.Option(..., help="Directorio de salida"),
    threshold: float = typer.Option(0.5, help="Umbral por defecto"),
    thresholds_csv: Path = typer.Option(
        None, help="CSV con columnas species,threshold para umbrales por especie"
    ),
    overwrite: bool = typer.Option(False),
) -> None:
    """Convierte rásters de idoneidad en binarios de presencia/ausencia."""
    setup_logging("INFO")
    thresholds: dict[str, float] | float = threshold
    if thresholds_csv:
        import pandas as pd

        df = pd.read_csv(thresholds_csv)
        thresholds = dict(zip(df["species"], df["threshold"], strict=True))

    out = binarize_directory(src, dst, thresholds=thresholds, overwrite=overwrite)
    console.print(f"[green]{len(out)} rásters binarizados en {dst}[/green]")


@app.command()
def figures(
    config: Path = typer.Argument(...),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Genera solo las figuras estáticas, reutilizando los resultados en disco."""
    cfg = Config.from_yaml(config)
    pipe = Pipeline(cfg, log_level=log_level).resume().step_figures()
    console.print(f"[green]{len(pipe.state.figures)} figuras en {cfg.run_dir / 'figuras'}[/green]")


@app.command()
def webmap(
    config: Path = typer.Argument(...),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Genera solo el mapa HTML, reutilizando los resultados ya calculados."""
    cfg = Config.from_yaml(config)
    pipe = Pipeline(cfg, log_level=log_level).resume().step_webmap()
    console.print(f"[green]{pipe.state.webmap}[/green]")


@app.command()
def run(
    config: Path = typer.Argument(...),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Ejecuta el análisis completo definido en el archivo de configuración."""
    cfg = Config.from_yaml(config)
    pipe = Pipeline(cfg, log_level=log_level).run_all()
    console.print_json(json.dumps(pipe.summary(), ensure_ascii=False))


@app.command()
def step(
    config: Path = typer.Argument(...),
    only: str = typer.Option(
        ..., help="delineate | exclude | disturbance | cluster | regions | ordination"
    ),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Ejecuta un único paso, reanudando el estado desde los resultados en disco."""
    cfg = Config.from_yaml(config)
    pipe = Pipeline(cfg, log_level=log_level)
    method = getattr(pipe, f"step_{only}", None)
    if method is None:
        raise typer.BadParameter(f"Paso desconocido: {only}")
    if only != "delineate":
        pipe.resume()
    method()
    console.print_json(json.dumps(pipe.summary(), ensure_ascii=False))


if __name__ == "__main__":
    app()
