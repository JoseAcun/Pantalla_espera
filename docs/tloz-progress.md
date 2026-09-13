# TLOZ V1: progreso del directo

Esta capa añade seguimiento editorial de **Juego → Zonas → Objetivos** sin sustituir STREAM_OS RPG, analítica, Pokémon ni la integración Twitch ya existente.

## Componentes reutilizados

- **Twitch/Helix y EventSub:** `StreamState` ya contiene `category_id`, `category`, `twitch_stream_id`, estado del directo y audiencia. TLOZ usa solamente `category_id` para identificar el juego actual; no hay un selector manual de juego en tiempo de directo.
- **FastAPI y panel local:** rutas en `app/main.py`, autenticadas con el mismo `X-Overlay-Admin-Token`, y una página estática nueva en `/admin/tloz`.
- **MariaDB Docker existente:** `DATABASE_URL` y la red `stream-data`; no se introduce SQLite, volumen ni contenedor adicional.
- **WebSocket/Browser Sources:** el mensaje `tloz.state` se entrega al conectar, tras guardar desde el panel y en el refresco periódico de Twitch. Los overlays además hacen una consulta prudente cada minuto como respaldo.
- **BRB existente:** `/overlay/brb` incorpora un módulo rotativo `PREVIOUSLY IN ZELDA` que solo aparece mientras la categoría Twitch esté vinculada a un juego TLOZ.

## Modelo persistido

La migración `db/009_tloz_progress.sql` crea exclusivamente estas tablas:

- `tloz_games`: catálogo, relación única opcional `twitch_category_id`, orden de cronología y layout.
- `tloz_zones`: zonas ordenadas de un juego.
- `tloz_objectives`: objetivos ordenados de una zona, marcados como `required` u `optional`.
- `tloz_playthroughs`: consola, zona, objetivo y estado especial actuales. Guarda el `twitch_stream_id` automáticamente cuando Twitch lo tenga.
- `tloz_objective_progress` y `tloz_progress_events`: completados e historial para el recap persistente.

No hay porcentajes, recomendaciones de ruta, detección dentro del juego, achievements ni mecánicas RPG nuevas.

## Flujo del panel y API

1. En Twitch, cambia la categoría al juego correspondiente. El backend ya la recibe mediante Helix/EventSub.
2. Abre `/admin/tloz`, introduce `OVERLAY_ADMIN_TOKEN` y crea el juego con su **ID de categoría Twitch**. Ese ID se obtiene del catálogo existente de categorías o de la respuesta de Twitch; se registra una vez, no en cada stream.
3. Crea zonas y objetivos. En el bloque **Directo actual**, guarda consola, zona, objetivo y, solo cuando haga falta, una situación breve como `Combate con Gohma`.
4. Marca “completado” junto con el objetivo seleccionado para añadirlo al historial. El panel no avanza objetivos automáticamente.

Rutas públicas: `GET /api/tloz/current`.

Rutas de administración: `GET/POST /api/tloz/games`, `PUT /api/tloz/games/{id}`, `GET/POST /api/tloz/games/{id}/zones`, `PUT /api/tloz/zones/{id}`, `GET /api/tloz/games/{id}/objectives`, `POST /api/tloz/zones/{id}/objectives`, `PUT /api/tloz/objectives/{id}` y `PUT /api/tloz/current`.

## Browser Sources y layouts

- `http://IP_DE_LA_PI:8010/overlay/tloz` — guía transparente del layout de juego y tarjeta de estado.
- `http://IP_DE_LA_PI:8010/overlay/tloz/starting-soon` — tarjeta `Previously in Zelda` para Starting Soon.
- `http://IP_DE_LA_PI:8010/overlay/brb` — incluye el mismo recap como uno de sus módulos.

Configura la fuente Browser en **1920×1080** en OBS. El overlay no captura vídeo: las cajas punteadas son guías para colocar las fuentes de captura y webcam detrás/debajo de la fuente Browser.

| Layout | Uso de las guías |
| --- | --- |
| `16_9` | gameplay panorámico principal |
| `4_3` | gameplay retro 4:3 centrado |
| `handheld` | captura vertical portátil |
| `ds` | pantalla inferior grande como gameplay; superior secundaria arriba a la izquierda; webcam en el espacio superior derecho |
| `3ds` | pantalla superior principal, inferior secundaria y webcam lateral |

## Migración y despliegue en la Pi

Antes de actualizar el contenedor, aplica una sola vez la migración usando el usuario de MariaDB que ya usas para las demás migraciones. Ejemplo si guardas la clave en una variable local:

```bash
read -s -p "Clave MariaDB: " DB_PASSWORD; echo
docker exec -i -e MYSQL_PWD="$DB_PASSWORD" mariadb mariadb -u root twitch_overlay < db/009_tloz_progress.sql
unset DB_PASSWORD
docker compose up --build --detach
docker compose logs --tail=100 overlay
```

La migración es aditiva e idempotente para reintentarla de forma segura; no borra tablas ni datos históricos.

## Validación manual

1. Comprueba `curl http://IP:8010/api/tloz/current`: inicialmente devuelve `active: false` hasta mapear la categoría.
2. Crea un juego con el ID de categoría actualmente detectado, zonas y objetivos en `/admin/tloz`.
3. Guarda la consola/zona/objetivo, marca uno completado y confirma que aparece en `/overlay/tloz/starting-soon` y en la rotación BRB.
4. Cambia la categoría en Twitch a una no vinculada: las fuentes TLOZ se ocultan, mientras RPG y analítica continúan intactos.
