# Revisión del flujo original

Hallazgos sobre `clasificacion_comunidades_espacial.ipynb`, `graficas.ipynb`,
`analisis_vectores.ipynb`, `dilu_fa/dilucion.ipynb`, `binary_map.py` y `final_fix.py`,
ordenados por impacto sobre los resultados publicables.

---

## A. Afectan a los resultados o a su defensa ante revisión

### A1. Los clusters y el análisis de deforestación describen conjuntos distintos

`crear_dendrograma_comunidades` se ejecuta sobre `composicion_especies.csv` (celda 14),
es decir el catálogo **con** zonas urbanas. La cadena de deforestación (celda 7) parte de
`composicion_especies_sin_urbano.csv`. Los grupos del dendrograma incluyen, por tanto,
comunidades que ya no existen en la caracterización de perturbación, y las extensiones
(`numero_celdas`) no coinciden entre ambas tablas.

*Corrección:* `Pipeline.step_exclude()` se ejecuta antes de `step_cluster()`, sobre un
único par (cuadrícula, catálogo) que se propaga a todos los pasos posteriores.

### A2. Ward sobre distancias de Jaccard

```python
distancias = pdist(matriz_especies, metric='jaccard')
Z = linkage(distancias, method='ward')
```

El criterio de Ward minimiza el incremento de la suma de cuadrados intra-grupo y está
definido únicamente para distancias euclidianas. `scipy` acepta la llamada, pero la
solución no es la de Ward y las alturas del dendrograma dejan de tener interpretación.
Para incidencia binaria corresponde UPGMA (`average`) o `complete`; si se desea Ward,
debe aplicarse sobre una transformación euclidiana (p. ej. Hellinger) de la matriz.

*Corrección:* `ClusterConfig.validate()` y `cluster_communities` rechazan la combinación
`ward` + métrica no euclidiana. El valor por defecto es `average`.

### A3. Identificadores de comunidad no reproducibles

`guid = str(uuid.uuid4())`. Dos ejecuciones sobre exactamente los mismos datos producen
identificadores distintos: no se pueden comparar corridas, ni versionar resultados, ni
citar una comunidad concreta en el manuscrito, ni volver a unir un CSV antiguo con un
shapefile nuevo.

*Corrección:* `community_id()` devuelve `blake2b` de la composición ordenada. Misma
composición ⇒ mismo identificador, siempre.

### A4. `k = 4` sin criterio

`num_clusters=4` aparece fijado en cinco lugares distintos sin justificación ni análisis
de sensibilidad.

*Corrección:* `evaluate_k()` calcula la silueta media para un rango de k y
`cluster_communities` reporta la correlación cofenética; ambos se exportan a
`04_diagnostico_k.csv` para el material suplementario.

### A5. Regla de presencia máximamente laxa

`if out_image.max() == 1: current_species.append(...)` declara presencia con **un solo
píxel** dentro de la celda. Además `rasterio.mask` se llama con `all_touched=False`
mientras el análisis zonal de deforestación usa `all_touched=True`: dos definiciones
distintas de "dentro de la celda" en el mismo flujo.

*Corrección:* `SpeciesConfig.presence_rule` ∈ `any | min_pixels | min_fraction |
majority`, con `all_touched` explícito y compartido. `any` sigue disponible para
reproducir el resultado anterior.

### A6. Umbral de binarización único para 38 especies

`binary_map.py` aplica `umbral = 0.5` a todos los modelos. La práctica estándar en SDM es
un umbral por especie (maxTSS, maximum kappa, 10-percentile training presence), derivado
de la evaluación de cada modelo.

*Corrección:* `binarize_directory(thresholds=...)` acepta un diccionario especie → umbral
o un CSV vía `spatialcom binarize --thresholds-csv`.

### A7. Todas las comunidades pesan igual en el dendrograma

Una composición presente en 1 celda influye tanto como una presente en 500. Las
composiciones raras (frecuentemente artefactos de borde de los SDM) desestabilizan el
árbol.

*Corrección:* `ClusterConfig.min_cells` permite excluirlas y `cluster_profiles` reporta la
extensión agregada por grupo.

---

## B. Defectos de implementación

### B1. NoData sin efecto en la binarización

En `binary_map.py`:

```python
banda_salida.WriteArray(array_binario)   # se escribe aquí
...
array_binario[array_datos == nodata_value] = 0   # se modifica después: no tiene efecto
```

El enmascarado se aplica a un array ya volcado a disco. Además `SetNoDataValue(0)` marca
la **ausencia** como NoData, lo que impide distinguir "ausencia" de "sin información".

### B2. Mutación accidental del DataFrame de origen

```python
denominator = community_stats['total_pixels_in_community']
denominator[denominator == 0] = np.nan
```

`denominator` es una vista, no una copia: los ceros de la columna original se convierten
en `NaN` y contaminan las salidas posteriores.

### B3. Truncado de campos del Shapefile

El formato DBF limita los nombres a 10 caracteres:
`cell_deforested_pixels` → `cell_defor`, `nivel_defor` → `nivel_defo`. El código lo
absorbe de forma inconsistente: la celda 8 comprueba `cell_defor`, la celda 10 lee
`nivel_defo`, y la documentación se refiere a los nombres largos.

*Corrección:* GeoPackage por defecto; `write_vector(fmt="shp")` avisa de qué campos se
truncarán.

### B4. Resolución de solapamientos con índices duplicados

`vincular_regiones_naturales` iteraba sobre un `GeoDataFrame` con índice repetido tras
`sjoin`, usaba `.loc` sobre ese índice y agrupaba por `level=0`. De ahí los errores
documentados en `SOLUCION_KEYERROR.md` y `SOLUCION_TYPEERROR.md`, y los parches que
`final_fix.py` aplica mediante reemplazo de cadenas sobre el JSON del notebook.

*Corrección:* `assign_regions` calcula el área de solape y resuelve con
`groupby("_cell")["_area"].idxmax()`, sin bucles ni índices ambiguos.

### B5. Errores silenciosos

Nueve funciones devuelven `None` ante un fallo (`FileNotFoundError`, columna ausente,
`zonal_stats` fallido) y los llamadores no comprueban el retorno. El fallo aparece varias
celdas después, en un lugar sin relación con la causa.

*Corrección:* jerarquía de excepciones en `exceptions.py`; `require_columns` valida el
esquema antes de operar.

### B6. Discrepancia de CRS solo advertida

```python
if src.crs != grid_crs:
    print(f"  ADVERTENCIA DE SRC: ...")
# ...y continúa
```

Una discrepancia de CRS invalida por completo la superposición; no es una advertencia.

*Corrección:* `validate_raster_stack` lanza `RasterError`.

### B7. `exit()` dentro de una celda

En la celda 3, `exit()` termina el kernel en lugar de la función.

### B8. `filter_by_species` por expresión regular sobre texto plano

`\bCebus_albifrons\b` también coincide dentro de `Cebus_albifrons_versicolor`, porque `_`
es carácter de palabra pero el límite se evalúa sobre el texto completo de la lista.

*Corrección:* comparación sobre la lista tokenizada.

---

## C. Estructura y mantenibilidad

| Problema | Evidencia | Solución |
|---|---|---|
| Rutas absolutas incrustadas | `'D:/modelos_primates/...'` en 23 celdas | `Config.from_yaml` |
| Estado global entre celdas | `Z`, `mlb`, `matriz_especies`, `pca_model` compartidos; celda 21 los comprueba a mano; celda 22 instruye "reiniciar el kernel" | `PipelineState` con `require()` |
| Notebook como código fuente | `final_fix.py` parchea el `.ipynb` por reemplazo de cadenas | módulos versionados en git |
| Sin pruebas | ninguna | 35 pruebas sobre datos sintéticos |
| `print` como registro | ~180 llamadas | `logging` con niveles y archivo |
| Tablas exportadas como PNG | `crear_tabla_articulo` | `viz/tables.py` → CSV / Markdown / LaTeX |
| Coste computacional | `n_celdas x n_especies` aperturas de ráster dentro del bucle | rasterización única + `np.bincount` por bloques |
| Duplicación entre notebooks | `abbreviate_species` en `graficas`, paletas repetidas | `viz/theme.py` |

---

## D. Detectado al correr sobre datos reales

Tres defectos que solo aparecen con los datos del proyecto, documentados con sus cifras
en `VALIDACION.md`: extensiones distintas entre los 38 rásters (V1), colisión del
identificador de celda al escribir la capa (V2) e índice duplicado en la asignación de
regiones, que inflaba la cuadrícula de 9.726 a 10.272 filas (V3). Los tres tienen prueba
de regresión.

---

## E. Pendiente de decisión

1. **`min_pixels` / `min_fraction` definitivos.** Fijar el criterio de presencia y
   reportarlo en Métodos. Recomendación: `min_fraction` ≥ 0.05 con análisis de
   sensibilidad frente a `any`.
2. **Umbrales por especie.** Requiere las métricas de evaluación de los modelos de
   BioModelos. Mientras no estén, 0.5 queda documentado como supuesto.
3. **Incertidumbre de los SDM.** El flujo trata cada modelo como verdad binaria. Un
   análisis de sensibilidad sobre el umbral es la vía más barata de acotarla.
4. **Nombre y licencia del paquete.** `spatialcom` es provisional; verificar
   disponibilidad en PyPI antes de publicar.
5. **`min_cells` para el clustering.** La corrida real deja nueve comunidades (24 celdas,
   0,3 % del área) repartidas en tres clusters residuales. Con `min_cells: 5` quedarían
   fuera. Requiere una corrida comparativa antes de fijar la versión del manuscrito.
6. **Robustez de k.** La silueta de k=5 (0,221) apenas supera a k=6 (0,217) y k=2
   (0,216). La estructura de grupos es débil; conviene reportar la curva completa.
