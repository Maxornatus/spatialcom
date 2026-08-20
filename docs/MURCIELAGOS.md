# Corrida `murcielagos_v1` — 196 especies

Ejecución sobre `murcielagos/Binarios`, con la misma cuadrícula y las mismas capas de
contexto que el análisis de primates.

```bash
spatialcom check configs/murcielagos_colombia.yaml
spatialcom run   configs/murcielagos_colombia.yaml
```

Tiempo total: **3 min 3 s**, de los cuales 2 min 36 s son las estadísticas zonales de
Hansen. La delineación de 9.726 celdas x 196 especies tarda **16 segundos**.

---

## Resultados

| Métrica | Valor |
|---|---|
| Especies | 196 |
| Comunidades delineadas | 7.619 |
| Tras excluir zonas urbanas | 7.010 |
| Celdas ocupadas | 8.950 de 9.726 |
| Riqueza por celda | 8 – 141, media **99,1** |
| k seleccionado | 2 (silueta 0,573) |
| Correlación cofenética | 0,897 |

La delineación reproduce exactamente el conteo del análisis previo en
`murcielagos/Resultados` (7.619 comunidades), lo que valida de forma independiente la
reimplementación con un segundo conjunto de datos.

---

## El resultado principal: el método no discrimina a esta riqueza

| | primates | murciélagos |
|---|---|---|
| Especies | 38 | 196 |
| Comunidades (tras exclusión) | 438 | 7.010 |
| **Celdas por comunidad** | **20,4** | **1,3** |
| Riqueza media por celda | 6,5 | 99,1 |
| Comunidades de una sola celda | 26 % | **87 %** |
| Comunidades con ≥ 2 celdas | 74 % (98,7 % del área) | 12,6 % (31,5 % del área) |
| Comunidades con ≥ 5 celdas | 48 % (95,3 % del área) | 1,8 % (11,3 % del área) |

Con 196 especies y una riqueza media de 99 por celda, **casi cada celda tiene una
composición única**: 6.128 de las 7.010 comunidades ocupan exactamente una celda. El
identificador de comunidad deja de agrupar y pasa a ser, en la práctica, un identificador
de celda.

Esto no es un defecto del código —los conteos son correctos y reproducen el análisis
previo— sino el criterio de **composición exacta** encontrando su límite. Agrupar por
identidad exacta funciona cuando el número de combinaciones posibles es comparable al
número de celdas; con 196 especies el espacio de combinaciones es astronómico y cada
celda cae en su propia clase.

### Consecuencia en el clustering

El clustering solo puede usar las comunidades con respaldo espacial. Con `min_cells: 2`
entran 882 comunidades (12,6 %) que cubren 2.822 de 8.950 celdas (**31,5 %**). El
resultado es degenerado:

| Cluster | Comunidades | Celdas | Riqueza media |
|---|---|---|---|
| 1 | 5 | 10 | 81,2 |
| 2 | 877 | 2.812 | 98,7 |

k = 2 con grupos de 5 y 877: el algoritmo aísla cinco atípicas y deja todo lo demás junto.
La silueta de 0,573 parece buena precisamente por eso —separar unos pocos atípicos da
siluetas altas— y no debe leerse como evidencia de estructura. La tabla región x cluster
lo confirma: el cluster 2 domina las cinco regiones, y el cluster 1 son 10 celdas andinas.

Con `min_cells: 5` la cobertura cae al 11,3 % del área. Ninguna elección de `min_cells`
resuelve el problema; solo mueve el punto de corte.

---

## Qué se puede hacer

En orden de esfuerzo creciente:

1. **Regla de presencia más estricta.** Ahora mismo un solo píxel de 1 km declara presencia
   en una celda de ~11 km. Con `presence_rule: min_fraction` y un umbral de 0,05–0,10 la
   riqueza por celda baja y las composiciones se repiten más. Es un cambio de una línea en
   la configuración y merece probarse primero.

2. **Analizar subconjuntos con sentido ecológico** en lugar de las 196 juntas: por familia
   (Phyllostomidae, Vespertilionidae…) o por gremio trófico (frugívoros, nectarívoros,
   insectívoros, hematófagos). Cada subconjunto tiene una riqueza comparable a la de los
   primates y el método vuelve a discriminar. Es además una pregunta biológica más
   nítida que "la comunidad de murciélagos".

3. **Celdas más pequeñas.** Reduce la riqueza por celda, pero aumenta el número de celdas y
   solo desplaza el problema; además los SDM a 1 km no soportan mucho más detalle.

4. **Cambiar el criterio de agrupación.** Lo estándar en regionalización biogeográfica a
   esta riqueza no es la composición exacta sino agrupar las **celdas** por *similitud* de
   composición (Jaccard entre celdas + clustering, o *bioregionalization* con
   Infomap/mapas de similitud). `spatialcom` no lo implementa: sería un modo de análisis
   nuevo, no un parámetro.

Recomendación: probar (1) y (2), que se resuelven con la configuración actual.

---

## Notas sobre los datos de entrada

**Los 196 rásters no declaran CRS.** Su resolución (0,008333°) y su extensión (−81,72 a
−66,87 lon; −4,23 a 12,59 lat) corresponden inequívocamente a coordenadas geográficas
sobre Colombia. Se declara con `species.assume_crs: EPSG:4326`, que solo se aplica a los
rásters sin CRS y comprueba que las coordenadas sean plausibles. Es una suposición
declarada del usuario, no un dato del archivo; conviene corregir los archivos en origen
con `gdal_edit.py -a_srs EPSG:4326`.

**Tres modelos están vacíos en la práctica**, y aportan ruido más que información:

| Especie | Píxeles con presencia | Comunidades |
|---|---|---|
| `Mimon_cozumelae` | **1** | 1 comunidad de 1 celda |
| `Natalus_mexicanus` | 3 | 1 comunidad de 1 celda |
| `Chilonatalus_micropus` | 9 | 1 comunidad de 1 celda |

`Mimon_cozumelae` desaparece por completo tras la exclusión urbana: su único píxel cae en
una celda urbana. Un SDM binarizado con uno o tres píxeles de presencia indica que el
umbral de corte dejó fuera casi todo el modelo; conviene revisar la umbralización de esas
especies antes de incluirlas.

**Un archivo tiene el sufijo `_binario` y los demás no**
(`Lophostoma_occidentalis_binario.tif`). `species.name_strip_suffixes` lo normaliza, pero
conviene homogeneizar los nombres en origen.

---

## Defectos del código que reveló esta corrida

Tres bugs que el conjunto de primates (438 comunidades, `min_cells: 1`) no podía
exponer. Los tres con prueba de regresión.

### M1. La ordenación reventaba con `min_cells > 1`

`step_ordination` pasaba el catálogo completo (7.010 filas) junto con la matriz de
distancias calculada sobre el subconjunto agrupado (123 filas), y pandas fallaba con
`Shape of passed values is (123, 2), indices imply (7010, 2)`.

Corregido: el paso usa `incidence.loc[clusters.labels.index]`, y `ordinate` valida ahora
que el número de pares de la matriz de distancias corresponda a las filas recibidas, con
un mensaje que dice exactamente qué pasar.

### M2. La matriz de similitud ocupaba 850 MB

Se calculaba sobre las 7.010 comunidades completas en lugar del subconjunto agrupado:
`04_matriz_similitud.csv` salió con 7.010 x 7.011 y tardó 94 segundos en escribirse.

Corregido: se calcula solo para las comunidades que entraron al clustering y se omite por
encima de 2.000, con un aviso que estima el tamaño que habría tenido.

---

### M3. El mapa ocultaba las comunidades sin cluster

Con `min_cells: 2`, 6.128 de las 7.010 comunidades llegan al mapa con `cluster` nulo. El
filtro de cluster comprobaba `state.clusters.has(com.k)`, y como `null` no está entre los
valores de cluster, **las descartaba todas al abrir el archivo**: el mapa mostraba 882
comunidades y 2.822 celdas de 7.010 y 8.950, sin ningún filtro activo y sin indicarlo.

Con el conjunto de primates el bug era invisible porque `min_cells: 1` asignaba cluster a
todas las comunidades.

Corregido: las comunidades sin cluster forman una categoría propia, **Sin grupo
asignado**, marcada por omisión y con su recuento de celdas; aparece también en la leyenda
y en la imagen exportada. Desmarcarla reproduce el comportamiento anterior, pero como
decisión explícita.

Además, bajo el control de riqueza se indica ahora el rango observado en los datos. En
murciélagos la riqueza mínima es 8, así que el control no baja de ahí; sin esa nota, ese
límite se lee como un filtro activo en vez de como el mínimo real.

---

## Archivos

En `resultados/murcielagos_v1/`. El mapa web pesa **6,8 MB**: 7.022 segmentos frente a los
499 de primates. Sigue abriendo sin conexión.

Las figuras se generan igual, pero el dendrograma y el mapa de calor describen solo el
31,5 % del área por lo dicho arriba. La dispersión riqueza-perturbación sí usa las 7.010
comunidades: da ρ = 0,22 con p = 9 × 10⁻⁷⁵. Ojo con la lectura — con n = 7.010 casi
cualquier asociación resulta significativa, y las comunidades no son independientes entre
sí. El tamaño del efecto (ρ = 0,22) es lo informativo, no el p-valor.
