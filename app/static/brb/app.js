const elements = {
  connection: document.querySelector('#connection'), streamer: document.querySelector('#streamer'),
  status: document.querySelector('#stream-status'), game: document.querySelector('#game'),
  episode: document.querySelector('#episode'), command: document.querySelector('#typed-command'),
  message: document.querySelector('#message'), progress: document.querySelector('#progress-bar'),
  follower: document.querySelector('#last-follower'), subscriber: document.querySelector('#last-subscriber'),
  cheer: document.querySelector('#last-cheer'), raid: document.querySelector('#last-raid'),
};

function eventText(event, text) { return event?.username && event.username !== '—' ? text : 'WAITING FOR SIGNAL'; }

function render(state) {
  elements.streamer.textContent = state.streamer || '—';
  elements.status.textContent = state.status || 'AFK';
  elements.game.textContent = state.game || 'NO GAME SELECTED';
  elements.episode.textContent = state.episode || '—';
  elements.follower.textContent = eventText(state.last_follower, state.last_follower?.username);
  elements.subscriber.textContent = eventText(state.last_subscriber, `${state.last_subscriber?.username || ''} · TIER ${state.last_subscriber?.tier || '—'}`);
  elements.cheer.textContent = eventText(state.last_cheer, `${state.last_cheer?.username || ''} · ${state.last_cheer?.bits || 0} BITS`);
  elements.raid.textContent = eventText(state.last_raid, `${state.last_raid?.username || ''} · ${state.last_raid?.viewers || 0} VIEWERS`);
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

connect(); loop();
