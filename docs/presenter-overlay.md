# Superficie de presentación / tráiler

`/overlay/presenter` es una Browser Source independiente pensada para grabar un tráiler del canal o conversar con el chat. No cambia las escenas BRB, Starting Soon, gameplay ni guarda datos: solo lee el estado público ya disponible del canal, la comunidad y TLOZ.

## URLs

Usa la IP actual de la Raspberry Pi y el puerto publicado por Docker:

```text
http://192.168.1.28:8010/overlay/presenter
http://192.168.1.28:8010/overlay/presenter?mode=trailer&camera=right
http://192.168.1.28:8010/overlay/presenter?mode=chat&camera=left
http://192.168.1.28:8010/overlay/presenter?mode=trailer&camera=none&channel_name=BokugaNEGAI&schedule=Directos%20miércoles%20y%20sábado
http://192.168.1.28:8010/admin/presenter
```

Parámetros disponibles:

- `mode=trailer` (predeterminado): rota de forma determinista cuatro módulos de 15 segundos; el ciclo completo dura 60 segundos.
- `mode=chat`: no rota. Pulsa `←` y `→`, o los números `1` a `4`, para cambiar entre identidad, comunidad, proyecto TLOZ y cierre.
- `camera=right` (predeterminado), `camera=left` o `camera=none`: reserva aproximadamente un tercio del lienzo para la cámara. La zona reservada no contiene texto ni tarjetas.
- `channel_name` y `schedule`: reemplazan texto de presentación. Se muestran como texto plano, por lo que no interpretan HTML.

Si el dashboard comunitario no está disponible, la tarjeta conserva una composición de espera. Si no hay proyecto TLOZ activo, muestra un archivo de aventura genérico; no genera ni almacena información nueva. No hay módulo de historial de streams porque el proyecto todavía no expone ese historial en una API pública.

## Panel desde tablet

Abre `http://192.168.1.28:8010/admin/presenter` desde la tablet conectada a la misma red. Introduce `OVERLAY_ADMIN_TOKEN` y usa los botones grandes para escoger qué módulo está al aire, avanzar o retroceder, y detener o reiniciar la rotación. El panel también cambia el lado seguro de cámara, la duración entre `5` y `60` segundos y los textos de presentación.

El token solo viaja en las solicitudes de administración de esa pestaña: no se almacena en el navegador. Cada cambio se transmite al instante a las Browser Sources Presenter conectadas mediante `presenter.control`. El panel muestra el módulo calculado actualmente, el modo automático o manual y su conexión con el backend.

El control remoto es temporal: el primer cambio del panel toma prioridad sobre los parámetros de URL durante esa sesión del proceso. Si no se usa el panel, Presenter conserva exactamente sus parámetros `mode`, `camera`, `channel_name` y `schedule`. Reiniciar el backend descarta el control remoto y regresa a esos valores predeterminados; no hay tablas, migraciones ni archivos de configuración nuevos.

El panel **no** controla OBS ni requiere `obs-websocket`: solo cambia la composición interna de `/overlay/presenter`. Las escenas de OBS, BRB, Starting Soon, gameplay y TLOZ continúan siendo independientes.

## Grabación en OBS

1. Crea una escena nueva, por ejemplo `TRAILER`.
2. Añade una Browser Source con una de las URLs anteriores, tamaño `1920 × 1080`; no actives audio porque esta fuente no reproduce música.
3. Añade la cámara como una fuente separada sobre el tercio libre indicado por `camera`. Con `camera=right`, colócala a la derecha; con `camera=left`, a la izquierda.
4. Para grabar, usa `mode=trailer`: tarda 60 segundos y vuelve al inicio. Para conversar, usa `mode=chat` y deja seleccionada la Browser Source antes de usar las teclas.

La fuente se actualiza al recibir los mensajes públicos del WebSocket; también hace una consulta inicial a los endpoints de estado. Como no tiene persistencia ni configuración propia, retirarla consiste en eliminar la Browser Source y, si ya no se desea, la ruta y la carpeta `app/static/presenter/` junto con la pequeña sección Presenter de `app/main.py`.
