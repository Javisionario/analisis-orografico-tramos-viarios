# Version v2_3

Fecha: 2026-07-06

## Cambios principales

- Version activa actualizada a `v2_3`.
- Suavizado simple `0-10` revisado con ventanas mas amplias en niveles altos:
  - `0`: sin suavizado;
  - `1`: 3 puntos, polinomio teorico 4;
  - `2`: 5 puntos, polinomio 3;
  - `3`: 9 puntos, polinomio 3;
  - `4`: 13 puntos, polinomio 2;
  - `5`: 17 puntos, polinomio 2;
  - `6`: 21 puntos, polinomio 2;
  - `7`: 27 puntos, polinomio 2;
  - `8`: 33 puntos, polinomio 2;
  - `9`: 41 puntos, polinomio 1;
  - `10`: 51 puntos, polinomio 1.
- Suavizado avanzado:
  - ventana hasta `55` puntos;
  - solo valores impares;
  - slider de polinomio invertido visualmente: izquierda `Polinomio 4`, derecha `Polinomio 1`;
  - se guarda `sg_polyorder_slider_visual` para trazabilidad.
- Umbral de pendiente anomala con paso `0,5 %`.
- Nueva opcion de perfil `Mostrar linea muestreada de elevaciones`, desmarcada por defecto.
- El muestreo altimetrico comprueba CRS del tramo y del raster y transforma coordenadas si no coinciden.
- El MDT de mapas se reproyecta con `rasterio.warp.reproject` a `EPSG:3857` y al tamano exacto de `MAP_MAIN`.
- Las curvas de nivel se extraen del raster reproyectado y se dibujan en coordenadas de pixel del mapa principal.
- Leyendas:
  - mas espacio entre encabezado y categorias;
  - leyenda algo mas alta;
  - mapa de pendientes con dos columnas: `Elevaciones` y `Pendientes`.

## Metadatos nuevos o revisados

- `muestreo_altimetrico.perfil_crs_tramo`;
- `muestreo_altimetrico.perfil_crs_raster`;
- `muestreo_altimetrico.perfil_transformacion_crs_aplicada`;
- `muestreo_altimetrico.perfil_n_puntos_muestreo`;
- `muestreo_altimetrico.perfil_n_cotas_validas`;
- `elevaciones_reproyectadas`;
- `elevaciones_crs_origen`;
- `elevaciones_crs_destino`;
- `elevaciones_target_bounds_3857`;
- `elevaciones_target_width`;
- `elevaciones_target_height`;
- `elevaciones_transform_destino`;
- `elevaciones_resampling`;
- `elevaciones_alineacion`;
- `curvas_usando_raster_reproyectado`;
- `mostrar_linea_muestreada_elevaciones`.

## Limitaciones conocidas

- El nivel simple `1` mantiene la tabla teorica solicitada con polinomio 4 y ventana 3; si la combinacion no es valida para Savitzky-Golay, el backend reduce automaticamente el polinomio y registra advertencia.
- La confirmacion visual fina de alineacion MDT debe revisarse sobre PNG generado en navegador/visor de imagen.
- La composición cartográfica se mantiene en un módulo PIL propio.

## QA recomendada

```powershell
..\.venv\Scripts\python.exe -m compileall src app.py
..\.venv\Scripts\python.exe -m unittest discover -s tests
```

Manual:

- Probar suavizado simple `0`, `4`, `7` y `10`.
- Probar suavizado avanzado con ventana alta y polinomio hacia la derecha.
- Probar umbrales `10 %`, `10,5 %` y `17 %`.
- Generar perfiles con y sin linea muestreada.
- Generar `Ma-2210` y revisar alineacion de MDT/curvas frente a Positron, vias y costa.
- Revisar leyenda de pendientes en dos columnas.
- Confirmar mapas `4015 x 2834`, `RGB`, `600 dpi`.

## QA realizada

Caso backend probado:

```text
Carretera: Ma-2210
PK inicio: 2+000
PK fin: 19+600
Sentido: creciente
Suavizado: 10/10
Umbral anomalia: 10,5 %
Linea muestreada de elevaciones: activada
```

Resultado:

- MDT usado desde WCS/cache con `Elevacion4258_5`, `5 m`.
- `bbox_origen = map_main`.
- Raster MDT descargado para encuadre final: `2639 x 2581`.
- Overlay de elevaciones reproyectado a `EPSG:3857`.
- Target overlay: `2799 x 2740`, igual a `MAP_MAIN`.
- Curvas de nivel usando raster reproyectado: `true`.
- CRS tramo: `EPSG:25830`.
- CRS raster: `EPSG:25830`.
- Transformacion CRS en muestreo: `false`.
- Puntos de muestreo: `234`.
- Cotas validas: `234`.
- Mapa de localizacion PNG: `4015 x 2834`, `RGB`, `600 dpi`.
- Mapa de pendientes PNG: `4015 x 2834`, `RGB`, `600 dpi`.
- Revisión visual: desaparece el rectangulo oblicuo de cobertura MDT; el relieve queda alineado con costa, Positron, vias y PKs.

## Confirmacion

Esta versión documenta exclusivamente cambios de la herramienta.

## Ajustes posteriores incluidos

- Se elimina el texto auxiliar de orientacion del slider de polinomio avanzado.
- Se corrige el texto `Mostrar linea muestreada de elevaciones` y se deja como checkbox normal sin recuadro destacado.
- Se incorpora `Mostrar anotaciones de lineas de nivel`, marcado por defecto. Si se desmarca, las curvas siguen presentes y solo se ocultan las etiquetas de cota.
- Los sliders de transparencia de elevaciones muestran porcentaje visible.
- Leyendas:
  - `MAP_LEGEND_Y_OFFSET_CM`: `0.30 cm` -> `0.24 cm`, relativo en cm;
  - `MAP_LEGEND_HEADING_STEP_PX`: `116 px` -> `132 px`, absoluto en px;
  - `heading_gap` en leyenda de dos columnas: `72 px` -> `92 px`, absoluto en px;
  - la alineacion de simbolos y etiquetas usa centro vertical compartido.
- El eje Y de perfiles usa pasos bonitos con objetivo de 5-7 etiquetas principales.
- Los rangos de pendientes aplanadas incluyen la pendiente bruta maxima aplanada y el PK asociado.
- El bloque `Parametros empleados` queda simplificado para usuario; los detalles internos permanecen en metadatos.

## Ajuste fino de leyendas y curvas

Leyenda de dos columnas del mapa de pendientes, valores absolutos en px:

- `font`: `42` -> `46`;
- `heading_font`: `48` -> `52`;
- `row_step`: `54` -> `62`;
- `swatch_w`: `58` -> `62`;
- `swatch_h`: `34` -> `38`;
- `gap`: `34` -> `20`;
- `heading_gap`: se mantiene en `92`.

La alineacion mantiene centro vertical comun para simbolo y etiqueta (`symbol_and_text_centered`) y `anchor="lm"` para el texto.

La leyenda general no se toca en este ajuste:

- `MAP_LEGEND_Y_OFFSET_CM = 0.24`;
- `MAP_LEGEND_LINE_STEP_PX = 76`;
- `MAP_LEGEND_HEADING_STEP_PX = 132`;
- `MAP_LEGEND_ROW_MIN_PX = 132`.

Etiquetas de curvas de nivel:

- sin halo;
- rotadas segun tangente local;
- angulo normalizado para evitar texto invertido;
- hueco visual en la curva bajo la etiqueta;
- solape basico evitado entre cajas de etiquetas;
- respetan `mostrar_anotaciones_curvas_nivel`.

El hueco se implementa de forma aproximada omitiendo puntos alrededor del indice de etiqueta; no es un recorte vectorial exacto por longitud continua.
