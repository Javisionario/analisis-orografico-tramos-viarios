# Parametros tecnicos

Fecha de revision: 2026-07-05

Este documento explica los parametros de la herramienta para un usuario tecnico no especialista. Los parametros se aplican a un unico tramo definido por carretera, sentido, PK inicio y PK fin.

## Resumen

| Parametro | Valor por defecto | Rango/interfaz | Afecta a | Efecto practico |
|---|---:|---|---|---|
| Resolucion MDT | `5 m` | `5 m`, `25 m` | Perfil, elevaciones de mapas, metadatos | Define la resolucion preferida del MDT descargado o leido de cache. Si falla 5 m, se intenta 25 m. |
| Intervalo de muestreo altimetrico | `75 m` | slider `20-250 m` | Perfil y pendiente derivada | Distancia entre puntos consecutivos donde se consulta la cota sobre la geometria. |
| Segmento pendiente | `auto` | `auto`, `100`, `200`, `500`, `1000 m` | Mapa de pendientes y GeoPackage/GeoJSON de segmentos | Longitud de cada tramo cartografico usado para simbolizar pendiente media. |
| Umbral de pendiente anomala | `20 %` | slider `5-40 %` | Perfil, mapa de pendientes, CSV/GPKG/GeoJSON | Aplana solo la representacion de pendientes extremas y marca anomalias. |
| Origen eje Y elevacion | `0 m` | `0 m`, `adaptado` | Grafico de perfil | Define si el eje de cota empieza en cero o se ajusta al rango altitudinal. |
| Alpha localizacion | `0.34` | `0-1` | Mapa de localizacion | Transparencia de la capa de elevaciones discretas. |
| Alpha pendientes | `0.46` | `0-1` | Mapa de pendientes | Transparencia de la capa de elevaciones discretas. |
| Suavizado Savitzky-Golay | `4/10` | slider `0-10` | Perfil y pendiente cartografica | Suaviza la serie de cotas ya muestreada, sin modificar geometria ni PK. |

## Resolucion MDT

La resolucion MDT indica el tamano de pixel preferido para obtener cotas.

- `5 m`: preferencia de detalle alto.
- `25 m`: preferencia mas ligera y robusta en ambitos amplios.

La interfaz parte de `5 m`. Si el WCS no esta disponible a 5 m, el backend intenta fallback a `25 m` y deja advertencia. Si tampoco esta disponible, intenta usar cache o fallback con cotas de PK cuando existen. La resolucion real usada queda en `metadatos.json`.

## Intervalo de muestreo altimetrico

Es la distancia entre puntos consecutivos sobre la linea donde se consulta la cota. No es el suavizado.

Un intervalo pequeno crea mas puntos y puede capturar mas detalle, pero tambien puede recoger ruido del raster. Un intervalo grande reduce ruido y peso de calculo, pero simplifica el perfil.

Regla metodologica:

- Recomendado: intervalo >= `4 x tamano de pixel MDT`.
- Si MDT = `5 m`, recomendado minimo `20 m`.
- Si MDT = `25 m`, recomendado minimo `100 m`.
- Si el intervalo queda por debajo del tamano de pixel, el backend lo ajusta al pixel y registra advertencia.
- Si queda entre `1 x pixel` y `4 x pixel`, el backend permite generar, pero registra advertencia metodologica.

Metadatos guardados:

- resolucion MDT real;
- tamano de pixel;
- intervalo elegido;
- ratio intervalo/pixel;
- intervalo recomendado minimo;
- advertencias.

## Suavizado Savitzky-Golay

El suavizado se aplica despues del muestreo altimetrico. No cambia la geometria del tramo ni los PK.

- `0`: sin suavizado; `cota_suavizada_m = cota_bruta_m`.
- `4`: valor recomendado por defecto.
- `10`: suavizado alto.

Internamente el slider controla una ventana Savitzky-Golay en numero impar de puntos. La ventana teorica, la ventana aplicada y el orden polinomico quedan registrados en metadatos.

| Slider | Ventana teorica | Polyorder teorico | Descripcion |
|---:|---:|---:|---|
| 0 | 0 | 0 | Sin suavizado |
| 1 | 3 | 4 | Efecto muy leve |
| 2 | 5 | 3 | Leve |
| 3 | 9 | 3 | Leve-medio |
| 4 | 13 | 2 | Medio-bajo, valor por defecto |
| 5 | 17 | 2 | Medio |
| 6 | 21 | 2 | Medio-alto |
| 7 | 27 | 2 | Alto |
| 8 | 33 | 2 | Alto estable |
| 9 | 41 | 1 | Muy alto |
| 10 | 51 | 1 | Muy suavizado |

Reglas de seguridad:

- la ventana aplicada se corrige a impar;
- minimo efectivo de 3 puntos cuando hay suficientes muestras;
- si hay pocos puntos, la ventana se reduce;
- si `polyorder >= window_length`, el orden se reduce automaticamente con advertencia.

El CSV conserva:

- `pk`;
- `distancia_m`;
- `x`;
- `y`;
- `cota_bruta_m`;
- `cota_suavizada_m`;
- `pendiente_bruta_pct`;
- `pendiente_representada_pct`;
- `pendiente_perfil_pct`;
- `pendiente_anomala`;
- `umbral_pendiente_anomala_pct`.

## Filtro de pendientes anomalas

El filtro de anomalias se aplica despues del muestreo y del suavizado. No modifica la geometria, los PK ni las cotas.

Funcionamiento:

- se calcula `pendiente_bruta_pct`;
- si `abs(pendiente_bruta_pct) <= umbral`, se conserva como `pendiente_representada_pct`;
- si `abs(pendiente_bruta_pct) > umbral`, se marca `pendiente_anomala = true`;
- en ese caso, `pendiente_representada_pct = signo * umbral`.

El dato bruto siempre se conserva en CSV y en los segmentos GeoJSON/GPKG. La representacion usa la pendiente filtrada para que un pico aislado no destruya la escala del perfil ni la lectura del mapa.

En mapas y perfil, las anomalias se pintan en amarillo intenso `#ffff00`. No se anade a la leyenda de pendientes para mantenerla limpia; el resumen de resultados indica cuantas lecturas o segmentos se han aplanado.

Muestreo, suavizado y anomalias son tres pasos distintos:

- muestreo: decide cada cuantos metros se consulta la cota;
- suavizado: reduce ruido en la serie de cotas;
- filtro de anomalias: limita solo la pendiente representada cuando supera el umbral.

## Origen del eje Y de elevacion

El perfil permite dos modos:

- `Origen en 0 m`: el eje de cota empieza en cero y nunca muestra cotas negativas.
- `Origen adaptado`: el eje se ajusta al rango altitudinal del tramo, con un intervalo de tick bonito por debajo de la cota minima y otro margen superior.

Metadatos guardados:

- `modo_eje_y`;
- `y_min_visual`;
- `y_tick_min`;
- `y_max`;
- `y_tick_step`.

## Segmento pendiente

Controla la longitud de los segmentos usados para simbolizar la pendiente media en el mapa de pendientes.

No cambia el perfil muestreado. Solo afecta a la cartografia de pendientes y a los datos auxiliares exportados como GeoJSON/GPKG.

Si se deja en `auto`, la longitud se adapta a la longitud total del tramo.

## Transparencias de elevacion

`Alpha localizacion` y `Alpha pendientes` solo afectan a la visualizacion de las elevaciones discretas sobre Positron.

- Valores bajos: base Positron mas visible.
- Valores altos: relieve/elevaciones mas dominantes.

No afectan al perfil ni al calculo de pendientes.

## Parametros v2.0

### Vias de fondo

Controla solo las carreteras de contexto que se dibujan bajo el tramo de estudio:

- `Todas las carreteras`: pinta toda la red dentro del encuadre.
- `Solo autovias`: pinta autovias/autopistas y mantiene siempre la via del ambito.
- `Solo la via del ambito`: pinta como contexto solo la carretera introducida.
- `Ninguna`: oculta la red de fondo; el tramo y los segmentos de pendiente se siguen dibujando.

El valor se guarda como `vias_fondo_modo` en metadatos.

### Sentido Ambos

El sentido `Ambos` genera dos juegos independientes de resultados:

- sentido creciente;
- sentido decreciente.

No se mezclan ambos sentidos en un mismo perfil. Si un sentido no existe o falla, la herramienta intenta generar el otro y registra advertencia no fatal.

### Elevaciones y curvas de nivel en mapas

Los mapas PIL v2.0 incorporan una capa de elevaciones a partir del MDT WCS/cache:

- clases discretas de elevacion, maximo 6;
- intervalos redondos adaptados al rango altitudinal real del mapa principal;
- alpha mas bajo en localizacion y mas alto en pendientes;
- Positron queda visible bajo la capa de elevacion.

Desde el ajuste fino v2_3, las clases de elevacion no arrancan automaticamente en 0. La herramienta calcula estadisticas sobre el raster ya recortado/reproyectado al `MAP_MAIN` y elige saltos bonitos entre:

- `10 m`;
- `20 m`;
- `50 m`;
- `100 m`;
- `200 m`;
- `500 m`.

El objetivo es obtener entre 4 y 6 clases cuando el rango lo permite, con maximo 6. El inicio y final de la leyenda son multiplos del intervalo elegido. Ejemplos:

- rango `1030-2460 m`: `1000-1500`, `1500-2000`, `2000-2500 m`;
- rango `1120-1780 m`: `1000-1200`, `1200-1400`, `1400-1600`, `1600-1800 m`;
- rango `0-180 m`: puede arrancar en `0 m`, porque la cota baja forma parte del ambito.

Si aparecen unos pocos ceros aislados en una zona claramente alta, se pueden ignorar solo para la clasificacion visual. Esto no modifica el raster, el perfil, los datos exportados ni las pendientes. La regla aplicada es conservadora: si `zmin <= 0`, `p05 > 100 m` y el porcentaje de pixeles cero es menor que `2 %`, la clasificacion usa percentiles bajos (`p02`/`p05`) en lugar del cero bruto. En zonas costeras o bajas, los ceros se conservan.

Las curvas de nivel se extraen del raster y se dibujan con PIL sobre el canvas final:

- curvas intermedias mas suaves;
- curvas maestras algo mas visibles;
- etiquetas discretas en algunas curvas maestras.

Las curvas maestras coinciden con los limites de clase de elevacion. Las curvas intermedias se colocan a mitad del intervalo principal: si las clases son cada `200 m`, las curvas intermedias van cada `100 m`; si las clases son cada `500 m`, las intermedias van cada `250 m`.

Si el MDT no esta disponible o no intersecta el mapa, se genera el mapa sin elevaciones/curvas y se registra advertencia.

### Configuracion de PKs

Los simbolos de PK y las etiquetas son capas distintas.

Modo automático usa una densidad adaptada a la longitud del ámbito:

- longitud <= 10 km: simbolos cada 1 km, etiquetas cada 1 km;
- longitud <= 30 km: simbolos cada 1 km, etiquetas cada 5 km;
- longitud <= 80 km: simbolos cada 5 km, etiquetas cada 10 km;
- longitud <= 150 km: simbolos cada 10 km, etiquetas cada 25 km;
- longitud <= 300 km: simbolos cada 25 km, etiquetas cada 50 km;
- longitud > 300 km: simbolos cada 50 km, etiquetas cada 100 km.

Modo manual usa deslizantes con valores discretos `1`, `5`, `10`, `25`, `50`, `100` y `250 km`. No se aceptan valores intermedios. Si la etiqueta queda mas densa que el simbolo, se corrige al intervalo del simbolo.

Modo `No mostrar PKs` oculta simbolos y etiquetas.

### Anomalias en perfil y mapa

El amarillo de anomalías no elimina el dato bruto:

- en mapas se mantiene amarillo intenso `#ffff00`;
- en perfiles v2.0 se usa `#c2b206`, mas legible sobre fondo claro;
- el CSV conserva `pendiente_bruta_pct` y `pendiente_representada_pct`.

Muestreo, suavizado y filtro de anomalias siguen siendo pasos independientes.

## Parametros v2_3

### Suavizado simple

El modo simple mantiene el control `0-10`.

- `0`: no suaviza.
- `4`: valor recomendado por defecto.
- `10`: suavizado alto.

La ayuda de interfaz muestra la ventana equivalente y el polinomio usado por la tabla interna.

### Suavizado Savitzky-Golay avanzado

Si se activa `Suavizado Savitzky-Golay avanzado`, el slider simple queda desactivado y se usan dos controles:

- `Ventana Savitzky-Golay`: numero impar de puntos, de `3` a `55`.
- `Valor polinomico`: `1` a `4`. En v2_3 la orientacion visual se invierte: izquierda `Polinomio 4`, derecha `Polinomio 1`.

Regla obligatoria:

- `polyorder < window_length`.

Si el usuario elige una combinacion incompatible, el backend reduce automaticamente el polinomio y registra advertencia.

En la interfaz este modo aparece como una opcion discreta dentro de la subseccion `Suavizado avanzado`, sin recuadro independiente. Cuando no esta activo, el slider simple `Suavizado` queda habilitado y los controles avanzados quedan desactivados.

Metadatos guardados:

- `suavizado_modo`;
- `suavizado_slider`;
- `sg_window_puntos_teorica`;
- `sg_window_puntos_aplicada`;
- `sg_window_metros_aprox`;
- `sg_polyorder`.
- `sg_polyorder_slider_visual`.

El umbral de pendiente anomala acepta pasos de `0,5 %` y se guarda como `float`.

### Perfiles con y sin pendiente

Cuando se marca `Perfiles longitudinales`, se exportan dos versiones:

- perfil con pendiente, con eje secundario y curva continua de pendiente;
- perfil sin pendiente, solo con elevacion y relleno.

La linea de pendiente es continua. La leyenda usa una muestra continua gris para `Pendientes (%)`.

En el perfil con pendiente, el subtitulo incluye `pendiente media abs.`. Se calcula con `pendiente_representada_pct`, es decir, despues de aplicar el umbral de pendientes anomalas. En metadatos se conservan:

- `pendiente_media_pct`;
- `pendiente_media_representada_pct`;
- `pendiente_media_abs_pct`;
- `pendiente_media_bruta_pct`;
- `criterio_calculo_pendiente_media`.

### Pendientes aplanadas

Las lecturas anomalas contiguas se agrupan por rangos de PK. En resultados y metadatos se guarda:

- `pk_inicio`;
- `pk_fin`;
- `n_puntos_muestreo`;
- `n_segmentos_mapa`.

El dato bruto no se borra: se conserva en `pendiente_bruta_pct`; la representacion usa `pendiente_representada_pct`.

### Salidas

En v2_3 `Datos auxiliares` queda desmarcado por defecto. Si se marca, se exportan CSV, GeoJSON/GPKG, metadatos y log en `datos_auxiliares.zip`.

### Diagnostico de elevaciones

Los mapas guardan metadatos de diagnostico para la capa MDT/WCS:

- existencia del raster;
- CRS, bounds, ancho, alto, nodata;
- min/max bruto, percentiles `p02`, `p05`, `p95`, `p98`;
- numero y porcentaje de pixeles cero;
- min/max usados para clasificacion visual;
- clases de elevacion;
- intervalo, inicio, fin y numero de clases;
- si se han ignorado ceros espurios solo para clasificacion visual;
- niveles de curvas maestras e intermedias;
- motivo de no renderizado;
- orden de composicion.

El detalle metodologico esta en `docs/diagnostico_elevaciones_wcs_v2_1.md`.

En v2_3, el raster MDT se reproyecta al encuadre exacto del mapa principal:

- CRS destino `EPSG:3857`;
- ancho/alto iguales a `MAP_MAIN`;
- bounds derivados del encuadre lon/lat ya ajustado por el compositor;
- `rasterio.warp.reproject` con resampling `bilinear`;
- composicion directa en el origen de `MAP_MAIN`.

Las curvas de nivel se extraen del raster ya reproyectado. Sus coordenadas de array se convierten directamente a pixeles de `MAP_MAIN`, por lo que comparten alineacion con el overlay de elevaciones.

El muestreo altimetrico del perfil comprueba CRS del tramo y CRS del raster. Si no coinciden, transforma los puntos de muestreo al CRS del raster antes de llamar a `src.sample()`. Los metadatos guardan CRS de tramo, CRS de raster, si hubo transformacion, numero de puntos y numero de cotas validas.

## Altimetria y WCS v2_2

La version `v2_2` muestra en resultados la fuente altimetrica realmente usada. Los valores posibles son:

- `MDT/WCS`: se ha descargado o leido un GeoTIFF MDT valido.
- `Cotas de PK`: el MDT no estaba disponible y se han interpolado cotas de la capa de PKs.
- `Sin cota real / perfil provisional`: no hubo MDT ni cotas PK suficientes.

Metadatos normalizados:

- `altimetria.fuente_altimetrica_usada`;
- `altimetria.resolucion_mdt_solicitada`;
- `altimetria.resolucion_mdt_usada`;
- `altimetria.coverage_mdt_usada`;
- `altimetria.mdt_disponible`;
- `altimetria.fallback_altimetrico_aplicado`;
- `altimetria.fallback_altimetrico_tipo`.

La descarga WCS usa WCS `1.0.0` con correspondencia fija entre resolución y cobertura:

- `5 m` → `COVERAGE=Elevacion4258_5`;
- `25 m` → `COVERAGE=Elevacion4258_25`;
- `FORMAT=GEOTIFFINT16`;
- `CRS=EPSG:25830`;
- `RESPONSE_CRS=EPSG:25830`.

Antes de descargar, se calcula `ancho × alto` para cada resolución. Si `5 m` supera `mdt.max_pixeles` (por defecto, `4 000 000`) y `25 m` cabe, se degrada a `25 m`; la advertencia y los metadatos registran la decisión. No se mezclan coberturas de distinta resolución en una misma tentativa. Si una descarga completa no es válida, la herramienta intenta descarga teselada. Ninguna respuesta se guarda como caché válida si no pasa la validación TIFF/rasterio.

### Notas de calculo inspeccionadas en v2_1

- La unica operacion de suavizado de la cota es Savitzky-Golay en `src/perfiles.py`. Antes se rellenan huecos `NaN` por interpolacion lineal para poder aplicar el filtro, pero no hay rolling mean, spline ni suavizado visual adicional de la curva.
- Desde v2_4, la pendiente bruta del perfil se calcula con la derivada numerica de la cota suavizada, despues se suaviza como serie independiente y finalmente se limita para representacion si supera el umbral de pendiente anomala.
- `Segmento pendiente (m)` no afecta al perfil longitudinal. Solo controla la longitud de los segmentos cartograficos del mapa de pendientes y de los GeoJSON/GPKG auxiliares.

## Ajustes v2_3 posteriores

### Anotaciones de curvas de nivel

`Mostrar anotaciones de lineas de nivel` controla solo las etiquetas de cota de las curvas maestras. Si esta desmarcado, las curvas siguen dibujandose, pero no se pintan textos como `200 m`. Se guarda en metadatos:

- `mostrar_anotaciones_curvas_nivel`;
- `n_etiquetas_curvas`.

En el ajuste fino v2_3, las etiquetas de curvas se integran en la linea:

- sin halo;
- rotadas segun la tangente local;
- con angulo normalizado para evitar texto boca abajo;
- con hueco visual bajo la etiqueta, implementado de forma aproximada por omision de puntos alrededor del indice de etiqueta;
- con comprobacion simple de solape entre cajas de etiquetas.

Metadatos asociados:

- `curvas_etiquetas_sin_halo`;
- `curvas_etiquetas_rotadas`;
- `curvas_etiquetas_siguen_tangente`;
- `curvas_etiquetas_hueco_linea`;
- `curvas_etiquetas_font_size`;
- `curvas_etiquetas_colisiones`.

### Transparencia de elevaciones

Los controles de transparencia de elevaciones muestran el valor elegido en porcentaje. La interfaz convierte el valor visible a alpha `0-1` para el backend, por ejemplo `34 %` se envia como `0.34`.

## Suavizado independiente v2_4

Desde `v2_4`, la herramienta separa dos suavizados distintos:

- `Suavizado de elevaciones`: suaviza `cota_bruta_m` para obtener `cota_suavizada_m`.
- `Suavizado de pendientes`: suaviza `pendiente_bruta_pct` para obtener `pendiente_suavizada_pct`.

Ambos pueden usarse en modo simple `0-10` o en modo avanzado Savitzky-Golay. Los metadatos se guardan en `perfil.suavizado_elevaciones` y `perfil.suavizado_pendientes`.

Pipeline aplicado:

1. Muestreo de cotas sobre la via: `cota_bruta_m`.
2. Relleno interno de huecos `NaN` para poder aplicar Savitzky-Golay.
3. Suavizado de elevaciones: `cota_suavizada_m`.
4. Derivada numerica de `cota_suavizada_m`: `pendiente_bruta_pct`.
5. Suavizado de pendientes: `pendiente_suavizada_pct`.
6. Aplanamiento por umbral de anomalia sobre `pendiente_suavizada_pct`.
7. Resultado de representacion: `pendiente_representada_pct`.

El perfil con pendiente y el mapa de pendientes usan `pendiente_representada_pct`. El perfil sin pendiente solo usa las cotas y no depende del suavizado de pendientes.

El CSV de perfil incluye `pendiente_suavizada_pct`. `pendiente_perfil_pct` se mantiene como alias de `pendiente_representada_pct`.

`Segmento pendiente (m)` sigue definiendo la longitud de los segmentos cartograficos. Desde `v2_4`, cada segmento calcula su clase y color con la media de `pendiente_representada_pct` dentro del segmento, no con la diferencia directa de cotas entre extremos. La pendiente por extremos de cota se conserva como `pendiente_cota_segmento_pct` solo para trazabilidad.

### Eje Y del perfil

El eje de elevacion usa la estrategia `nice_steps_max_7_ticks`: pasos bonitos `10`, `20`, `25`, `50`, `100`, `200`, `250`, `500` y `1000 m`, con objetivo de 5-7 etiquetas principales y maximo 8. En modo adaptado el eje empieza y termina en multiplos del paso elegido; en modo origen 0 no se muestran etiquetas negativas aunque pueda existir un margen visual inferior. Metadatos:

- `y_tick_count`;
- `y_tick_step`;
- `y_tick_min`;
- `y_tick_max`;
- `y_axis_strategy`.

### Pendientes aplanadas

Cada rango anomalo incluye tambien:

- `pendiente_bruta_max_abs_pct`;
- `pendiente_bruta_max_pct`;
- `pk_pendiente_bruta_max`.

Estos valores se calculan con `pendiente_bruta_pct`; la representacion sigue usando `pendiente_representada_pct`.

### Parametros empleados en resultados

La interfaz principal muestra solo: suavizado, muestreo altimetrico, segmento pendiente, umbral de anomalia, fuente altimetrica usada, resolucion MDT solicitada, resolucion MDT usada, estado MDT y fallback aplicado. La cobertura, CRS, tiles, rutas y otros detalles quedan en `metadatos.json`.
