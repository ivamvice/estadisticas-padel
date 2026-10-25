# Estadísticas Pádel

Web de estadísticas de la Liga Pádel Madrid: ranking de jugadores, resultados de Liga y Copa por equipo y convocatoria del club.
Fuente de los datos: ligapadelmadrid.com.

## Cómo funciona

- `index.html`: la web. Lee los datos de la carpeta `data/`.
- `manifest.webmanifest` e `icons/`: permiten instalarla en el móvil con el icono de la pelota.
- `data/ranking/`: fotos guardadas del ranking Masculino (`M/`) y Femenino (`F/`) e índice (`index.json`).
- `data/partidos.json`: resultados de los encuentros de Liga y Copa.
- `scripts/`: programas que leen la web de la liga y actualizan `data/`.

## Actualización automática (pestaña Actions)

- **Actualizar ranking**: cada día. Guarda una foto nueva solo si cambian los puntos de los jugadores del club.
- **Actualizar resultados**: cada día. Tarda unos 45-60 minutos.
- **Publicar web**: publica la web en GitHub Pages. Se lanza sola tras cada actualización o al subir cambios.

Cualquiera de ellos se puede lanzar a mano desde Actions → el flujo → *Run workflow*.
