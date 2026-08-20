# Cómo contribuir

## Entorno de desarrollo

Las dependencias geoespaciales (`geopandas`, `rasterio`, `rasterstats`) se instalan
mejor desde conda-forge, sobre todo en Windows:

```bash
conda create -n spatialcom -c conda-forge python=3.11 geopandas rasterio rasterstats
conda activate spatialcom
pip install -e ".[viz,dev]"
```

En Linux y macOS basta con pip:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[viz,dev]"
```

## Antes de abrir un pull request

```bash
ruff check .
ruff format --check .
mypy src/spatialcom
pytest
```

Las pruebas construyen rásters y cuadrículas sintéticos en `tmp_path`: corren en
segundos y **no** necesitan los datos del proyecto. Toda corrección de un defecto
debería llegar acompañada de una prueba de regresión.

## Estructura y regla de dependencias

`io` → `core` → `cluster` → `viz` → `pipeline` → `cli`. Ninguna capa importa hacia
arriba. `core` y `cluster` no conocen matplotlib ni rutas de archivo; si una función
nueva necesita leer disco o dibujar, va en `io` o en `viz`.

Otras convenciones del proyecto:

- Ninguna función devuelve `None` ante un fallo: se lanza un error de
  `spatialcom.exceptions`.
- Nada de `print()` en la librería; usar el logger de `spatialcom._logging`.
- Las funciones de `viz` devuelven `(fig, ax)`; no guardan ni muestran.

## Reportar un problema

Abre un *issue* con la versión de `spatialcom`, la de Python, el sistema operativo y
el fragmento de `config.yaml` implicado. Si el fallo depende de los datos, la salida
de `spatialcom check config.yaml` suele bastar para reproducirlo.

## Licencia

Al contribuir aceptas que tu aporte se distribuya bajo la licencia MIT del proyecto.
