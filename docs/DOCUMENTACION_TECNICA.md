# Documentación técnica

Esta documentación reúne la información técnica de **Orografía y Localización de Tramos Viarios v3.1.1**. El README principal explica el uso habitual; este documento conserva el detalle sobre parámetros, metodología, salidas y composición.

## 1. Arquitectura general

La aplicación es una herramienta web local basada en FastAPI.

Estructura principal:

```text
Desarrollo/
├── app/
│   ├── app.py
│   ├── src/
│   ├── static/
│   └── templates/
├── config/
├── data/
├── docs/
├── qa/
├── scripts/
├── tests/
└── requirements.txt
```

Los resultados se escriben fuera del árbol de desarrollo, en `Resultados/`.

## 2. Arranque

Arranque recomendado:

```text
iniciar_analisis_orografico_tramos_viarios.bat
```

El BAT usa un entorno virtual local `.venv`.

Para evitar reinstalar dependencias en cada arranque, calcula el SHA-256 de `Desarrollo/requirements.txt` y lo compara con:

```text
.venv/.requirements.sha256
```

Solo ejecuta `pip install -r` cuando:

- se crea el entorno por primera vez;
- el marcador no existe;
- cambia el contenido de `requirements.txt`.

El marcador se actualiza únicamente tras una instalación correcta.

Arranque manual:

```powershell
.\.venv\Scripts\python.exe .\Desarrollo\app\app.py
```

URL local habitual:

```text
http://127.0.0.1:8025/
```

El servidor se limita a loopback por defecto. Para usar un host remoto debe
activarse explícitamente `app.allow_remote`; no se ofrece autenticación multiusuario.

## 3. Configuración

Archivo principal:

```text
Desarrollo/config/config.yaml
```

### Rutas de datos

Parámetros principales:

- `datos.viario_gpkg`: GeoPackage de la red viaria.
- `datos.capa_lineas`: capa lineal calibrada.
- `datos.capa_pks`: capa de puntos kilométricos.
- `datos.limites_gpkg`: límites administrativos.
- `datos.capa_ccaa`: capa de comunidades autónomas.
- `datos.capa_provincias`: capa de provincias.

### Campos

La configuración admite listas de nombres alternativos para varios campos, entre ellos:

- carretera;
- sentido;
- M inicial y final;
- PK puntual;
- etiqueta de PK;
- cota;
- tipo de vía.

Esto permite adaptar la herramienta a esquemas de datos distintos sin modificar directamente el código.

## Referenciación lineal y perfiles

La fuente preferente de PK es la coordenada M original de `LineStringM`. Cuando
el lector GIS no la conserva, se recupera desde WKB/FID del GeoPackage; si no es
posible, el fallback por límites de fila queda marcado explícitamente. El eje X
del perfil es siempre distancia geométrica física, mientras que el PK procede de
M. Por ello el soporte completo requiere un GeoPackage calibrado. Las rutas
paralelas se resuelven como una única cadena continua; una discontinuidad física
se rechaza antes de calcular perfiles o pendientes.

La canalización single y multi sigue separada por seguridad de regresión; su
unificación por scope queda como deuda técnica posterior.

### CRS

Configuración actual de referencia:

- trabajo: `EPSG:25830`;
- Canarias: `EPSG:4083`;
- geográfico: `EPSG:4326`.

## 4. Modelo digital del terreno

La herramienta obtiene preferentemente la altimetría mediante WCS.

Servicio configurado:

```text
https://servicios.idee.es/wcs-inspire/mdt?VERSION=1.0.0
```

Resoluciones preferidas:

```text
5 m
25 m
```

La lógica prioriza 5 m y puede utilizar 25 m como fallback si la descarga o cobertura de 5 m falla.

La petición WCS está orientada al flujo usado por la herramienta y trabaja con el CRS de trabajo configurado.

Si el MDT no puede utilizarse, la herramienta puede recurrir a cotas disponibles en la capa de PKs cuando el esquema de datos lo permite.

### Advertencia

El MDT representa la superficie del terreno. Puede no reproducir correctamente la rasante de:

- túneles;
- viaductos;
- pasos superiores;
- estructuras elevadas;
- otras situaciones en las que la carretera no coincide con la superficie topográfica.

## 5. Muestreo y perfil longitudinal

### Intervalo de muestreo altimétrico

Define la distancia entre puntos sucesivos donde se consulta la elevación sobre el tramo.

Valor por defecto:

```text
75 m
```

La recomendación general es no utilizar un intervalo inferior a aproximadamente cuatro veces el tamaño de píxel del MDT.

### Suavizado de elevaciones

Se aplica sobre la serie de cotas antes de calcular la pendiente.

La interfaz ofrece un control simple `0-10` y una configuración avanzada mediante Savitzky-Golay.

Desde v3.1.1, el botón **? Ayuda** de la cabecera abre un manual breve de uso. Resume el flujo de cálculo, la diferencia entre resolución del MDT e intervalo de muestreo y el papel de los dos suavizados; no sustituye a esta documentación técnica.

### Cálculo de pendiente

La pendiente bruta se obtiene a partir de la derivada de la serie de elevaciones suavizada.

Después puede aplicarse un segundo suavizado específico para la pendiente.

La secuencia conceptual es:

```text
MDT
→ muestreo de cotas
→ suavizado de elevaciones
→ cálculo de pendiente
→ suavizado de pendientes
→ control de anomalías
→ pendiente representada
```

## 6. Pendientes anómalas

Existe un umbral de pendiente anómala configurable.

Valor de referencia:

```text
20 %
```

La herramienta conserva el dato original para trazabilidad, pero puede limitar o aplanar la representación gráfica cuando se supera el umbral configurado.

Se distinguen:

- `pendiente_bruta_pct`;
- `pendiente_suavizada_pct`;
- `pendiente_representada_pct`.

La anomalía se determina cuando `abs(pendiente_suavizada_pct) > umbral`; en ese caso `pendiente_anomala = true` y la representación pasa a `0 %`.

El resumen puede agrupar rangos contiguos afectados e informar de los PK asociados.

## 7. Parámetros de interfaz

Entre los controles disponibles se encuentran:

### Resolución MDT
Permite seleccionar la resolución altimétrica solicitada.

### Intervalo de muestreo
Controla la densidad de puntos usados para construir el perfil.

### Suavizado de elevaciones
Reduce ruido en la serie de cotas.

### Suavizado de pendientes
Reduce ruido en la derivada sin modificar la cota base.

### Savitzky-Golay avanzado
Permite configurar ventana y orden polinómico de forma separada para elevaciones y pendientes.

### Segmento pendiente
Define la longitud sobre la que se agrega o simboliza la pendiente media en el mapa.

### Umbral de pendiente anómala
Controla cuándo una pendiente se considera fuera del rango razonable para la representación.

### Origen del eje de elevación
Puede partir de `0 m` o adaptarse al rango real del perfil.

### Línea muestreada
Permite mostrar la serie de cota muestreada junto al perfil procesado.

### Curvas de nivel
Las curvas pueden mantenerse visibles ocultando únicamente sus anotaciones.

### Vías de fondo
Opciones disponibles:

- todas;
- solo autovías;
- solo vía del ámbito;
- ninguna.

### PKs
Modos:

- automático;
- manual;
- no mostrar.

En manual se pueden definir intervalos de símbolo y etiqueta.

### Sentido
Opciones:

- creciente;
- decreciente;
- ambos.

Con `Ambos` se generan salidas separadas por sentido.

## 8. Mapas base

### IGN gris

Proveedor predeterminado.

El mapa principal y el mapa de localización solicitan primero el WMS de IGN:

```text
IGNBaseTodo-gris
```

Si el WMS falla, usan como fallback el TMS de IGN:

```text
https://tms-ign-base.idee.es/1.0.0/IGNBaseGris/{z}/{x}/{y}.jpeg
```

La herramienta adapta internamente el eje Y al esquema TMS solo cuando usa ese fallback.

No requiere API key.

### CARTO Positron

Proveedor opcional.

Utiliza el endpoint raster de Positron y requiere una API key de CARTO.

La clave:

- se introduce desde la interfaz;
- puede almacenarse en el Administrador de credenciales de Windows mediante `keyring`;
- no se guarda en YAML;
- no se guarda en caché;
- no se escribe en logs;
- no se incluye en metadatos ni resultados;
- no se versiona en Git.

Los mensajes de error asociados a teselas se saneaban para eliminar query strings sensibles.

## 9. Composición cartográfica

Los mapas se generan mediante un compositor PIL propio.

Características de referencia:

- `4015 × 2834 px`;
- RGB;
- `600 dpi`;
- tamaño conceptual `17 × 12 cm`.

La composición integra:

- mapa base;
- carretera;
- tramo seleccionado;
- PKs;
- elevaciones;
- curvas de nivel;
- mapa de situación;
- leyendas y escala.

Cuando el mapa de localización usa el fallback TMS, aplica un offset de zoom específico para obtener una cartografía más generalizada:

```text
LOCATION_TILE_ZOOM_OFFSET = -1
```

## 10. Elevaciones y curvas de nivel

El MDT utilizado en la composición se reproyecta a la rejilla del mapa antes de generar las clases de elevación y las curvas de nivel.

Las clases de elevación se adaptan al rango real de cada mapa.

Los saltos de clase permitidos son:

```text
10, 20, 50, 100, 200 y 500 m
```

Las curvas principales coinciden con estos límites y las curvas intermedias se sitúan entre clases.

## 11. Salidas

Cada generación crea una carpeta con estructura similar a:

```text
Resultados/CARRETERA_PKINI-PKFIN_SENTIDO_YYYYMMDD_HHMMSS/
```

Puede contener:

```text
mapa_localizacion_[via].png/pdf
mapa_pendientes_[via].png/pdf
perfil_longitudinal_[via]_[sentido]_con_pendiente.png/pdf/svg
perfil_longitudinal_[via]_[sentido]_sin_pendiente.png/pdf/svg
datos_auxiliares_[via].csv
datos_auxiliares_[via].geojson/gpkg
tramo_estudio_[via].geojson/gpkg
metadatos.json
log.txt
mapas.zip
perfiles.zip
datos_auxiliares.zip
```

Los datos auxiliares son opcionales desde la interfaz.

Los ZIP aparecen como descargas agrupadas:

- mapas;
- perfiles;
- datos auxiliares.

## 12. Parámetros empleados y metadatos

La interfaz muestra un resumen reducido de los parámetros relevantes para interpretar la generación:

- suavizado de elevaciones;
- suavizado de pendientes;
- muestreo;
- segmento de pendiente;
- umbral de anomalía;
- fuente altimétrica;
- resolución MDT solicitada y usada;
- estado del MDT.

La información interna más detallada queda en `metadatos.json`.

La API key de CARTO se excluye explícitamente de los parámetros persistentes.

## 13. Caché

La herramienta usa cachés locales para reducir descargas repetidas, especialmente de:

- MDT;
- teselas de mapa base.

Las cachés están fuera de Git y son regenerables.

## 14. Resultados de carretera y PK

La aplicación:

- lista las carreteras disponibles;
- valida que la vía exista;
- calcula el rango PK real por sentido;
- ajusta valores fuera de rango al PK disponible más cercano;
- informa al usuario cuando se produce ese ajuste.

La búsqueda de carreteras normaliza diferencias de mayúsculas, espacios y guiones.

## 15. Pruebas

Comprobaciones habituales:

```powershell
.\.venv\Scripts\python.exe -m compileall Desarrollo\app
.\.venv\Scripts\python.exe -m unittest discover -s Desarrollo\tests
```

La composición de mapas dispone además de scripts de QA específicos en `Desarrollo/qa/`.

## 16. Problemas frecuentes

### Dependencias Python
Si faltan `fastapi`, `uvicorn` u otras librerías, ejecutar el BAT o instalar `Desarrollo/requirements.txt`.

### GDAL / Fiona / Rasterio
En instalaciones Windows problemáticas puede ser más sencillo utilizar paquetes de `conda-forge`.

### WCS
Si el MDT de 5 m falla, la herramienta puede intentar la resolución de 25 m y registrar el fallback.

### CARTO
Si Positron no dispone de una API key válida, la aplicación bloquea la generación cartográfica con ese proveedor.

### Medidas M / PK
Si la geometría no conserva M, la herramienta puede recurrir a campos explícitos de PK/M cuando el esquema lo permite.

## 17. Datos locales

Los GeoPackage requeridos no se incluyen en Git.

Consultar:

```text
Desarrollo/data/README.md
```

para información sobre:

- `CalibradaBase.gpkg`;
- `LimitesAdministrativos.gpkg`;
- fuentes públicas de referencia;
- adaptación de capas y campos.

## 18. Historial técnico

La documentación histórica de iteraciones anteriores permanece en:

```text
Desarrollo/docs/
```

Los documentos `version_v2_*.md` forman parte del historial de desarrollo y no representan la numeración pública actual.

La versión pública actual es:

```text
v3.1.1
```
