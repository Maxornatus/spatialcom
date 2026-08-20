# Leaflet incluido

Copia íntegra de la distribución oficial de Leaflet, incrustada para que los mapas
generados funcionen sin conexión.

- **Versión:** 1.9.4
- **Origen:** https://unpkg.com/leaflet@1.9.4/dist/
- **Descargado:** 2026-08-20
- **Licencia:** BSD 2-Clause, ver `LICENSE` (© 2010-2023 Vladimir Agafonkin,
  © 2010-2011 CloudMade)

Archivos: `leaflet.js`, `leaflet.css`, `images/{layers,layers-2x,marker-icon}.png`.
Los `.png` son los únicos recursos referenciados por `url()` dentro de la hoja de
estilos; al generar un mapa se incrustan como data URI, de modo que el HTML resultante
no hace ninguna petición externa.

No se incluye `leaflet.js.map`: el comentario `sourceMappingURL` se elimina al incrustar
el script.

Para actualizar, descargue los cinco archivos de la nueva versión, reemplácelos aquí y
ajuste la versión en este documento y en `spatialcom.viz.webmap.LEAFLET_VERSION`.
