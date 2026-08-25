const elements = {
  streamer: document.querySelector('#streamer'), game: document.querySelector('#game'),
  viewers: document.querySelector('#viewer-count'), uptime: document.querySelector('#stream-uptime'),
  follower: document.querySelector('#last-follower'), subscriber: document.querySelector('#last-subscriber'),
  cheer: document.querySelector('#last-cheer'), raid: document.querySelector('#last-raid'),
};

let currentState = {};

function textOrDash(value) { return value && value !== '—' ? value : '—'; }

function render(state) {
  currentState = state;
  elements.streamer.textContent = textOrDash(state.streamer);
  elements.game.textContent = textOrDash(state.game);
  elements.viewers.textContent = state.is_live ? String(state.viewer_count ?? 0) : '0';
  elements.follower.textContent = textOrDash(state.last_follower?.username);
  elements.subscriber.textContent = state.last_subscriber?.username && state.last_subscriber.username !== '—'
    ? `${state.last_subscriber.username} · T${String(state.last_subscriber.tier || '—').replace('000', '')}` : '—';
  elements.cheer.textContent = state.last_cheer?.username && state.last_cheer.username !== '—'
    ? `${state.last_cheer.username} · ${state.last_cheer.bits || 0}` : '—';
  elements.raid.textContent = state.last_raid?.username && state.last_raid.username !== '—'
    ? `${state.last_raid.username} · ${state.last_raid.viewers || 0}` : '—';
  renderUptime();
}

function renderUptime() {
  if (!currentState.is_live || !currentState.stream_started_at) {
    elements.uptime.textContent = 'OFFLINE';
    return;
  }
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(currentState.stream_started_at).getTime()) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  elements.uptime.textContent = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws/overlay`);
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    if (message.type === 'stream_state') render(message.data);
  });
  socket.addEventListener('close', () => setTimeout(connect, 1500));
}

connect();
setInterval(renderUptime, 1000);
