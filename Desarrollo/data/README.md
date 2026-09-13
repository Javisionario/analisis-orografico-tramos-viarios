# Datos locales requeridos

La herramienta necesita dos conjuntos de datos geográficos locales para funcionar. Estos datos **no se incluyen en el repositorio Git**.

## Archivos esperados

Este directorio debe contener:

- `CalibradaBase.gpkg`
- `LimitesAdministrativos.gpkg`

Las rutas y nombres anteriores son los utilizados por la configuración actual del proyecto.

## 1. Red viaria calibrada

`CalibradaBase.gpkg` contiene la red viaria calibrada utilizada por la herramienta para trabajar con carreteras y puntos kilométricos.

El repositorio no distribuye este archivo.

Como fuente pública de referencia puede utilizarse la **Red de Carreteras del Estado (RCE) calibrada** publicada por el Ministerio de Transportes y Movilidad Sostenible:

- [Archivos y geometrías de la RCE](https://www.transportes.gob.es/carreteras/catalogo-y-evolucion-de-la-red-de-carreteras/archivos-geometrias-rce)
- [Descarga de la RCE 2025 calibrada (Shapefile)](https://cdn.transportes.gob.es/portal-web-transportes/carreteras/red_carreteras/rce/260306-redrce2025_calibrada.zip)

La fuente pública puede requerir **conversión a GeoPackage y adaptación de su estructura, capas o campos** para ajustarse al esquema que espera esta herramienta.

## 2. Límites administrativos

`LimitesAdministrativos.gpkg` contiene la cartografía administrativa utilizada por la herramienta, al menos con información de:

- provincias;
- comunidades autónomas.

Puede generarse a partir de cartografía administrativa pública, por ejemplo del Instituto Geográfico Nacional (IGN), siempre que se prepare con la estructura que espera la aplicación.

## Por qué no se versionan

Estos archivos se mantienen fuera de Git porque:

- son ficheros geográficos relativamente pesados;
- la cartografía de límites administrativos puede obtenerse de fuentes públicas oficiales y no es necesario duplicarla en el repositorio;
- la herramienta está preparada para trabajar con datos locales proporcionados por cada instalación;
- el repositorio debe contener el código y la configuración necesarios para reproducir la herramienta, no necesariamente las fuentes geográficas originales.

## Preparación de una instalación nueva

Después de clonar el repositorio:

1. coloque los dos archivos en este directorio;
2. compruebe que conservan exactamente estos nombres:

   ```text
   CalibradaBase.gpkg
   LimitesAdministrativos.gpkg
   ```

3. ejecute `iniciar_analisis_orografico_tramos_viarios.bat` desde la raíz del proyecto.

Si se utilizan fuentes públicas alternativas, puede ser necesario adaptar previamente su formato o esquema antes de que la herramienta pueda consumirlas.
