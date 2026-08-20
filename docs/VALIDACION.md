# Validación sobre los datos reales

Ejecución `primates_v1`, 2026-08-20. Entradas: `cuadricula_cortada.shp` (9.726 celdas,
EPSG:4326), 38 rásters binarios de `tiff_primates_binarios`, `ciudades.shp`,
`deforestacion_colombia.vrt` (Hansen GFC 2024 v1.12), `Regiones_Naturales/regiones.shp`.

```bash
spatialcom run configs/primates_colombia.yaml
```

Tiempo total: **3 min 30 s**, de los cuales 2 min 34 s son las estadísticas zonales sobre
el mosaico Hansen a 30 m. La delineación de comunidades —el paso que en el notebook
recorría celda por celda abriendo los 38 rásters en cada una— tarda **2 segundos**.

---

## Reproducción del resultado original

`docs/comparar_con_notebook.py` compara composición a composición contra
`resultados/prueba_10`, ignorando los identificadores (los del notebook eran UUID
aleatorios, irrepetibles por construcción):

```
--- delineación completa ---
  comunidades   antiguo  447 | nuevo  447
  celdas        antiguo  9568 | nuevo  9568
  mismas composiciones: True
  discrepancias de conteo: 0

--- tras excluir zonas urbanas ---
  comunidades   antiguo  438 | nuevo  438
  celdas        antiguo  8918 | nuevo  8918
  mismas composiciones: True
  discrepancias de conteo: 0
```

Coincidencia exacta: los mismos 447 conjuntos de especies, con los mismos conteos de
celda, pese a un algoritmo distinto. La reimplementación no cambia el resultado
biológico, solo su coste y su reproducibilidad.

---

## Defectos detectados al correr sobre datos reales

Tres bugs que las pruebas sintéticas no cubrían. Los tres tienen ahora prueba de
regresión (`pytest`: 35 pruebas).

### V1. Los 38 rásters tienen 38 extensiones distintas

Cada modelo de BioModelos viene recortado a su propia área. La primera implementación
leía todas las especies con el mismo índice de fila/columna, tomando el primer ráster
como referencia: las capas quedaban desplazadas unas respecto a otras y las
composiciones habrían sido falsas.

Comprobado sobre los datos: 38 extensiones distintas, todas alineadas al mismo enrejado
(desviación máxima 3,7 × 10⁻⁸ px). La corrección construye una malla común como unión de
las extensiones y lee cada especie por **límites geográficos**, no por índice.
`validate_raster_stack` ahora rechaza rásters cuyo enrejado no coincida.

### V2. Colisión al escribir la cuadrícula

`load_grid` deja `cell_id` como índice y como columna. Los drivers vectoriales
materializan el índice con `reset_index(drop=False)`, que choca con la columna homónima:
`ValueError: cannot insert cell_id, already exists`. `write_vector` resuelve el duplicado
antes de escribir.

### V3. Índice duplicado en la asignación de regiones

`assign_regions` devolvía **10.272 filas** para una cuadrícula de 9.726: 546 celdas
duplicadas. Causa: `sjoin` hereda el índice de la cuadrícula y lo repite una vez por
región intersectada; `pairs.loc[groupby(...).idxmax()]` recupera entonces *todas* las
filas que comparten cada etiqueta, no una sola.

Es el mismo patrón de índice duplicado que hacía fallar a `vincular_regiones_naturales`
en el notebook. La corrección normaliza el índice con `reset_index(drop=True)` antes de
agrupar, y la función verifica ahora dos invariantes: una región por celda y número de
celdas inalterado.

---

## Resultados de la corrida

### Delineación

| Métrica | Valor |
|---|---|
| Celdas | 9.726 |
| Celdas con al menos una especie | 9.568 |
| Composiciones únicas | 447 |
| Especies | 38 |
| Riqueza máxima por celda | 15 |
| Celdas excluidas por zona urbana | 654 (6,7 %) |
| Comunidades vigentes tras la exclusión | 438 (9 desaparecen) |

### Perturbación (Hansen 2001-2024)

Celdas con al menos un píxel de pérdida: 9.652 de 9.726 (99,24 %).

| Nivel | Rango (% de la celda) | Celdas |
|---|---|---|
| 0 | 0 | 74 |
| 1 | 0-10 | 8.101 |
| 2 | 10-25 | 1.105 |
| 3 | 25-45 | 347 |
| 4 | 45-75 | 95 |
| 5 | > 75 | 4 |

### Clustering

UPGMA sobre distancia de Jaccard. Correlación cofenética **0,814**.

| Cluster | Comunidades | Celdas | Riqueza media | Riqueza máx. | Pérdida media (%) |
|---|---|---|---|---|---|
| 1 | 2 | 2 | 1,50 | 2 | 0,06 |
| 2 | 2 | 2 | 1,50 | 2 | 0,44 |
| 3 | 5 | 20 | 1,80 | 3 | 0,64 |
| 4 | 267 | 5.978 | 7,88 | 15 | 5,27 |
| 5 | 162 | 2.916 | 4,48 | 9 | 5,78 |

### Distribución regional

| Subregión | c1 | c2 | c3 | c4 | c5 | Celdas | Clusters |
|---|---|---|---|---|---|---|---|
| Amazonas | 0 | 0 | 0 | 2.693 | 0 | 2.693 | 1 |
| Llanos | 0 | 0 | 0 | 2.493 | 4 | 2.497 | 2 |
| Andes | 0 | 2 | 20 | 787 | 1.423 | 2.232 | 4 |
| Caribe | 2 | 0 | 0 | 0 | 901 | 903 | 2 |
| Pacífico | 0 | 0 | 0 | 0 | 584 | 584 | 1 |

La separación principal es la esperada: el cluster 4 ocupa la Amazonia y los Llanos
(comunidades ricas, cis-andinas) y el cluster 5 el Caribe, el Pacífico y la vertiente
andina (comunidades trans-andinas, menos ricas). Los Andes son la única región con
representación de cuatro clusters, coherente con su papel de barrera y zona de contacto.

---

## Advertencias sobre estos resultados

1. **La estructura de clusters es débil.** La silueta de k=5 es 0,221, apenas por encima
   de k=6 (0,217) y k=2 (0,216); toda la curva se mueve entre 0,13 y 0,22. Los datos de
   composición no presentan grupos marcadamente separados, y el óptimo elegido no está
   bien diferenciado de sus vecinos. Reportar la curva completa
   (`04_diagnostico_k.csv`), no solo el k elegido.

2. **Los clusters 1-3 son residuales.** Nueve comunidades y 24 celdas en total: el 0,3 %
   del área. Son composiciones raras, probablemente artefactos de borde de los SDM, que
   el algoritmo aísla porque cada comunidad pesa igual sea cual sea su extensión. Con
   `cluster.min_cells: 5` quedarían fuera del clustering y la solución se apoyaría solo
   en comunidades con respaldo espacial. Merece una corrida comparativa antes de fijar la
   versión del manuscrito.

3. **99,24 % de celdas con pérdida detectada** es consecuencia de contar un solo píxel de
   30 m como celda afectada. La cifra informativa es la distribución de niveles, no ese
   porcentaje. El 83 % de las celdas está en el nivel 1 (menos del 10 % de su superficie).

4. **Regla de presencia.** Esta corrida usa `min_pixels: 1`, equivalente al criterio del
   notebook. Sigue pendiente decidir el criterio definitivo y su análisis de
   sensibilidad.
