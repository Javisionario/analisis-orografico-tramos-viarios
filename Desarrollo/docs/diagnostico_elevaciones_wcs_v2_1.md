# Diagnostico de elevaciones MDT/WCS v2_1

Fecha: 2026-07-06

Este diagnóstico revisa por qué las elevaciones pueden no verse en los mapas PIL.

## Que intenta hacer la herramienta

- Servicio WCS configurado: `https://servicios.idee.es/wcs-inspire/mdt?VERSION=1.0.0`.
- Resolucion preferida en interfaz: `5 m`.
- Fallback previsto: `25 m` si falla 5 m.
- CRS de trabajo por defecto: `EPSG:25830`.
- BBOX WCS: bbox proyectado del tramo ampliado, en el CRS interno del tramo.
- Cache MDT: `cache/mdt`.
- Compositor de mapa: PIL propio.
- Sistema visual del compositor: geometria en `EPSG:4326` y proyeccion Web Mercator para teselas Positron.

Orden de composicion actual:

1. Positron.
2. Elevaciones discretas como overlay RGBA.
3. Curvas de nivel.
4. Vias de fondo.
5. Tramo/segmentos de pendiente.
6. PKs.
7. Marcos, escala, norte y leyendas.

## Metadatos de diagnostico añadidos

En `metadatos.json`, dentro de cada mapa, se guardan:

- `elevaciones_intento_renderizado`;
- `elevaciones_renderizadas`;
- `elevaciones_motivo_no_renderizado`;
- `mdt_path`;
- `mdt_exists`;
- `mdt_crs`;
- `mdt_bounds`;
- `mdt_width`;
- `mdt_height`;
- `mdt_nodata`;
- `mdt_min`;
- `mdt_max`;
- `mdt_resolution`;
- `elevaciones_clases`;
- `elevaciones_alpha`;
- `orden_composicion`;
- `curvas_nivel_generadas`;
- `n_curvas`.

## Puntos posibles de fallo

- El WCS no responde o devuelve error temporal.
- La cobertura elegida por GetCapabilities no es compatible con el bbox/resolucion.
- El CRS de peticion no esta soportado por el WCS.
- El bbox se envia en un CRS distinto al esperado.
- El raster existe en cache pero no intersecta el encuadre del mapa tras pasar a lon/lat.
- El raster abre con rasterio, pero toda la ventana queda en nodata.
- El raster tiene min/max finitos, pero no se generan clases de elevacion.
- El alpha es bajo y la elevacion queda visualmente demasiado sutil sobre Positron.
- El overlay se compone fuera del clip `MAP_MAIN`.
- La diferencia entre `EPSG:25830` y el encuadre Web Mercator exige una reproyeccion raster mas estricta en ciertos ambitos.
- Existe un cache antiguo/corrupto.
- El fallo queda registrado como warning y el mapa continua sin bloquear.

## Opciones de correccion

- Mantener WCS y corregir reproyeccion/composicion si los metadatos muestran bbox/CRS incoherentes.
- Precachear MDT por ambito y validar min/max antes de componer.
- Usar COORD_Z de PKs solo como fallback de perfil, no como mapa continuo.
- Configurar un MDT local si se dispone de raster fiable.
- Usar otro servicio MDT si el WCS resulta inestable.
- Desactivar elevaciones con aviso claro cuando el raster no sea valido.

## Estado v2_1

No se rediseña el WCS en esta iteracion. Se añaden metadatos para diagnosticar el fallo real en una generacion con datos locales. Las correcciones visuales o de reproyeccion se dejan condicionadas al resultado de esos metadatos.
