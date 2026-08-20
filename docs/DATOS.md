# Qué datos hacen falta y cómo obtenerlos

`spatialcom` no modela nichos ni descarga nada por usted: toma modelos de distribución ya
producidos y los convierte en comunidades. Este documento cubre todo lo que va *antes*:
qué capas necesita, de dónde salen y en qué estado tienen que llegar.

Cuando tenga los datos, `spatialcom check config.yaml` le dirá si sirven antes de gastar
tiempo de cómputo.

---

## Resumen

| Dato | ¿Obligatorio? | Formato | Fuente típica |
|---|---|---|---|
| Área de estudio | para generar la cuadrícula | vectorial (polígono) | GADM, Natural Earth, agencia nacional |
| Cuadrícula de análisis | **sí** | vectorial (polígonos) | `spatialcom make-grid` |
| Modelos de distribución | **sí** | ráster, uno por especie | BioModelos, IUCN, o modelado propio desde GBIF |
| Capa de exclusión | no | vectorial | uso del suelo, ESA WorldCover, GHSL |
| Pérdida de cobertura | no | ráster categórico | Hansen Global Forest Change |
| Regiones biogeográficas | no | vectorial | ecorregiones RESOLVE, cartografía nacional |
| Ocurrencias puntuales | no | CSV con lat/lon | GBIF |
| Rasgos por especie | no | CSV | literatura, PanTHERIA, EltonTraits |

**Dos requisitos que atraviesan todo:** un único CRS de trabajo para todas las capas, y
que los rásters de especie compartan resolución y enrejado. Las extensiones sí pueden
diferir entre especies.

---

## 1. Área de estudio

El polígono que delimita dónde se analiza. Sirve para tender la cuadrícula y recortarla.

- **[GADM](https://gadm.org/download_country.html)** — límites administrativos de todo el
  mundo, en varios niveles (0 = país, 1 = departamento, 2 = municipio). Gratuito para uso
  académico.
- **[Natural Earth](https://www.naturalearthdata.com/)** — dominio público, más
  generalizado; suficiente si la costa exacta no importa.
- Para análisis ecológicos suele ser mejor un límite **biogeográfico** que uno político:
  una cuenca, un bioma o una ecorregión.

Colóquelo en `datos/limite/`.

---

## 2. Cuadrícula de análisis

Es la unidad espacial de todo el resto: cada celda recibirá una composición de especies.

```bash
spatialcom make-grid \
  --boundary datos/limite/pais.shp \
  --cell-size 0.1 \
  --out datos/cuadricula.gpkg \
  --min-area-fraction 0.05
```

`--cell-size` va **en las unidades del CRS**: grados si es geográfico (EPSG:4326), metros
si es proyectado. `0.1` grados son unos 11 km en el ecuador.

`--min-area-fraction 0.05` descarta las astillas costeras que quedan al recortar y que
aportan ruido sin información.

### Cómo elegir el tamaño de celda

Es la decisión más consecuente de todo el análisis y no tiene respuesta universal:

- **Demasiado fina** respecto a la resolución de los modelos: se inventa detalle que los
  SDM no tienen, y aparecen cientos de composiciones únicas que son artefactos de borde.
- **Demasiado gruesa**: todas las especies coexisten en todas las celdas y las comunidades
  dejan de distinguirse.

Regla práctica: al menos varias decenas de píxeles del ráster por celda. Con SDM a 1 km,
celdas de 10 km dan 100 píxeles por celda. Conviene correr el análisis con dos o tres
tamaños y reportar la sensibilidad del número de comunidades al tamaño elegido.

El origen de la malla se alinea a múltiplos del tamaño de celda, de modo que dos corridas
sobre la misma zona producen exactamente la misma cuadrícula.

---

## 3. Modelos de distribución de especies

Un ráster por especie, con `1` donde la especie está presente y `0` donde no.

### Opción A — usar modelos ya publicados

Lo más rápido y lo que hizo el proyecto de primates de Colombia.

- **[BioModelos](http://biomodelos.humboldt.org.co/)** (Instituto Humboldt) — modelos
  revisados por expertos para especies colombianas. Se descargan como GeoTIFF.
- **[IUCN Red List](https://www.iucnredlist.org/resources/spatial-data-download)** —
  polígonos de rango de distribución. Hay que rasterizarlos; son rangos de extensión de
  ocurrencia, más gruesos que un SDM.
- **[Map of Life](https://mol.org/)** — agrega rangos y modelos de varias fuentes.

### Opción B — modelar desde ocurrencias

Si su especie o región no está cubierta. `spatialcom` **no** hace esta parte; necesitará
`maxent`, el paquete `ENMeval` de R, o `elapid` en Python.

**1. Descargar ocurrencias de GBIF.**

Por el portal: busque el taxón en [gbif.org](https://www.gbif.org/occurrence/search),
aplique filtros y pida la descarga. Obtendrá un **DOI que debe citar** en el manuscrito.

Programáticamente:

```python
from pygbif import occurrences as occ

datos = occ.search(
    scientificName="Ateles hybridus",
    country="CO",
    hasCoordinate=True,
    hasGeospatialIssue=False,
    basisOfRecord=["PRESERVED_SPECIMEN", "HUMAN_OBSERVATION"],
    year="1980,2025",
    limit=300,
)
```

Para volúmenes grandes use `occ.download()`, que genera un DOI citable, en lugar de
paginar `search()`.

**2. Limpiar las ocurrencias.** Es donde se decide la calidad del modelo:

- Descarte registros sin coordenadas o con `hasGeospatialIssue`.
- Filtre por incertidumbre: `coordinateUncertaintyInMeters` menor que su resolución.
- Elimine centroides de país y de departamento, sedes de instituciones y coordenadas
  (0, 0) — el paquete `CoordinateCleaner` de R los detecta automáticamente.
- Elimine duplicados y aplique *thinning* espacial (un registro por píxel) para reducir el
  sesgo de muestreo.
- Revise el resultado sobre un mapa antes de modelar.

**3. Variables ambientales.**

- **[WorldClim 2.1](https://worldclim.org/data/worldclim21.html)** — 19 variables
  bioclimáticas, resoluciones de 30 s a 10 min.
- **[CHELSA](https://chelsa-climate.org/)** — clima a alta resolución, mejor en terreno
  montañoso.
- **[ESA WorldCover](https://esa-worldcover.org/)** — cobertura del suelo a 10 m.
- Recorte todas al área de estudio y descarte las variables muy correlacionadas (VIF, o
  correlación de Pearson por encima de 0,7).

**4. Modelar y evaluar.** Divida en entrenamiento y prueba (a ser posible con bloques
espaciales, no aleatoriamente), y guarde para cada especie su **umbral de corte** —
maxTSS, maximum kappa o *10-percentile training presence*. Ese umbral es el insumo del
paso siguiente.

### Binarizar

```bash
spatialcom binarize \
  --src datos/sdm_continuos \
  --dst datos/sdm_binarios \
  --thresholds-csv datos/umbrales.csv
```

`umbrales.csv` tiene dos columnas, `species` y `threshold`:

```csv
species,threshold
Ateles_hybridus,0.42
Alouatta_seniculus,0.38
```

Sin el CSV se aplica `--threshold 0.5` a todas. Es un supuesto, no un resultado: si lo
usa, **decláre­lo en Métodos**. Un umbral por especie derivado de la evaluación del modelo
es lo que espera un revisor.

### Nombres de archivo

El nombre del archivo **es** el nombre de la especie en todas las salidas. Use
`Genero_especie.tif`, sin espacios ni acentos. Los sufijos que quiera ignorar se declaran
en `species.name_strip_suffixes`.

### Alineación

Todos los rásters deben compartir CRS y resolución. Las extensiones pueden diferir —cada
SDM viene recortado a su propia área— pero los píxeles tienen que caer sobre el mismo
enrejado. Si `spatialcom check` reporta desalineación:

```bash
gdalwarp -t_srs EPSG:4326 -tr 0.008333 0.008333 -tap \
         -r near entrada.tif salida.tif
```

`-tap` fuerza el alineado a múltiplos del tamaño de píxel, que es exactamente lo que hace
comparables dos rásters de extensiones distintas. `-r near` preserva los valores 0/1: no
use interpolación bilineal sobre datos binarios.

---

## 4. Capa de exclusión (opcional)

Celdas que no deben contar como hábitat: zonas urbanas, cuerpos de agua, cultivos
intensivos. Cualquier celda que intersecte esta capa pierde su comunidad.

- **[ESA WorldCover](https://esa-worldcover.org/)** — cobertura global a 10 m; extraiga la
  clase de superficie construida.
- **[GHSL](https://ghsl.jrc.ec.europa.eu/)** — asentamientos humanos, varias épocas.
- Cartografía nacional de uso del suelo, normalmente más precisa localmente.

Convierta el ráster de cobertura a polígonos, o use directamente una capa vectorial de
áreas urbanas.

> El criterio actual es binario: si una celda toca la capa, se excluye entera. Con celdas
> grandes esto puede ser severo — en el caso de los primates de Colombia excluyó el 6,7 %
> de las celdas. Considérelo al elegir el tamaño de celda.

---

## 5. Pérdida de cobertura forestal (opcional)

Ráster categórico donde `0` es sin pérdida y `1..N` el año en que se perdió la cobertura.

**[Hansen Global Forest Change](https://storage.googleapis.com/earthenginepartners-hansen/download.html)**
es la fuente estándar. Descargue los mosaicos `lossyear` que cubren su área (vienen en
teselas de 10° x 10°) y únalos en un VRT:

```bash
gdalbuildvrt datos/cobertura/perdida.vrt datos/cobertura/Hansen_*_lossyear_*.tif
```

Un VRT es un archivo de texto que referencia las teselas sin duplicarlas: pesa unos pocos
kilobytes y `spatialcom` lo lee como si fuera un solo ráster.

En la configuración, `year_offset: 2000` y `value_range: [1, 24]` significan que el valor
1 es 2001 y el 24 es 2024. Ajústelos a la versión que descargue.

> Advertencia de interpretación: con píxeles de 30 m, casi cualquier celda de 10 km
> contiene *algún* píxel de pérdida. En el caso de los primates de Colombia, el 99,24 % de
> las celdas registró pérdida. La cifra informativa es la distribución de niveles
> (`disturbance_level`), no ese porcentaje.

---

## 6. Regiones biogeográficas (opcional)

Para agregar los resultados por unidades con sentido ecológico.

- **[Ecorregiones RESOLVE 2017](https://ecoregions.appspot.com/)** — 846 ecorregiones
  terrestres, cobertura global.
- **[WWF Biomas](https://www.worldwildlife.org/publications/terrestrial-ecoregions-of-the-world)**.
- Cartografía nacional: en Colombia, las cinco regiones naturales (Amazonía, Andes,
  Caribe, Orinoquía, Pacífico).

Debe tener una columna con el nombre de la región. Si contiene la palabra "region" se
detecta sola; si no, indíquela en `regions.name_column`.

Cuando una celda cae en varias regiones se le asigna aquella con la que comparte **mayor
área de intersección**.

---

## 7. Datos opcionales para índices derivados

**Ocurrencias puntuales** (vectores de enfermedad, depredadores, amenazas) — CSV con
columnas de latitud y longitud. Se obtienen igual que las ocurrencias de especies, en
GBIF. Alimenta `core.indices.point_exposure_index`.

**Rasgos por especie** — CSV con una columna de especie y una o más de rasgos
(competencia de hospedero, masa corporal, gremio trófico). Fuentes: la literatura
primaria, [PanTHERIA](https://esapubs.org/archive/ecol/E090/184/),
[EltonTraits](https://esapubs.org/archive/ecol/E095/178/). Alimenta
`core.indices.trait_weighted_index`, base de los índices de dilución y amplificación.

---

## 8. Estructura de carpetas

```bash
spatialcom init mi_proyecto
```

crea:

```
mi_proyecto/
├── config.yaml              configuración comentada, lista para editar
├── datos/
│   ├── limite/              área de estudio
│   ├── sdm_continuos/       modelos sin binarizar
│   ├── sdm_binarios/        salida de 'binarize'
│   ├── uso_suelo/           capas de exclusión
│   ├── cobertura/           pérdida de cobertura
│   └── regiones/            unidades biogeográficas
└── resultados/
```

---

## 9. Comprobar antes de correr

```bash
spatialcom check mi_proyecto/config.yaml
```

Revisa, para cada insumo: que exista, que tenga CRS, que los rásters compartan CRS y
resolución, que estén sobre el mismo enrejado, que los valores sean 0/1 y que las capas
opcionales se solapen realmente con la cuadrícula. Devuelve código 1 si falta algo
obligatorio, así que sirve como puerta previa en un script.

---

## 10. Citación y licencias

Cada fuente tiene sus condiciones y casi todas exigen citación:

- **GBIF** — cite el DOI de la descarga, no el portal. Es lo que hace reproducible su
  conjunto de ocurrencias.
- **BioModelos** — cite el Instituto Humboldt y los autores de cada modelo.
- **Hansen GFC** — cite Hansen et al. (2013), *Science* 342:850-853.
- **WorldClim** — cite Fick & Hijmans (2017).
- **GADM** — libre para uso académico, prohibido el uso comercial.
- **IUCN** — requiere aceptar sus términos y citar la versión de la Lista Roja.

Anote la fecha de descarga de cada capa: los datos cambian entre versiones y sin esa fecha
su análisis deja de ser reproducible.
