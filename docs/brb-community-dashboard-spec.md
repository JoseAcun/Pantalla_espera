# STREAM_OS BRB Community Dashboard

## Especificación funcional y técnica para implementación

**Estado:** Propuesta lista para implementar  
**Proyecto:** Twitch Stream Overlay / STREAM_OS  
**Superficie principal:** `/overlay/brb`  
**Stack existente:** FastAPI, MariaDB, HTML/CSS/JavaScript sin frameworks, WebSocket `/ws/overlay`

## 1. Objetivo

Evolucionar la pantalla BRB actual para que, además del estado del stream, muestre actividad y progreso de la comunidad mediante tres módulos:

1. **Misiones activas:** misión diaria y semanal, progreso colectivo y completaciones recientes.
2. **USER_LOG:** feed público y limitado de acontecimientos relevantes del RPG.
3. **Tabla de temporada:** clasificación reiniciable basada en misiones completadas y XP obtenida durante la temporada.

La pantalla debe ayudar a que una persona nueva entienda que STREAM_OS es un RPG comunitario, reconocer a quienes participan y ofrecer una razón para regresar. No debe convertirse en un volcado de base de datos ni incentivar spam.

## 2. Alcance del MVP

### Incluido

- Mantener el bloque actual de estado del stream y eventos de Twitch.
- Añadir una rotación automática entre `STREAM_STATUS`, `QUEST_TRACKER`, `USER_LOG` y `SEASON_RANKING`.
- Mostrar como máximo una misión diaria y una semanal.
- Mostrar progreso colectivo de cada misión: jugadores que la completaron / jugadores registrados que tuvieron progreso en el periodo.
- Mostrar los últimos cinco usuarios que completaron la misión seleccionada.
- Mostrar un USER_LOG de máximo seis entradas visibles.
- Mostrar top cinco de la temporada.
- Carga inicial por HTTP y actualizaciones en vivo mediante el WebSocket existente.
- Estado vacío claro cuando MariaDB no esté configurada o no haya actividad.
- Pruebas del repositorio, endpoints y serialización de eventos.

### Fuera del MVP

- Panel público independiente para consultar todo el ranking.
- Ranking por tiempo visto.
- Animaciones complejas, avatares o retratos de usuarios.
- Premios automáticos por posición al terminar una temporada.
- Configuración visual avanzada desde Game Master.
- Exponer texto de mensajes de Twitch, IDs de mensajes o datos internos de moderación.

## 3. Principios de producto

1. **Reconocimiento antes que vigilancia.** El log debe celebrar progreso, no narrar cada acción del usuario.
2. **Actividad válida, no volumen de chat.** Nunca mostrar cada mensaje ni premiar cantidad bruta de mensajes.
3. **Oportunidad para usuarios nuevos.** La clasificación visible debe ser estacional, no histórica.
4. **Gameplay primero.** Esta información vive inicialmente en BRB; no se añade completa al overlay permanente del stream.
5. **Datos públicos mínimos.** Solo mostrar `display_name` y acontecimientos del RPG que sean apropiados para emisión.
6. **Degradación segura.** Una consulta o WebSocket fallido no debe romper las animaciones ni el estado básico del BRB.

## 4. Fuentes de datos existentes

### `game_player_activity`

La tabla existente es un ledger anti-spam. Registra actividad deduplicada mediante:

- `chat_messages`: máximo una entrada válida por minuto.
- `activity_windows`: una entrada por bloque de 20 minutos.
- `stream_days`: una entrada por día.
- `raid_actions`: una acción aceptada por el boss.

No debe presentarse directamente al navegador. `source_message_id` y `activity_key` son datos internos y nunca deben aparecer en respuestas públicas.

### Otras tablas existentes

- `game_players`: nombre, nivel, XP, créditos y última actividad.
- `game_quest_definitions`: definición de misiones.
- `game_player_quest_progress`: progreso, periodo y fecha de completado.
- `game_rewards`: XP y créditos entregados por una fuente.
- `game_player_items`: objetos adquiridos.

## 5. Modelo de temporadas

Crear una migración nueva, siguiendo la numeración del directorio `db/`.

```sql
CREATE TABLE game_seasons (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  slug VARCHAR(64) NOT NULL,
  starts_at DATETIME(6) NOT NULL,
  ends_at DATETIME(6) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (id),
  UNIQUE KEY uq_game_season_slug (slug),
  KEY idx_game_season_active_dates (active, starts_at, ends_at)
);
```

Para el MVP debe existir como máximo una temporada activa para la hora actual. Si no existe, el endpoint de ranking devuelve `season: null` y una lista vacía; no debe inventar una temporada implícita.

El ranking se calcula con eventos ocurridos entre `starts_at` y `ends_at`:

- `missions_completed`: cantidad de filas de `game_player_quest_progress` con `completed_at` dentro del periodo.
- `season_xp`: suma de `game_rewards.xp` dentro del periodo.
- Desempate: más misiones completadas, luego mayor XP de temporada, luego completado más reciente y finalmente nombre en orden ascendente.

No usar el XP histórico de `game_players.xp` como XP de temporada.

## 6. USER_LOG público

### Separación de responsabilidades

`game_player_activity` continúa siendo el registro técnico anti-spam. Crear una tabla separada para acontecimientos aptos para emisión:

```sql
CREATE TABLE game_public_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_user_id VARCHAR(32) NULL,
  event_type VARCHAR(40) NOT NULL,
  title VARCHAR(120) NOT NULL,
  detail VARCHAR(255) NOT NULL DEFAULT '',
  metadata_json JSON NULL,
  occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_game_public_events_time (occurred_at DESC),
  KEY idx_game_public_events_user_time (twitch_user_id, occurred_at DESC),
  CONSTRAINT fk_public_event_player
    FOREIGN KEY (twitch_user_id) REFERENCES game_players (twitch_user_id)
);
```

`metadata_json` solo almacena valores necesarios para renderizar, nunca texto de chat, tokens, `source_message_id` ni payloads completos de Twitch.

### Tipos iniciales

| Tipo | Cuándo se crea | Ejemplo visible |
|---|---|---|
| `player_joined` | Se crea un perfil con `!join` | `NEW PLAYER INITIALIZED` |
| `quest_completed` | Una misión pasa a completada y se entrega recompensa | `MISSION COMPLETE // +75 XP +30 C` |
| `item_acquired` | Una misión entrega un objeto | `ITEM ACQUIRED // FIREWALL MANTLE [RARE]` |
| `level_up` | El nivel resultante supera el nivel anterior | `LEVEL INCREASED // LV 08` |
| `raid_action_milestone` | Hito agregado de raid, no cada comando | `RAID SIGNAL // 10 ACTIONS ACCEPTED` |
| `activity_summary` | Resumen agregado opcional | `PARTY ACTIVITY // 8 USERS VERIFIED` |

Para el MVP son obligatorios `player_joined`, `quest_completed`, `item_acquired` y `level_up`. Los dos tipos agregados pueden implementarse después.

### Reglas de volumen

- Nunca crear un evento público por cada `chat_messages` o `activity_windows`.
- Como máximo una entrada de resumen de actividad cada diez minutos.
- Una completación de misión puede generar una sola entrada que incluya recompensa y objeto. No crear duplicados visuales si `quest_completed` ya contiene el objeto.
- Conservar eventos en base de datos; el endpoint entrega solo los últimos 20 y el BRB muestra hasta seis.

## 7. Contratos de respuesta

Añadir modelos Pydantic en `app/game/models.py` o en un módulo dedicado coherente con el proyecto.

### Snapshot del dashboard

`GET /api/game/community-dashboard`

Este endpoint es público y de solo lectura. No requiere `X-Overlay-Admin-Token` porque OBS debe poder consumirlo.

```json
{
  "generated_at": "2026-09-01T21:45:00Z",
  "quests": [
    {
      "id": 12,
      "cadence": "daily",
      "name": "Señal online",
      "description": "Participa en tres ventanas del directo.",
      "objective_type": "activity_windows",
      "objective_target": 3,
      "reward_xp": 75,
      "reward_credits": 30,
      "period_key": "2026-09-01",
      "participants": 20,
      "completions": 12,
      "recent_completers": [
        {"display_name": "KERNELCAT", "completed_at": "2026-09-01T21:42:00Z"}
      ]
    }
  ],
  "user_log": [
    {
      "id": 442,
      "event_type": "quest_completed",
      "display_name": "KERNELCAT",
      "title": "MISSION COMPLETE",
      "detail": "SIGNAL ONLINE // +75 XP +30 C",
      "occurred_at": "2026-09-01T21:42:00Z"
    }
  ],
  "season": {
    "name": "SEASON_01 // BOOT SEQUENCE",
    "starts_at": "2026-09-01T00:00:00Z",
    "ends_at": "2026-09-30T23:59:59Z",
    "days_remaining": 29,
    "leaders": [
      {
        "rank": 1,
        "display_name": "KERNELCAT",
        "missions_completed": 18,
        "season_xp": 4820
      }
    ]
  }
}
```

### WebSocket

Al conectar a `/ws/overlay`, enviar también:

```json
{"type": "game.community.snapshot", "data": {}}
```

Cuando se cree un evento público o cambie una completación relevante, emitir uno de estos mensajes:

```json
{"type": "game.community.event", "data": {}}
{"type": "game.community.refresh", "data": {}}
```

Recomendación para el MVP: `game.community.event` añade inmediatamente una línea al log; `game.community.refresh` provoca que el cliente vuelva a solicitar el snapshot completo. Evitar emitir el ranking completo por cada mensaje de chat.

## 8. Consultas del repositorio

Añadir métodos a `GameRepository` con nombres equivalentes a:

- `community_dashboard(category_id: str = "")`
- `active_public_quests(category_id: str = "")`
- `recent_public_events(limit: int = 20)`
- `active_season_leaders(limit: int = 5)`
- `record_public_event(...)`

### Misiones activas

- Respetar misiones globales y la categoría actual, igual que `player_quests`.
- Calcular `period_key` usando la misma función y zona horaria que el progreso existente.
- Elegir como máximo una diaria y una semanal, ordenadas por `id` ascendente en el MVP.
- `participants` cuenta usuarios con fila de progreso en la misión y periodo actuales.
- `completions` cuenta filas con `completed_at IS NOT NULL`.
- `recent_completers` devuelve como máximo cinco nombres, ordenados por `completed_at DESC`.

### Ranking

- Limitar todas las consultas públicas a un máximo fijo en backend aunque el cliente solicite más.
- Excluir usuarios sin actividad durante la temporada.
- No exponer `twitch_user_id` al frontend salvo necesidad futura justificada.

## 9. Integración con la lógica existente

### Registro de jugador

En el flujo de `!join`, si `register_player` informa `created=True`:

1. Crear `player_joined` en `game_public_events`.
2. Emitir `game.community.event`.

### Completación de misión

Actualmente `_advance_quests` devuelve `QuestCompletion`. Extender el resultado con los datos mínimos necesarios para registrar el evento de forma idempotente, preferiblemente `quest_id`, `period_key` y nivel anterior/nuevo.

La creación de recompensa y evento público debe ocurrir dentro de la misma transacción. Añadir una clave única o un `source_type/source_id` equivalente para impedir duplicados si Twitch reenvía un evento.

Después de confirmar la transacción:

1. Mantener el anuncio actual en el chat.
2. Emitir `game.community.event` con la versión pública.
3. Emitir `game.community.refresh` para actualizar misión y ranking.

### Objetos y nivel

- Incluir el objeto en el mismo evento de completación durante el MVP.
- Registrar `level_up` solo si el nivel calculado aumenta realmente.
- No emitir eventos si el `INSERT IGNORE` de recompensa indica que ya se procesó la fuente.

## 10. Interfaz BRB

### Estructura

Mantener la cabecera actual. Dentro de `.content`, convertir la pantalla en un contenedor de módulos rotativos:

```text
STREAM_OS v0.2                                      LOCAL ONLINE

> mount module://quest_tracker

ACTIVE QUEST
SEÑAL ONLINE                              DAILY
Participa en tres ventanas del directo.
[############--------] 12 / 20 USERS
REWARD: 75 XP + 30 CREDITS

RECENT COMPLETIONS
01 KERNELCAT   21:42
02 NOVA_PLAYER 21:37
03 BOKUFAN92   21:31
```

```text
> open USER_LOG --tail=6

21:42 KERNELCAT    MISSION COMPLETE
                    SIGNAL ONLINE // +75 XP +30 C
21:36 GUEST_404    NEW PLAYER INITIALIZED
21:31 NOVA_PLAYER  LEVEL INCREASED // LV 08
```

```text
> calculate season_ranking

SEASON_01 // BOOT SEQUENCE                12 DAYS REMAINING
RANK  PLAYER          MISSIONS       XP
01    KERNELCAT       18           4820
02    SANTIAGO42      16           4150
03    NOVA_PLAYER     14           3760
04    BOKUFAN92       12           3210
05    GUEST_404       11           2980
```

### Rotación

- `STREAM_STATUS`: 8 segundos.
- `QUEST_TRACKER`: 10 segundos.
- `USER_LOG`: 10 segundos.
- `SEASON_RANKING`: 10 segundos.
- Transición de 300–500 ms con opacidad y desplazamiento vertical corto.
- Respetar `prefers-reduced-motion` desactivando desplazamientos y usando solo cambio de opacidad.
- Si un módulo no tiene datos, omitirlo de la rotación en lugar de mostrar una pantalla vacía completa.

### Estilo

- Conservar negro/verde, brillo CRT, scanlines y tipografía monoespaciada.
- Usar amarillo para recompensas/avisos y rojo solo para errores o amenazas.
- No reducir texto importante por debajo de 20 px efectivos en un lienzo 1920×1080.
- Truncar nombres largos con elipsis y preservar alineación de columnas.
- El USER_LOG debe usar nombres escapados mediante `textContent`, nunca `innerHTML` con datos externos.

### Estados vacíos

Ejemplos:

```text
QUEST_TRACKER: NO ACTIVE MISSIONS
USER_LOG: WAITING FOR PLAYER SIGNAL
SEASON_RANKING: NO ACTIVE SEASON
```

Si `/api/game/community-dashboard` responde 503, la pantalla original debe continuar funcionando y el módulo comunitario se omite durante esa sesión o reintenta con backoff.

## 11. Administración mínima

Añadir al panel `/admin/game` una sección de temporada:

- Nombre.
- Slug generado o editable.
- Fecha/hora de inicio.
- Fecha/hora de cierre.
- Activar/desactivar.

Las rutas de escritura deben requerir `X-Overlay-Admin-Token`:

- `GET /api/game/seasons`
- `POST /api/game/seasons`
- `PUT /api/game/seasons/{season_id}`

No es necesario implementar borrado en el MVP; desactivar conserva el historial.

## 12. Seguridad y privacidad

- No incluir texto de chat en `game_public_events` ni respuestas del dashboard.
- No exponer `source_message_id`, `activity_key`, tokens, correos, login interno ni payloads Twitch.
- Renderizar todo nombre o detalle externo con `textContent`.
- Limitar longitudes en Pydantic y base de datos.
- El endpoint público es exclusivamente de lectura.
- Las acciones de administración conservan la validación del token existente.
- Los fallos de base de datos se registran en servidor sin mostrar SQL o credenciales al navegador.

## 13. Rendimiento

- El snapshot público debe responder con una cantidad acotada: 2 misiones, 20 eventos y 5 líderes como máximo.
- Añadir índices necesarios para fechas de completado y recompensas si `EXPLAIN` muestra escaneos completos.
- No recalcular el ranking cada segundo. Cargar al abrir, al recibir `game.community.refresh` y opcionalmente cada 60 segundos como recuperación.
- Las consultas de MariaDB continúan ejecutándose mediante `asyncio.to_thread` como el resto del proyecto.

## 14. Pruebas requeridas

### Repositorio

- Selecciona correctamente misión diaria y semanal del periodo actual.
- Respeta categoría global y categoría del stream.
- Cuenta participantes y completaciones sin duplicados.
- Ordena completadores recientes.
- Calcula ranking dentro de las fechas de temporada, no con XP histórico.
- Aplica desempates de forma determinista.
- No duplica eventos públicos al reprocesar una recompensa.

### API

- Devuelve el contrato completo con datos.
- Devuelve listas vacías sin temporada o misiones.
- Devuelve 503 controlado si no existe `DATABASE_URL`.
- Las rutas de temporada rechazan token inválido.
- El endpoint público no devuelve identificadores o campos internos.

### WebSocket

- Envía snapshot comunitario al conectar cuando la base está disponible.
- Emite evento y refresh después de una completación.
- Un fallo del dashboard no impide enviar `stream_state` ni `pokemon_team`.

### Frontend

- Rota únicamente entre módulos con contenido.
- Tolera reconexión y snapshot repetido sin duplicar entradas del log.
- Limita el feed visible a seis eventos.
- Escapa nombres y detalles.
- Respeta `prefers-reduced-motion`.
- Se visualiza correctamente en 1920×1080 y mantiene legibilidad en 1280×720.

## 15. Criterios de aceptación

La funcionalidad se considera completa cuando:

1. `/overlay/brb` conserva sus funciones actuales y muestra los nuevos módulos sin recargar la página.
2. Una persona que utiliza `!join` aparece en USER_LOG una sola vez.
3. Una misión completada aparece en USER_LOG, actualiza su lista de completadores y actualiza el ranking.
4. El ranking usa solamente la temporada activa y muestra máximo cinco usuarios.
5. Ningún mensaje de chat, ID técnico o secreto llega al navegador.
6. Sin MariaDB o sin temporada activa, el BRB sigue siendo utilizable.
7. Todas las pruebas existentes y nuevas pasan.
8. El README documenta migración, rutas, configuración de temporada y comportamiento del BRB.

## 16. Orden recomendado de implementación

1. Crear migración de temporadas y eventos públicos.
2. Añadir modelos Pydantic y métodos de repositorio.
3. Implementar snapshot público y rutas administrativas de temporada.
4. Registrar eventos públicos de forma transaccional e idempotente.
5. Añadir mensajes WebSocket sin alterar los existentes.
6. Construir los módulos y la rotación del BRB.
7. Añadir administración básica de temporada.
8. Crear pruebas y actualizar README.
9. Previsualizar a 1920×1080 y 1280×720 con datos de muestra.

## 17. Instrucción breve para una tarea de Codex

Usar esta especificación como fuente de verdad para implementar el **STREAM_OS BRB Community Dashboard** en el proyecto existente. Preservar la arquitectura FastAPI/MariaDB/HTML-CSS-JS sin frameworks, mantener compatibilidad con los overlays actuales y no modificar comportamientos ajenos al alcance. Antes de editar, inspeccionar las migraciones y pruebas existentes; después implementar por capas, ejecutar todas las pruebas y verificar visualmente `/overlay/brb` en 1920×1080 y 1280×720.
