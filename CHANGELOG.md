# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Este proyecto sigue [Versionado Semántico](https://semver.org/lang/es/).

## [No publicado]

## [0.1.0] — 2026-08-20

Primera versión pública.

### Añadido

- Delineación de comunidades espaciales a partir de rásters SDM binarios sobre una
  cuadrícula regular, con identificador de composición determinista.
- Clasificación jerárquica de comunidades (Jaccard, enlace, selección de *k* por
  silueta, r cofenética) y ordenación (PCoA, NMDS, PCA, t-SNE).
- Caracterización: exclusión de celdas, pérdida de cobertura por año y niveles de
  perturbación, vinculación con regiones biogeográficas, índices ponderados por rasgos.
- Seis figuras del manuscrito y un mapa web HTML autónomo que abre sin conexión
  (Leaflet 1.9.4 incrustado).
- CLI `spatialcom`: `init`, `make-grid`, `binarize`, `check`, `validate`, `run`,
  `step`, `figures`, `webmap`.
- API por componentes (`spatialcom.io`, `.core`, `.cluster`, `.viz`) y orquestada
  (`Config` + `Pipeline`).
- 146 pruebas sobre datos sintéticos, sin dependencia de los datos del proyecto.

[No publicado]: https://github.com/Maxornatus/spatialcom/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Maxornatus/spatialcom/releases/tag/v0.1.0
