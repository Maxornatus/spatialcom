# Mapa web interactivo

`spatialcom.viz.webmap` genera un único archivo HTML autónomo con las comunidades sobre
un mapa, filtrables por especie, región, cluster y riqueza. No necesita servidor: se abre
con doble clic, se adjunta a un correo o se sube como material suplementario.

## Generarlo

Se produce automáticamente como paso 7 de `spatialcom run`. Para regenerarlo sin repetir
el análisis —cambiar el título, la simplificación o el mapa base— basta con:

```bash
spatialcom webmap configs/primates_colombia.yaml
```

Desde la API:

```python
from spatialcom.viz.webmap import build_webmap

build_webmap(
    grid, catalog, "resultados/mapa",
    region_column="Subregion",
    title="Comunidades de primates de Colombia",
    simplify_tolerance=0.002,
    basemap="carto",
)
```

## Configuración

```yaml
webmap:
  enabled: true
  filename: 07_mapa_comunidades
  title: Comunidades de primates de Colombia
  subtitle: ""
  simplify_tolerance: 0.002   # grados; 0 conserva la geometría exacta
  coord_precision: 4          # ~11 m en el ecuador
  basemap: none               # none | carto | osm
  leaflet: bundled            # bundled | cdn | ruta a una carpeta propia
  context_path: null          # contorno de referencia; null = usar regions.path
```

## Pestañas

El archivo tiene dos vistas que comparten el mismo panel de filtros: lo que se filtra en
una se refleja inmediatamente en la otra.

- **Mapa** — las comunidades sobre el territorio.
- **Gráficas** — top 10 de comunidades por riqueza y por extensión, recalculado con los
  filtros activos.
- **Tabla** — el catálogo completo de comunidades, ordenable, filtrable y exportable a
  CSV.
- **Figuras** — las figuras estáticas del análisis (`spatialcom figures`), incrustadas.
  Esta pestaña **no** reacciona a los filtros y el panel se atenúa para dejarlo claro.

---

## Controles

| Control | Comportamiento |
|---|---|
| **Especies** | Búsqueda incremental sobre la lista; junto a cada nombre, las celdas que ocupa. Dos modos: *contiene alguna* (unión) y *contiene todas* (intersección). |
| **Región** | Casillas por región natural. Recorta la geometría a la parte contenida en la región, no muestra la comunidad entera. |
| **Cluster** | Casillas por grupo del clustering jerárquico. Con `cluster.min_cells > 1` aparece además **Sin grupo asignado**, marcada por omisión: son las comunidades que quedaron fuera del clustering por su poca extensión, y sin esa casilla desaparecerían del mapa sin avisar. |
| **Riqueza** | Rango mínimo y máximo de número de especies. Bajo el control se indica el rango observado en los datos, para que un mínimo alto no se confunda con un filtro activo. |
| **Colorear por** | Riqueza, extensión (escala logarítmica), cluster, región o pérdida de cobertura. La leyenda se adapta. |
| **Clic en el mapa** | Ficha de la comunidad: identificador, riqueza, extensión total, celdas en la región, cluster, pérdida de cobertura y lista completa de especies en cursiva. |

El contador superior muestra, en vivo, comunidades visibles, celdas visibles y número de
especies representadas en la selección.

---

## Descargar imágenes

### El mapa

Botón **Imagen PNG** en el panel, con escala 1x, 2x o 3x. La imagen se compone en un
`canvas` local —sin servicios de render ni peticiones de red— y reproduce:

- el **encuadre actual**: el mismo centro y zoom que hay en pantalla;
- solo las comunidades que **pasan los filtros**, con el color activo;
- el contorno de referencia debajo;
- una cabecera con el título, el resumen textual de los filtros aplicados y los conteos;
- la leyenda correspondiente al modo de color.

Que los filtros queden **escritos en la propia imagen** es deliberado: una figura que
muestra un subconjunto sin decir cuál es intrazable en cuanto sale del navegador.

> Con `basemap: carto` u `osm`, las teselas **no** se incluyen: son de otro dominio y
> contaminan el `canvas`, lo que impide exportarlo. La imagen lleva una nota al pie
> indicándolo. Con `basemap: none` —el valor por omisión— no hay diferencia entre lo que
> se ve y lo que se exporta.

### Las gráficas

Cada gráfica tiene botones **SVG** y **PNG**. El SVG es vectorial y editable en Inkscape o
Illustrator: es el formato indicado para una figura de manuscrito. El PNG se rasteriza a
2x a partir del mismo SVG.

Los nombres de archivo se derivan del título del mapa
(`comunidades_de_primates_de_colombia_top10_riqueza.svg`).

---

## Las gráficas top 10

**Por riqueza** ordena por número de especies; a igual riqueza manda la extensión visible.
**Por extensión** ordena por celdas visibles —las que quedan dentro de los filtros, no la
extensión total de la comunidad—, coherente con el contador superior.

### Etiquetas comparativas

Las comunidades más ricas comparten casi siempre el mismo núcleo de especies
generalistas. Rotular cada barra con su composición completa produce diez etiquetas que
empiezan igual y no distinguen nada.

En su lugar se extrae el **núcleo común** al conjunto mostrado, se enuncia una sola vez
sobre la gráfica, y cada barra se rotula con lo que **añade** a ese núcleo:

```
Nucleo comun a las 10: A. seniculus, A. vociferans, A. belzebuth +6
  1. + C. lugens, C. medemi, L. fuscus +3
  2. + C. lucifer, C. lugens, L. fuscus +3
  3. + C. medemi, L. fuscus, L. nigricollis +2
```

Cuando no hay núcleo compartido —el caso habitual de la gráfica por extensión, donde las
comunidades son heterogéneas— se muestra la composición abreviada de cada una. El
identificador y la lista completa están siempre en el tooltip de la barra.

## La pestaña de tabla

El catálogo de comunidades en forma tabular, con una fila por comunidad visible.

| Columna | Contenido |
|---|---|
| # | Posición en el orden actual |
| Riqueza | Número de especies |
| Celdas | Celdas **visibles** bajo los filtros activos |
| Ext. total | Extensión total de la comunidad, filtros aparte |
| Cluster | Grupo asignado, o `sin grupo` si `min_cells` la dejó fuera |
| Pérdida % | Pérdida de cobertura |
| Región | Regiones en las que aparece |
| Composición | Primeras 4 especies en cursiva, con enlace para desplegar el resto |
| Identificador | El hash determinista de la composición |

**Mínimo de celdas.** Un control propio, con valor 2 por omisión: descarta las comunidades
de una sola celda. Con muchas especies esas son la inmensa mayoría —en murciélagos, 6.128
de 7.010— y no describen un ensamblaje repetido sino una celda concreta. Ponerlo a 1
muestra el catálogo entero.

**Comparte los filtros del panel.** Lo que se filtre por especie, región, cluster o
riqueza se refleja en la tabla, igual que en el mapa y en las gráficas. La columna
*Celdas* cuenta solo las visibles, coherente con el contador superior.

**Ordenar** pulsando cualquier cabecera; una segunda pulsación invierte el sentido. Por
omisión ordena por extensión visible, de mayor a menor.

**Buscar** por nombre de especie o por identificador de comunidad.

**Descargar CSV** exporta exactamente las filas mostradas, en el orden mostrado, con la
composición completa —no la abreviada— en la columna correspondiente. El archivo lleva BOM
para que Excel respete los acentos, y escapa comas y comillas: la lista de especies
contiene comas y sin escapar rompería las columnas.

---

## La pestaña de figuras

Las figuras que produce el paso 7 (`fig_dendrograma`, `fig_heatmap_incidencia`,
`fig_riqueza_vs_perturbacion`, `fig_perturbacion_por_region`,
`fig_perturbacion_por_cluster`, `figS_diagnostico_k`) se incrustan en el HTML, cada una
con su título, su pie explicativo y un enlace de descarga.

Se controla con `webmap.embed_figures` y toma lo que haya en `<run_dir>/figuras`. Con
`embed_figures: false` la pestaña desaparece; también se oculta sola si esa carpeta no
existe.

### Por qué van como `<img>` y no como SVG en línea

Matplotlib genera identificadores de glifo y de recorte dentro de cada SVG. Fusionar seis
figuras en un mismo documento HTML haría colisionar esos identificadores —y el CSS de la
página se aplicaría a los elementos del gráfico—. Como data URI dentro de un `<img>`, cada
figura conserva su propio espacio de nombres y su propio estilo, al precio de un 33 % de
sobrecoste por la codificación base64.

### Orden

No es alfabético. Sigue la secuencia del argumento —cómo se construyeron los grupos, qué
contienen, cómo se relacionan con la perturbación— y deja las suplementarias al final; el
orden lo fija el diccionario `FIGURE_CAPTIONS` en `viz/webmap.py`. Ordenar por nombre de
archivo pondría `figS_diagnostico_k` la primera.

### Tamaño

Las seis figuras en SVG suman unos 820 KB, que en base64 son ~1,1 MB: el HTML pasa de
765 KB a **1,9 MB**. Si necesita un archivo más ligero, genere las figuras en PNG
(`output.figure_format: png`), incruste solo algunas pasando una lista a `build_webmap`,
o ponga `embed_figures: false`.

### Interactivas frente a estáticas

| | Gráficas | Figuras |
|---|---|---|
| Reaccionan a los filtros | sí | no |
| Qué describen | la selección actual | el análisis completo |
| Formato | SVG generado en el navegador | SVG/PNG de matplotlib |
| Para el manuscrito | exploración | figuras finales |

---

## Semántica de los contadores

Las celdas se disuelven por pareja **(comunidad, región)**. Cada rasgo del mapa lleva su
propio número de celdas, de modo que al filtrar por Amazonas el contador da las celdas
amazónicas de esas comunidades, no la extensión total de comunidades que también se
extienden a los Llanos. Los totales por región coinciden con `05_region_x_cluster.csv`.

El contador de *comunidades* deduplica por identificador: una comunidad presente en dos
regiones cuenta una vez.

## Tamaño del archivo

Tres mecanismos lo controlan:

1. **Disolución** por comunidad y región: de ~9.700 polígonos de celda a unos cientos de
   segmentos.
2. **Simplificación** con `simplify_tolerance` (Douglas-Peucker con topología preservada).
3. **Redondeo** de coordenadas a `coord_precision` decimales.

Para el caso de los primates de Colombia: 9,8 MB de geometría en crudo → **765 KB** de
archivo, de los cuales unos 165 KB son Leaflet incrustado; con las seis figuras
estáticas incrustadas el total sube a 1,9 MB. Subir `coord_precision` a 6 o poner `simplify_tolerance: 0` devuelve la
geometría exacta a costa del tamaño.

Los atributos no se repiten por geometría: cada rasgo apunta por índice a una tabla de
comunidades, y las especies se codifican como índices sobre una lista única.

## Uso sin conexión

**Es el comportamiento por omisión.** El paquete incluye Leaflet 1.9.4
(`viz/assets/leaflet/`, BSD 2-Clause, ver `PROCEDENCIA.md`) y lo incrusta en el HTML:

* La hoja de estilos de Leaflet referencia tres PNG (`layers.png`, `layers-2x.png`,
  `marker-icon.png`). Se incrustan como data URI, porque una vez el CSS está dentro de un
  `<style>` esas rutas relativas se resolverían respecto al HTML y fallarían.
* El comentario `sourceMappingURL` se elimina: apunta a `leaflet.js.map`, que no se
  incluye.
* Con `basemap: none`, las URL de teselas ni siquiera llegan al archivo: Python las aporta
  en el payload solo cuando hay mapa base, de modo que un revisor no encuentra direcciones
  externas que parezcan dependencias.
* En su lugar se embebe un **contorno de referencia** (por omisión, la capa de regiones
  naturales, simplificada a 0,01°) que da el contexto geográfico que darían las teselas.

Comprobado con el registro de red del navegador: al abrir el mapa generado se hace **una
sola petición, la del propio archivo**.

### Variantes

| Objetivo | Configuración |
|---|---|
| Offline total (por omisión) | `leaflet: bundled`, `basemap: none` |
| Fondo cartográfico con conexión | `leaflet: bundled`, `basemap: carto` |
| Archivo mínimo, requiere red | `leaflet: cdn`, `basemap: carto` |
| Copia propia de Leaflet | `leaflet: ./assets/leaflet` |

`leaflet: cdn` ahorra unos 165 KB, a cambio de que el archivo no abra sin conexión.

## Llevárselo a otro equipo

El HTML es **un solo archivo autosuficiente**. Basta copiarlo: no necesita el resto de la
carpeta de resultados, ni Python, ni `spatialcom`, ni conexión.

Comprobado copiando únicamente el `.html` a una carpeta vacía: las cuatro pestañas
funcionan y el navegador hace **una sola petición, la del propio archivo**.

Lo que hace posible eso:

* Ninguna referencia relativa. La única URL externa del archivo es el enlace de atribución
  a `leafletjs.com`, que es un enlace clicable, no un recurso que se descargue.
* Sin `fetch`, sin `XMLHttpRequest`, sin `type="module"`: todo eso falla o queda
  restringido cuando el documento se abre desde el disco.
* Sin tipografías externas; solo la del sistema.
* Leaflet, los datos y las figuras van incrustados.

### Abrirlo con doble clic (`file://`)

Al abrirlo desde el disco el documento vive en un **origen opaco**, con reglas más
estrictas que al servirlo por HTTP. Dos consecuencias que se tuvieron en cuenta:

* La exportación PNG de las gráficas rasteriza un SVG sobre un `canvas`. Si la imagen
  intermedia se cargara desde una URL `blob:`, el canvas quedaría contaminado y `toBlob`
  fallaría con `SecurityError`. Se carga desde un **data URI**, que se considera del mismo
  origen y no contamina.
* La exportación PNG del mapa dibuja únicamente trazados vectoriales, sin imágenes
  intermedias, así que nunca estuvo afectada.

Si aun así una descarga fallara, el aviso dice qué ocurrió y sugiere el SVG, que no
depende del `canvas`.

### Enviarlo por correo

6,8 MB para murciélagos y 1,9 MB para primates. Si el gestor de correo lo rechaza, las
opciones son `webmap.embed_figures: false` (quita ~1,5 MB) o `leaflet: cdn` (quita ~165 KB
a cambio de necesitar conexión).

---

### Actualizar la copia de Leaflet

Descargue `leaflet.js`, `leaflet.css` y las tres imágenes de la nueva versión, sustitúyalos
en `src/spatialcom/viz/assets/leaflet/` y actualice `LEAFLET_VERSION` en
`spatialcom.viz.webmap` y la versión en `PROCEDENCIA.md`.
