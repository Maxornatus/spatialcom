"""Compara la salida de `spatialcom` con los resultados del notebook original.

Verifica que la reimplementación reproduce la delineación celda a celda, pese a
usar un algoritmo distinto (rasterización única + `bincount` frente al bucle
celda x especie) e identificadores deterministas en lugar de UUID aleatorios.

Uso:
    python docs/comparar_con_notebook.py ../resultados/prueba_10 ../resultados/primates_v1
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


def composiciones(serie: pd.Series) -> list[frozenset]:
    return [frozenset(x.strip() for x in str(v).split(",") if x.strip()) for v in serie]


def comparar(antiguo: Path, nuevo: Path) -> int:
    old_full = pd.read_csv(antiguo / "composicion_especies.csv")
    old_urb = pd.read_csv(antiguo / "composicion_especies_sin_urbano.csv")
    new_full = pd.read_csv(nuevo / "01_catalogo_comunidades.csv")
    new_urb = pd.read_csv(nuevo / "02_catalogo_filtrado.csv")

    fallos = 0
    for etiqueta, old, new in [
        ("delineación completa", old_full, new_full),
        ("tras excluir zonas urbanas", old_urb, new_urb),
    ]:
        o = dict(zip(composiciones(old["lista_especies"]), old["numero_celdas"], strict=True))
        n = dict(zip(composiciones(new["species_list"]), new["n_cells"], strict=True))

        mismas = set(o) == set(n)
        conteos = [k for k in set(o) & set(n) if int(o[k]) != int(n[k])]

        print(f"\n--- {etiqueta} ---")
        print(f"  comunidades   antiguo {len(o):4d} | nuevo {len(n):4d}")
        print(f"  celdas        antiguo {sum(o.values()):5d} | nuevo {sum(n.values()):5d}")
        print(f"  mismas composiciones: {mismas}")
        print(f"  discrepancias de conteo: {len(conteos)}")

        if not mismas:
            fallos += 1
            solo_viejo = set(o) - set(n)
            solo_nuevo = set(n) - set(o)
            print(f"  solo en el antiguo ({len(solo_viejo)}): {list(solo_viejo)[:3]}")
            print(f"  solo en el nuevo   ({len(solo_nuevo)}): {list(solo_nuevo)[:3]}")
        if conteos:
            fallos += 1
            for k in conteos[:5]:
                print(f"    {sorted(k)[:3]}...: {o[k]} -> {n[k]}")

    print("\nRESULTADO:", "reproduce el original" if fallos == 0 else f"{fallos} discrepancias")
    return fallos


if __name__ == "__main__":
    antiguo = Path(sys.argv[1] if len(sys.argv) > 1 else "../resultados/prueba_10")
    nuevo = Path(sys.argv[2] if len(sys.argv) > 2 else "../resultados/primates_v1")
    raise SystemExit(1 if comparar(antiguo, nuevo) else 0)
