# Twitch Stream Overlay — Terminal BRB

Overlay local para OBS, construido con FastAPI y HTML/CSS/JavaScript sin frameworks. Incluye una pantalla BRB animada, actualizaciones de estado por WebSocket local y conexión OAuth con Twitch para cargar la información inicial del canal mediante Helix.

## Estructura

```text
app/
  main.py          # servidor HTTP, API y WebSocket para OBS
  state.py          # estado compartido del stream
  models.py         # contratos de datos
  static/brb/       # escena web independiente
```

## Arranque local

1. Crea y activa el entorno virtual:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Instala las dependencias y prepara la configuración:

   ```powershell
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

3. Inicia el backend:

   ```powershell
   uvicorn app.main:app --reload
   ```

4. Comprueba `http://localhost:8000/health` y abre `http://localhost:8000/overlay/brb`.

## Conectar Twitch

1. Copia el Client ID de tu app en `.env` como `TWITCH_CLIENT_ID`.
2. Si la consola también ofrece **New Secret**, puedes generar uno, guardarlo como `TWITCH_CLIENT_SECRET` y añadir exactamente `http://localhost:8000/auth/twitch/callback` como OAuth Redirect URL. El proyecto usará Authorization Code Grant.
3. Si tu app es pública y no muestra **New Secret**, deja `TWITCH_CLIENT_SECRET` vacío: el proyecto usará Device Code Grant, pensado para aplicaciones locales de escritorio.
4. Reinicia el servidor y abre `http://localhost:8000/auth/twitch/start`. En el flujo público, abre Twitch Activate, ingresa el código mostrado y vuelve a esta pestaña.
4. El backend guarda el token y refresh token solamente en `.twitch_tokens.json`, archivo ignorado por Git. Verifica la conexión en `http://localhost:8000/api/twitch/status`.

Tras autorizar, el backend consulta Helix (`users`, `channels` y `streams`) y actualiza el overlay conectado. Puedes forzar una actualización con `POST http://localhost:8000/api/twitch/sync`.

La escena BRB muestra los últimos follow, sub, cheer y raid que EventSub reciba mientras el backend está conectado. Hasta el primer evento de cada tipo verá `WAITING FOR SIGNAL`.

También muestra viewers actuales y duración del directo. La duración se calcula localmente desde la hora de inicio informada por Helix; el backend actualiza los viewers una vez por minuto.

### Persistencia opcional con MariaDB

Si defines `DATABASE_URL`, el backend guarda cada entrega de EventSub en `twitch_events` y la relaciona con `twitch_users`, `follows`, `subscription_events`, `cheers` o `raids`. Al reiniciar, restaura el último evento de cada tipo y evita duplicados mediante el identificador de mensaje. Además, Helix consulta y persiste el último follow existente al conectar, aunque haya ocurrido antes de arrancar el backend.

Para registrar un sub que confirmaste manualmente, define `OVERLAY_ADMIN_TOKEN` en `.env`. Primero consulta `GET /api/twitch/users/{nick}`; después envía `POST /api/twitch/manual/subscriber` con el encabezado `X-Overlay-Admin-Token`, el `login` y el `tier` (`1000`, `2000` o `3000`). El registro queda marcado como `source: manual` en `twitch_events`.

## OBS

En OBS crea una **Browser Source** con la URL `http://localhost:8000/overlay/brb`. El overlay ocupa todo el lienzo de la fuente: configura **1920×1080** para stream 16:9 (o exactamente la resolución de tu lienzo) y deja activado "Refresh browser when scene becomes active" si quieres reiniciar la animación al entrar a la escena.

### Música BRB

La escena reproduce la pista local configurada en `app/static/audio/`, a volumen bajo. En la Browser Source activa **Control audio via OBS** para que aparezca en el mezclador. Si OBS bloquea el autoplay en tu instalación, añade esa misma pista como **Media Source**, activa `Loop` y baja el volumen desde el mezclador; no añadas ambas fuentes de audio a la vez. Verifica que cuentas con los permisos o licencia de la pista antes de emitir.

## Twitch y EventSub

La cuenta del broadcaster autorizará una aplicación de Twitch mediante OAuth. Las credenciales viven exclusivamente en `.env`; el navegador nunca recibe tokens ni secretos.

Scopes previstos, únicamente al implementar la función correspondiente:

- `moderator:read:followers`: último follow y `channel.follow`.
- `channel:read:subscriptions`: suscripciones y `channel.subscribe`.
- `bits:read`: cheers y `channel.cheer`.

`channel.raid` y `channel.update` no exigen scope para el tipo de evento, aunque EventSub por WebSocket requiere un token de usuario para crear suscripciones. Para un backend local se usa EventSub WebSocket: no hace falta exponer un callback HTTPS público. Tras la autorización, el backend conecta y registra `channel.follow`, `channel.subscribe`, `channel.cheer`, `channel.raid` y `channel.update` automáticamente; consulta `GET /api/twitch/status` para ver `eventsub_connected`.

Twitch puede reenviar una notificación, y los eventos ocurridos durante una desconexión de EventSub no se recuperan. La siguiente mejora será persistir los últimos eventos para conservarlos tras reinicios.

## Pruebas

Sin credenciales el proyecto funciona en modo demo: abre el overlay y verifica que el indicador cambia a `LOCAL ONLINE`, que recibe el estado inicial y que la animación se repite. La API de estado está disponible en `GET /api/state`.

## Despliegue en Raspberry Pi

El backend puede vivir en una Raspberry Pi dentro de tu red local; OBS se conecta a ella por IP o nombre de host. No expongas el puerto 8000 a Internet ni hagas port-forwarding en el router.

### Preparar la Pi

En Raspberry Pi OS, conéctate por SSH y ejecuta lo siguiente como tu usuario normal (sustituye la URL del repositorio):

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install -y git python3-venv python3-pip
git clone https://github.com/TU_USUARIO/TU_REPOSITORIO.git ~/stream-overlay
cd ~/stream-overlay
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
```

Edita `.env` y añade `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` y los valores manuales. Usa una IP reservada en el router o un hostname estable, por ejemplo `stream-overlay.local`. Para realizar OAuth desde otro equipo de tu LAN, registra en Twitch y en `TWITCH_REDIRECT_URI` exactamente la misma URL, por ejemplo:

```env
TWITCH_REDIRECT_URI=http://stream-overlay.local:8000/auth/twitch/callback
```

Después abre `http://stream-overlay.local:8000/auth/twitch/start` desde un navegador de tu red y autoriza Twitch. Si mDNS no funciona en tu red, usa la IP obtenida con `hostname -I` en su lugar y regístrala exactamente igual en Twitch.

### Servicio automático

Instala la unidad incluida y arráncala con tu usuario actual:

```bash
cd ~/stream-overlay
sudo cp deploy/stream-overlay@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stream-overlay@$USER.service
sudo systemctl status stream-overlay@$USER.service
```

El servicio arranca tras reinicios y reinicia automáticamente si falla. Para ver registros:

```bash
journalctl -u stream-overlay@$USER.service -f
```

### OBS y actualizaciones

Desde el equipo donde ejecutas OBS, usa `http://stream-overlay.local:8000/overlay/brb` (o la IP de la Pi) como URL de Browser Source. Configura 1920×1080 y activa **Control audio via OBS** si quieres que OBS mezcle la música.

Para publicar una actualización desde GitHub en la Pi:

```bash
cd ~/stream-overlay
bash deploy/update-on-pi.sh
```

El script usa `git pull --ff-only`, actualiza dependencias y reinicia el servicio. Tus archivos `.env` y `.twitch_tokens.json` no se modifican ni se suben al repositorio.

## Despliegue recomendado: Docker Compose en Raspberry Pi

Esta es la opción recomendada para la Pi. La imagen contiene el código y dependencias; `.env` se queda en la Pi y un volumen Docker persistente conserva los tokens de Twitch al actualizar o recrear el contenedor.

`compose.yaml` debe permanecer versionado: describe la aplicación reproducible. Los valores propios de cada equipo van en `.env`, que está ignorado por Git. Por ejemplo, `OVERLAY_PORT=8010` evita editar el YAML cuando el puerto 8000 ya está ocupado.

Si alguna vez necesitas cambiar la estructura solo en una Pi (por ejemplo, añadir otro volumen), crea `compose.override.yaml`; Docker Compose lo aplica automáticamente y el proyecto lo ignora en Git.

### Instalar Docker y arrancar

Instala Docker Engine y el plugin Compose siguiendo la guía oficial de Docker para tu edición de Raspberry Pi OS. Luego clona tu repositorio y ejecuta:

```bash
git clone https://github.com/TU_USUARIO/TU_REPOSITORIO.git ~/stream-overlay
cd ~/stream-overlay
cp .env.example .env
chmod 600 .env
nano .env
docker compose up --build --detach
docker compose ps
docker compose logs --follow
```

En `.env` usa la IP reservada o hostname de la Pi en `TWITCH_REDIRECT_URI`, y registra exactamente esa misma URL en Twitch. Por ejemplo, si la IP de la Pi es `192.168.1.50`:

```env
TWITCH_REDIRECT_URI=http://192.168.1.50:8000/auth/twitch/callback
```

Desde un equipo de la misma red abre `http://192.168.1.50:8010/auth/twitch/start` y completa OAuth. El volumen `twitch-overlay-data` conserva el token fuera del contenedor. Usa el mismo host y puerto tanto para abrir esta URL como en `TWITCH_REDIRECT_URI`; no alternes entre IP, hostname o `localhost` durante el flujo.

Para OBS, usa `http://192.168.1.50:8010/overlay/brb` como Browser Source. No expongas el puerto publicado a Internet.

Para una barra discreta sobre el stream (fondo transparente y datos resumidos en la parte inferior), añade otra Browser Source con `http://192.168.1.50:8010/overlay/stream` y el mismo tamaño de tu lienzo, por ejemplo 1920×1080.

### STREAM_OS RPG (MVP de raid)

Ejecuta `db/002_game_schema.sql` una vez en MariaDB después de la migración inicial. Abre `http://IP_DE_LA_PI:8010/admin/game`, introduce `OVERLAY_ADMIN_TOKEN` y configura las categorías que Twitch haya detectado; cada una tiene su propio tema y contenido futuro. Desde esa misma vista puedes iniciar el boss de prueba de la categoría actual.

Los espectadores se registran con `!join` y participan una vez por ronda mediante `!attack`, `!defend` o `!heal`. La fuente de OBS `http://IP_DE_LA_PI:8010/overlay/game/boss` muestra solo el estado colectivo. Después de desplegar esta versión debes renovar OAuth para conceder `user:read:chat` y `user:write:chat`; sin esos permisos el resto del overlay seguirá funcionando, pero el Game Master no recibirá ni podrá responder mensajes.

#### Progresión de niveles

La XP de `game_players` es el total acumulado y la fuente de verdad. El nivel es una caché recalculable: pasar del nivel `L` al siguiente requiere `100 × 1.15^(L-1)` XP, redondeada al múltiplo de 5 más cercano. Los valores se pueden ajustar solo desde `GAME_LEVEL_BASE_XP`, `GAME_LEVEL_GROWTH` y `GAME_LEVEL_ROUNDING`; si los cambias, después de desplegar ejecuta `docker compose exec overlay python -m app.game.recalculate_levels` para actualizar los niveles almacenados sin modificar XP, créditos ni inventario.

`!profile` muestra la XP total y el progreso dentro del nivel actual. Las misiones y las rondas de raid usan la misma concesión idempotente de recompensas, por lo que ambas actualizan el nivel de la misma forma.

Al desplegar esta versión, ejecuta una vez `db/008_level_progression.sql`. Preserva XP, créditos, inventario y progreso de misiones; solo actualiza la caché `game_players.level` con la curva nueva.

### BRB Community Dashboard

Después de aplicar las migraciones RPG anteriores, ejecuta `db/007_community_dashboard.sql` una vez. La pantalla `http://IP_DE_LA_PI:8010/overlay/brb` sigue mostrando el estado actual del stream y rota, solo cuando hay datos, entre misiones activas, el registro público de actividad y el ranking de temporada. Si MariaDB no está disponible, la BRB conserva el módulo de estado sin interrumpirse.

En `http://IP_DE_LA_PI:8010/admin/game`, usando `OVERLAY_ADMIN_TOKEN`, crea una temporada con inicio y cierre que incluyan la hora actual. El ranking no aparece hasta que exista una temporada activa; cuenta exclusivamente misiones completadas y XP de recompensas dentro de sus fechas. No se elimina el historial al desactivarla.

Los eventos públicos se generan una sola vez para `!join`, completaciones de misión y aumentos de nivel. No se publican mensajes de chat, identificadores internos ni los buckets anti-spam. El endpoint público que consume BRB es `GET /api/game/community-dashboard`; las rutas de administración de temporadas requieren el token.

En una Pi con MariaDB en el contenedor `mariadb`, aplica la migración así:

```bash
read -rsp "Clave MariaDB: " DB_PASSWORD; echo
docker exec -i -e MYSQL_PWD="$DB_PASSWORD" mariadb \
  mariadb -u root twitch_overlay < db/007_community_dashboard.sql
unset DB_PASSWORD
```

### Equipo Pokémon

Abre `http://192.168.1.50:8010/admin/pokemon`, escribe el valor de `OVERLAY_ADMIN_TOKEN`, y configura hasta seis Pokémon con apodo opcional. Al guardar, el backend consulta PokéAPI y conserva el sprite en el volumen `/data`; por ello el overlay sigue mostrando el equipo aunque PokéAPI no esté disponible durante el stream. En OBS añade una Browser Source transparente con `http://192.168.1.50:8010/overlay/pokemon`, a la resolución de tu lienzo. La barra lateral se actualiza en vivo al guardar un cambio.

### Actualizar desde GitHub

```bash
cd ~/stream-overlay
bash deploy/docker-update-on-pi.sh
```

El comando descarga únicamente actualizaciones fast-forward, reconstruye la imagen y recrea el contenedor. La política `unless-stopped` hace que vuelva a iniciar tras un reinicio de la Pi.
