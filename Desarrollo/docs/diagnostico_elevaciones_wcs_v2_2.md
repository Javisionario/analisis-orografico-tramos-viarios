# Diagnostico de elevaciones MDT/WCS v2_2

Fecha: 2026-07-06

## Diagnostico de partida

En `v2_1`, una generacion con `Ma-2210` registro:

- `mdt.source = no_disponible`;
- `mdt.path = null`;
- `coverage = null`;
- `resolucion_m = null`;
- `perfil.fuente_altimetrica = pk_coord_z`;
- `elevaciones_renderizadas = false`;
- `curvas_nivel_generadas = false`.

El log indicaba fallos de coberturas a `5 m` y `25 m` con respuesta vacia o demasiado corta. La herramienta estaba usando `OWSLib.getCoverage()` con `format="GeoTIFF"` y parametro `identifier`, lo que no replicaba la peticion funcional observada en QGIS.

## Peticion QGIS adoptada

QGIS obtiene un GeoTIFF valido con WCS 1.0.0:

```text
SERVICE=WCS
VERSION=1.0.0
REQUEST=GetCoverage
FORMAT=GEOTIFFINT16
COVERAGE=Elevacion4258_5
CRS=EPSG:25830
RESPONSE_CRS=EPSG:25830
WIDTH=...
HEIGHT=...
```

En `v2_2`, `src/mdt_wcs.py` construye explicitamente esa peticion con `requests.get()` y deja `OWSLib` solo para descubrir coberturas adicionales si las preferidas fallan.

## Orden de prueba

1. `Elevacion4258_5` con `FORMAT=GEOTIFFINT16`.
2. `Elevacion4258_25` con `FORMAT=GEOTIFFINT16`.
3. Coberturas adicionales detectadas por `GetCapabilities`.

WCS 2.0.1 queda como segunda via futura; no sustituye la ruta QGIS 1.0.0 mientras esta funcione.

## Validacion de respuesta

Antes de guardar cache `.tif`, se valida:

- HTTP `200`;
- `Content-Type` compatible con TIFF/GeoTIFF;
- firma TIFF `II*` o `MM*`;
- apertura con `rasterio`;
- `width > 0`;
- `height > 0`;
- CRS existente;
- transform valido;
- valores finitos en una muestra.

Si falla:

- no se guarda como cache valida;
- si existia cache invalida, se descarta;
- se guarda diagnostico de URL, parametros, status, content-type, bytes y texto inicial si la respuesta parece XML/texto.

## Descarga teselada

Si el raster completo supera `1024 x 1024 px` o si la descarga completa no produce un TIFF valido, se intenta descarga por teselas WCS con el mismo esquema QGIS:

- tile maximo: `1024 x 1024 px`;
- validacion individual de cada tile;
- mosaico con `rasterio.merge` si todos los tiles son validos.

Metadatos:

- `wcs_modo_descarga`;
- `wcs_tile_width`;
- `wcs_tile_height`;
- `n_tiles`;
- `n_tiles_ok`;
- `n_tiles_error`.

## Prueba realizada

Se probo el BBOX de ejemplo de QGIS:

```text
BBOX=1007999.8058,4435142.5104,1010523.1843,4435700.4002
CRS=EPSG:25830
COVERAGE=Elevacion4258_5
FORMAT=GEOTIFFINT16
```

Resultado fuera del sandbox de red:

- `source = wcs`;
- `coverage = Elevacion4258_5`;
- `resolution = 5.0`;
- `wcs_modo_descarga = directa`;
- `mdt_width = 505`;
- `mdt_height = 112`;
- `mdt_crs = EPSG:25830`.

## Generacion Ma-2210 v2_2

Caso probado:

```text
Carretera: Ma-2210
PK inicio: 2+000
PK fin: 19+600
Sentido: creciente
Resolucion solicitada: 5 m
```

Resultado:

- `altimetria.fuente_altimetrica_usada = mdt`;
- `altimetria.fuente_altimetrica_usada_label = MDT/WCS`;
- `coverage_mdt_usada = Elevacion4258_5`;
- `resolucion_mdt_usada = 5.0`;
- `fallback_altimetrico_aplicado = false`;
- `wcs_modo_descarga = teselada`;
- `mdt_width = 2339`;
- `mdt_height = 1773`;
- `mdt_crs = EPSG:25830`;
- `elevaciones_renderizadas = true` en localizacion y pendientes;
- `curvas_nivel_generadas = true`;
- `n_curvas = 83`.

## Decision final

La herramienta `v2_2` prioriza la ruta QGIS WCS 1.0.0 con `GEOTIFFINT16`. Si esta ruta falla en una ejecucion concreta, la interfaz y metadatos deben mostrar claramente si se ha usado fallback a cotas de PK o perfil provisional.
