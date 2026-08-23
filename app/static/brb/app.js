const elements = {
  connection: document.querySelector('#connection'), streamer: document.querySelector('#streamer'),
  status: document.querySelector('#stream-status'), game: document.querySelector('#game'),
  episode: document.querySelector('#episode'), command: document.querySelector('#typed-command'),
  message: document.querySelector('#message'), progress: document.querySelector('#progress-bar'),
  follower: document.querySelector('#last-follower'), subscriber: document.querySelector('#last-subscriber'),
  cheer: document.querySelector('#last-cheer'), raid: document.querySelector('#last-raid'),
  viewers: document.querySelector('#viewer-count'), uptime: document.querySelector('#stream-uptime'),
};

let currentState = {};

function eventText(event, text) { return event?.username && event.username !== '—' ? text : 'WAITING FOR SIGNAL'; }

function render(state) {
  currentState = state;
  elements.streamer.textContent = state.streamer || '—';
  elements.status.textContent = state.status || 'AFK';
  elements.game.textContent = state.game || 'NO GAME SELECTED';
  elements.episode.textContent = state.episode || '—';
  elements.viewers.textContent = state.is_live ? String(state.viewer_count ?? 0) : '0';
  elements.follower.textContent = eventText(state.last_follower, state.last_follower?.username);
  elements.subscriber.textContent = eventText(state.last_subscriber, `${state.last_subscriber?.username || ''} · TIER ${state.last_subscriber?.tier || '—'}`);
  elements.cheer.textContent = eventText(state.last_cheer, `${state.last_cheer?.username || ''} · ${state.last_cheer?.bits || 0} BITS`);
  elements.raid.textContent = eventText(state.last_raid, `${state.last_raid?.username || ''} · ${state.last_raid?.viewers || 0} VIEWERS`);
  renderUptime();
}

function renderUptime() {
  if (!currentState.is_live || !currentState.stream_started_at) {
    elements.uptime.textContent = 'OFFLINE';
    return;
  }
  const elapsed = Math.max(0, Math.floor((Date.now() - new Date(currentState.stream_started_at).getTime()) / 1000));
  const hours = Math.floor(elapsed / 3600);
  const minutes = Math.floor((elapsed % 3600) / 60);
  const seconds = elapsed % 60;
  elements.uptime.textContent = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws/overlay`);
  socket.addEventListener('open', () => { elements.connection.textContent = 'LOCAL ONLINE'; });
  socket.addEventListener('message', ({ data }) => { const message = JSON.parse(data); if (message.type === 'stream_state') render(message.data); });
  socket.addEventListener('close', () => { elements.connection.textContent = 'RECONNECTING'; setTimeout(connect, 1500); });
}

const theme = document.querySelector('#brb-theme');
theme.volume = 0.18;
theme.play().catch(() => { elements.connection.title = 'El navegador bloqueó el autoplay; usa la pista como Media Source en OBS.'; });

const messages = ['Searching for streamer...', 'WARNING: return time may vary.', 'ERROR: STREAMER NOT FOUND'];
let run = 0;
function loop() {
  const command = '> execute return_stream.exe'; let character = 0; elements.command.textContent = '';
  const typer = setInterval(() => { elements.command.textContent = command.slice(0, ++character); if (character === command.length) clearInterval(typer); }, 45);
  let progress = 0; const loader = setInterval(() => { progress = Math.min(progress + 2, 100); elements.progress.style.width = `${progress}%`; if (progress === 100) { clearInterval(loader); elements.message.textContent = messages[run++ % messages.length]; setTimeout(loop, 3000); } }, 55);
}

connect(); loop(); setInterval(renderUptime, 1000);
