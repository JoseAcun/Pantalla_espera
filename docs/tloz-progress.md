# TLOZ V1: progreso del directo

Esta capa añade seguimiento editorial de **Juego → Zonas → Objetivos** sin sustituir STREAM_OS RPG, analítica, Pokémon ni la integración Twitch ya existente.

## Componentes reutilizados

- **Twitch/Helix y EventSub:** `StreamState` ya contiene `category_id`, `category`, `twitch_stream_id`, estado del directo y audiencia. TLOZ usa solamente `category_id` para identificar el juego actual; no hay un selector manual de juego en tiempo de directo.
- **FastAPI y panel local:** rutas en `app/main.py`, autenticadas con el mismo `X-Overlay-Admin-Token`, y una página estática nueva en `/admin/tloz`.
- **MariaDB Docker existente:** `DATABASE_URL` y la red `stream-data`; no se introduce SQLite, volumen ni contenedor adicional.
- **WebSocket/Browser Sources:** el mensaje `tloz.state` se entrega al conectar, tras guardar desde el panel y en el refresco periódico de Twitch. Los overlays además hacen una consulta prudente cada minuto como respaldo.
- **BRB existente:** `/overlay/brb` incorpora un módulo rotativo `PREVIOUSLY IN ZELDA` que solo aparece mientras la categoría Twitch esté vinculada a un juego TLOZ.

## Modelo persistido

La migración `db/009_tloz_progress.sql` crea exclusivamente estas tablas. La
migración aditiva `db/010_tloz_catalog_slugs.sql` añade slugs estables para el
catálogo y conserva íntegras las filas manuales existentes.

- `tloz_games`: catálogo, relación única opcional `twitch_category_id`, era/rama, orden de cronología y layout.
- `tloz_zones`: zonas ordenadas de un juego, con slug estable para importación.
- `tloz_objectives`: objetivos ordenados de una zona, con slug y etiqueta `required` u `optional`.
- `tloz_playthroughs`: consola, zona, objetivo y estado especial actuales. Guarda el `twitch_stream_id` automáticamente cuando Twitch lo tenga.
- `tloz_objective_progress` y `tloz_progress_events`: completados e historial para el recap persistente.

No hay porcentajes, recomendaciones de ruta, detección dentro del juego, achievements ni mecánicas RPG nuevas.

## Flujo del panel y API

1. En Twitch, cambia la categoría al juego correspondiente. El backend ya la recibe mediante Helix/EventSub.
2. Abre `/admin/tloz`, introduce `OVERLAY_ADMIN_TOKEN` y vincula el juego con su **ID de categoría Twitch**. El catálogo no inventa IDs: el campo queda vacío hasta capturarlo desde el estado Twitch existente. Con el directo en esa categoría, consulta `GET /api/state` y copia `category_id`, o usa el catálogo de categorías detectadas en `/admin/game`; después edita ese juego desde el panel/API para guardarlo una sola vez.
3. Crea zonas y objetivos. En el bloque **Directo actual**, guarda consola, zona, objetivo y, solo cuando haga falta, una situación breve como `Combate con Gohma`.
4. Marca “completado” junto con el objetivo seleccionado para añadirlo al historial. El panel no avanza objetivos automáticamente.

Rutas públicas: `GET /api/tloz/current`.

Rutas de administración: `GET/POST /api/tloz/games`, `PUT /api/tloz/games/{id}`, `GET/POST /api/tloz/games/{id}/zones`, `PUT /api/tloz/zones/{id}`, `GET /api/tloz/games/{id}/objectives`, `POST /api/tloz/zones/{id}/objectives`, `PUT /api/tloz/objectives/{id}` y `PUT /api/tloz/current`.

## Browser Sources y layouts

- `http://IP_DE_LA_PI:8010/overlay/tloz` — en un juego con layout 16:9 es una capa transparente compacta: el gameplay ocupa todo OBS y la webcam se coloca por separado.
- `http://IP_DE_LA_PI:8010/overlay/tloz?position=top-right` — el mismo módulo compacto en una esquina libre. Valores: `top-left`, `top-right`, `bottom-left` (predeterminado) y `bottom-right`.
- `http://IP_DE_LA_PI:8010/overlay/tloz?position=top-right&mode=minimal` — oculta la etiqueta y consola para escenas con aún menos información fija.
- `http://IP_DE_LA_PI:8010/overlay/tloz/starting-soon` — tarjeta `Previously in Zelda` para Starting Soon.
- `http://IP_DE_LA_PI:8010/overlay/brb` — incluye el mismo recap como uno de sus módulos.

Configura la fuente Browser en **1920×1080** en OBS. Para 16:9, coloca la captura de juego a lienzo completo y esta Browser Source encima: no dibuja marco, guía ni caja de webcam. Elige la esquina libre según tu cámara mediante `position`; la fuente no reserva ninguna zona para ella. Los layouts no 16:9 conservan sus guías para organizar las fuentes de captura.

| Layout | Uso de las guías |
| --- | --- |
| `16_9` | capa transparente compacta sobre gameplay panorámico a lienzo completo; sin guía ni reserva de webcam |
| `4_3` | gameplay retro 4:3 centrado |
| `handheld` | captura vertical portátil |
| `ds` | pantalla inferior grande como gameplay; superior secundaria arriba a la izquierda; webcam en el espacio superior derecho |
| `3ds` | pantalla superior principal, inferior secundaria y webcam lateral |

## Migración y despliegue en la Pi

Antes de actualizar el contenedor, aplica una sola vez la migración usando el usuario de MariaDB que ya usas para las demás migraciones. Ejemplo si guardas la clave en una variable local:

```bash
read -s -p "Clave MariaDB: " DB_PASSWORD; echo
docker exec -i -e MYSQL_PWD="$DB_PASSWORD" mariadb mariadb -u root twitch_overlay < db/009_tloz_progress.sql
docker exec -i -e MYSQL_PWD="$DB_PASSWORD" mariadb mariadb -u root twitch_overlay < db/010_tloz_catalog_slugs.sql
unset DB_PASSWORD
docker compose up --build --detach
docker compose logs --tail=100 overlay
```

Las migraciones son aditivas e idempotentes para reintentarlas de forma segura; no borran tablas ni datos históricos.

## Catálogo inicial versionado

`data/tloz/chronology.json` contiene 19 juegos principales, orden de presentación
único, era/rama, plataforma, layout y un `twitch_category_id` deliberadamente
vacío. `skyward-sword.game.json` y `the-minish-cap.game.json` contienen, como
primeros ejemplos completos, 22 zonas y 71 objetivos de contexto para stream.
No son walkthroughs exhaustivos.

Después de aplicar `009` y `010`, y ya con la imagen actualizada, impórtalo así:

```bash
docker compose exec overlay python -m app.tloz.import_catalog
```

El importador valida **todos** los JSON antes de escribir y hace upsert por slug
de juego/zona/objetivo. Se puede ejecutar de nuevo al actualizar el catálogo:
actualiza títulos, orden y texto editorial, pero nunca elimina playthroughs ni
progreso de jugadores.

## Validación manual

1. Comprueba `curl http://IP:8010/api/tloz/current`: inicialmente devuelve `active: false` hasta mapear la categoría.
2. Ejecuta el importador, vincula con el `category_id` actualmente detectado y recarga `/admin/tloz`.
3. Guarda la consola/zona/objetivo, marca uno completado y confirma que aparece en `/overlay/tloz/starting-soon` y en la rotación BRB.
4. Cambia la categoría en Twitch a una no vinculada: las fuentes TLOZ se ocultan, mientras RPG y analítica continúan intactos.
