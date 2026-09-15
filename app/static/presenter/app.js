(() => {
  'use strict';

  const query = new URLSearchParams(window.location.search);
  const modules = ['intro', 'community', 'tloz', 'cta'];
  const labels = { intro: 'IDENTIDAD', community: 'COMUNIDAD', tloz: 'PROYECTO TLOZ', cta: 'CIERRE / CTA' };
  const allowedCamera = new Set(['left', 'right', 'none']);
  const queryCamera = allowedCamera.has(query.get('camera')) ? query.get('camera') : 'right';
  const queryMode = query.get('mode') === 'chat' ? 'chat' : 'trailer';
  const localDurationMs = 15_000;
  const root = document.querySelector('#presenter');
  const elements = {
    connection: document.querySelector('#connection'), channelName: document.querySelector('#channel-name'),
    streamStatus: document.querySelector('#stream-status'), liveStatus: document.querySelector('#live-status'),
    streamCategory: document.querySelector('#stream-category'), viewerCount: document.querySelector('#viewer-count'),
    communitySummary: document.querySelector('#community-summary'), communityCards: document.querySelector('#community-cards'),
    tlozTitle: document.querySelector('#tloz-title'), tlozSummary: document.querySelector('#tloz-summary'),
    tlozTimeline: document.querySelector('#tloz-timeline'), schedule: document.querySelector('#schedule'),
    moduleIndicator: document.querySelector('#module-indicator'), modeIndicator: document.querySelector('#mode-indicator'),
  };
  const state = { stream: null, dashboard: null, tloz: null, remote: null, activeIndex: 0, interval: null, timeout: null };

  function text(value, fallback = '—', limit = 160) {
    if (typeof value !== 'string' && typeof value !== 'number') return fallback;
    const cleaned = String(value).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, limit);
    return cleaned || fallback;
  }

  function presentationText(name, fallback, limit) {
    const remoteValue = state.remote?.remote_active ? state.remote[name] : '';
    return text(remoteValue || query.get(name), fallback, limit);
  }

  function setText(element, value, fallback, limit) { element.textContent = text(value, fallback, limit); }

  function applyPresentationFrame() {
    const camera = state.remote?.remote_active ? state.remote.camera : queryCamera;
    root.classList.remove('camera-right', 'camera-left', 'camera-none', 'mode-trailer', 'mode-chat', 'remote-control');
    root.classList.add(`camera-${camera}`, `mode-${queryMode}`);
    if (state.remote?.remote_active) root.classList.add('remote-control');
    elements.schedule.textContent = presentationText('schedule', 'Sígueme para saber cuándo continuamos.', 120);
    elements.modeIndicator.textContent = state.remote?.remote_active
      ? (state.remote.auto_rotate ? `CONTROL REMOTO · AUTO ${state.remote.duration_seconds}s` : 'CONTROL REMOTO · MANUAL')
      : (queryMode === 'trailer' ? 'TRAILER · 60s' : 'CHAT · TECLAS 1–4 / ← →');
  }

  function renderStream(stream) {
    state.stream = stream || null;
    setText(elements.channelName, presentationText('channel_name', stream?.streamer || 'STREAMER', 48), 'STREAMER', 48);
    setText(elements.streamStatus, stream?.title, stream?.is_live ? 'En directo ahora.' : 'Preparando el próximo directo.', 150);
    setText(elements.liveStatus, stream?.is_live ? 'EN VIVO' : 'AFK', 'AFK', 16);
    setText(elements.streamCategory, stream?.category || stream?.game, 'SIN CATEGORÍA', 64);
    elements.viewerCount.textContent = stream?.is_live ? String(Number(stream.viewer_count || 0)) : '—';
  }

  function makeCard(title, detail) {
    const card = document.createElement('article'); card.className = 'data-card';
    const heading = document.createElement('strong'); const description = document.createElement('span');
    heading.textContent = text(title, 'ACTIVIDAD', 80); description.textContent = text(detail, 'En preparación.', 150);
    card.append(heading, description); return card;
  }

  function renderDashboard(dashboard) {
    state.dashboard = dashboard || null; elements.communityCards.replaceChildren();
    const cards = []; const quest = dashboard?.quests?.[0]; const event = dashboard?.user_log?.[0]; const leader = dashboard?.season?.leaders?.[0];
    if (quest) cards.push(makeCard(quest.name, quest.description || `${quest.completions || 0} completadas`));
    if (event) cards.push(makeCard(event.title || event.display_name, event.detail || 'Actividad reciente'));
    if (leader) cards.push(makeCard(`TEMPORADA · ${leader.display_name}`, `${leader.season_xp || 0} XP · ${leader.missions_completed || 0} misiones`));
    if (!cards.length) { elements.communitySummary.textContent = 'La comunidad tendrá aquí sus misiones y últimos logros.'; cards.push(makeCard('COMMUNITY LINK', 'El progreso compartido aparece cuando haya actividad pública.')); }
    else elements.communitySummary.textContent = `${cards.length} señal${cards.length === 1 ? '' : 'es'} pública${cards.length === 1 ? '' : 's'} del canal.`;
    elements.communityCards.append(...cards.slice(0, 2));
  }

  function renderTloz(tloz) {
    state.tloz = tloz || null; elements.tlozTimeline.replaceChildren();
    if (!tloz?.active || !tloz.game) { elements.tlozTitle.textContent = 'Archivo de aventura'; elements.tlozSummary.textContent = 'La cronología aparecerá cuando el proyecto TLOZ esté activo.'; return; }
    setText(elements.tlozTitle, tloz.game.title, 'The Legend of Zelda', 130);
    const zone = text(tloz.current_zone?.name, '', 100); const objective = text(tloz.current_objective?.title, '', 150);
    elements.tlozSummary.textContent = [zone, objective].filter(Boolean).join(' · ') || 'Explorando el siguiente capítulo.';
    (tloz.timeline || []).slice(0, 7).forEach((entry) => { const item = document.createElement('li'); item.textContent = text(entry.title, 'ARCHIVO', 70); if (entry.current) item.classList.add('current'); elements.tlozTimeline.append(item); });
  }

  function showModule(index) {
    state.activeIndex = (index + modules.length) % modules.length; const current = modules[state.activeIndex];
    document.querySelectorAll('.module').forEach((module) => { const active = module.dataset.module === current; module.hidden = !active; module.classList.toggle('active', active); });
    elements.moduleIndicator.textContent = `${String(state.activeIndex + 1).padStart(2, '0')} / 04 · ${labels[current]}`;
  }
  function clearRotation() { if (state.interval) window.clearInterval(state.interval); if (state.timeout) window.clearTimeout(state.timeout); state.interval = null; state.timeout = null; }
  function startLocalTrailer() { clearRotation(); showModule(0); state.interval = window.setInterval(() => showModule(state.activeIndex + 1), localDurationMs); }
  function remoteModuleIndex(control) {
    const start = modules.indexOf(control.active_module);
    if (!control.auto_rotate || !control.rotation_started_at) return start;
    const elapsed = Math.max(0, Date.now() - Date.parse(control.rotation_started_at));
    return (start + Math.floor(elapsed / (control.duration_seconds * 1000))) % modules.length;
  }
  function startRemoteRotation(control) {
    clearRotation(); showModule(remoteModuleIndex(control)); if (!control.auto_rotate) return;
    const elapsed = Math.max(0, Date.now() - Date.parse(control.rotation_started_at)); const durationMs = control.duration_seconds * 1000; const remaining = durationMs - (elapsed % durationMs);
    state.timeout = window.setTimeout(() => { showModule(state.activeIndex + 1); state.interval = window.setInterval(() => showModule(state.activeIndex + 1), durationMs); }, remaining);
  }
  function applyRemoteControl(control) { if (!control?.remote_active) return; state.remote = control; applyPresentationFrame(); renderStream(state.stream); startRemoteRotation(control); }

  async function fetchJson(url) { const response = await fetch(url, { cache: 'no-store' }); if (!response.ok) throw new Error(`${url} unavailable`); return response.json(); }
  async function loadPublicData() {
    const [stream, dashboard, tloz] = await Promise.allSettled([fetchJson('/api/state'), fetchJson('/api/game/community-dashboard'), fetchJson('/api/tloz/current')]);
    if (stream.status === 'fulfilled') renderStream(stream.value); if (dashboard.status === 'fulfilled') renderDashboard(dashboard.value); else renderDashboard(null); if (tloz.status === 'fulfilled') renderTloz(tloz.value); else renderTloz(null);
  }
  function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'; const socket = new WebSocket(`${protocol}://${window.location.host}/ws/overlay`);
    socket.addEventListener('open', () => { elements.connection.textContent = 'LOCAL ONLINE'; elements.connection.classList.add('online'); });
    socket.addEventListener('message', ({ data }) => { const message = JSON.parse(data); if (message.type === 'stream_state') renderStream(message.data); if (message.type === 'tloz.state') renderTloz(message.data); if (message.type === 'presenter.control') applyRemoteControl(message.data); if (message.type === 'game.community.event' || message.type === 'game.community.refresh' || message.type === 'game.community.snapshot') fetchJson('/api/game/community-dashboard').then(renderDashboard).catch(() => renderDashboard(null)); });
    socket.addEventListener('close', () => { elements.connection.textContent = 'RECONNECTING'; elements.connection.classList.remove('online'); window.setTimeout(connect, 1_500); });
  }

  applyPresentationFrame(); renderDashboard(null); renderTloz(null); loadPublicData(); connect();
  if (queryMode === 'trailer') startLocalTrailer(); else showModule(0);
  window.addEventListener('keydown', (event) => { if (queryMode !== 'chat') return; if (event.key === 'ArrowRight') { event.preventDefault(); showModule(state.activeIndex + 1); } if (event.key === 'ArrowLeft') { event.preventDefault(); showModule(state.activeIndex - 1); } if (/^[1-4]$/.test(event.key)) showModule(Number(event.key) - 1); });
})();
