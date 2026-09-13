# Version v2_1

Fecha: 2026-07-06

## Cambios principales

- Version visible actualizada a `v2_1`.
- La linea de pendiente en perfiles pasa a ser continua.
- Se generan dos perfiles por sentido:
  - `perfil_longitudinal_[via]_[sentido]_con_pendiente`;
  - `perfil_longitudinal_[via]_[sentido]_sin_pendiente`.
- Se elimina de la interfaz el checkbox `Mostrar linea de pendiente`.
- Se reorganiza la barra lateral en:
  - Ambito;
  - Configuracion de entrada;
  - Configuracion de salida;
  - Salidas.
- `Datos auxiliares` queda desmarcado por defecto.
- Se añade modo avanzado de suavizado Savitzky-Golay:
  - ventana impar de 3 a 23 puntos;
  - polinomio 1 a 4;
  - metadatos de modo, ventana y polinomio.
- Ajuste adicional: el modo avanzado queda integrado como checkbox discreto en la subseccion `Suavizado avanzado`, sin recuadro propio. Cuando esta desmarcado, los controles avanzados quedan desactivados.
- Los deslizantes manuales de PK aceptan solo `1`, `5`, `10`, `25`, `50`, `100` y `250 km`; la etiqueta nunca puede ser mas densa que el simbolo.
- El perfil con pendiente muestra `pendiente media abs.` en el subtitulo y el resumen del tramo incorpora `Pendiente media absoluta`.
- Se mejora el ranking del autocompletado para priorizar prefijos reales de carretera.
- Se mejora el resumen de pendientes aplanadas con rangos PK a PK, puntos de muestreo y segmentos de mapa.
- Se ajustan leyendas de mapas:
  - mas aire tras encabezados;
  - bloque de leyenda algo mas cerca del subtitulo;
  - sin categoria amarilla de anomalia;
  - clases extremas sin simbolos `<` ni `>`.
- Se crea `docs/diagnostico_elevaciones_wcs_v2_1.md`.

## Limitaciones conocidas

- El diagnostico de elevaciones queda instrumentado, pero no se rediseña el WCS ni la reproyeccion raster en esta iteracion.
- La leyenda de pendiente del perfil usa una muestra gris continua como fallback, no un gradiente multicolor.
- La QA funcional en navegador requiere reiniciar el servidor para que cargue el backend v2_1.

## QA

Automatica:

```powershell
..\.venv\Scripts\python.exe -m compileall src app.py
..\.venv\Scripts\python.exe -m unittest discover -s tests
```

Manual pendiente/recomendada:

- Confirmar estructura de interfaz.
- Probar `V-3` y comprobar que `V-30` aparece antes que `AV-3001`.
- Probar suavizado simple y avanzado.
- Generar perfiles y comprobar con/sin pendiente.
- Revisar `metadatos.json` de mapas para elevaciones MDT/WCS.
- Confirmar ZIPs.

## Confirmacion

Esta versión documenta exclusivamente cambios de la herramienta.
