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
