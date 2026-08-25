const editor = document.querySelector('#team-editor');
const tokenInput = document.querySelector('#admin-token');
const statusLine = document.querySelector('#status');
let team = { members: [] };

function setStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.style.color = isError ? '#ff8989' : '#eaff91';
}

function headers() {
  return { 'Content-Type': 'application/json', 'X-Overlay-Admin-Token': tokenInput.value };
}

async function request(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || 'La solicitud falló.');
  return payload;
}

function memberAt(slot) { return team.members.find((member) => member.slot === slot); }

function preview(member) {
  const node = document.createElement('div');
  node.className = 'preview';
  if (!member) { node.textContent = 'Sin Pokémon seleccionado.'; return node; }
  const image = document.createElement('img'); image.src = member.sprite_url || ''; image.alt = member.display_name || member.pokemon;
  const text = document.createElement('div'); const name = document.createElement('strong'); name.textContent = member.display_name || member.pokemon;
  const details = document.createElement('small'); details.textContent = (member.types || []).join(' · ');
  text.append(name, details); node.append(image, text); return node;
}

function makeSlot(slot) {
  const existing = memberAt(slot);
  const card = document.createElement('article'); card.className = 'slot'; card.dataset.slot = slot;
  const title = document.createElement('h2'); title.textContent = `Espacio ${slot}`;
  const row = document.createElement('div'); row.className = 'search-row';
  const search = document.createElement('input'); search.placeholder = 'Busca: pikachu'; search.value = existing?.pokemon_name || '';
  const searchButton = document.createElement('button'); searchButton.type = 'button'; searchButton.textContent = 'Buscar';
  row.append(search, searchButton);
  const results = document.createElement('div'); results.className = 'results';
  const previewBox = preview(existing); previewBox.classList.add('selected-preview');
  const nickname = document.createElement('input'); nickname.placeholder = 'Apodo opcional'; nickname.maxLength = 32; nickname.value = existing?.nickname || '';
  card.dataset.pokemon = existing?.pokemon_name || '';
  const actions = document.createElement('div'); actions.className = 'actions';
  const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Guardar';
  const clear = document.createElement('button'); clear.type = 'button'; clear.className = 'danger'; clear.textContent = 'Vaciar';
  actions.append(save, clear); card.append(title, row, results, previewBox, nickname, actions);

  async function searchPokemon() {
    try {
      const matches = await request(`/api/pokemon/search?q=${encodeURIComponent(search.value)}`, { method: 'GET' });
      results.replaceChildren();
      if (!matches.length) { results.textContent = 'Sin coincidencias.'; return; }
      for (const match of matches) {
        const choice = document.createElement('button'); choice.type = 'button'; choice.textContent = match.name;
        choice.addEventListener('click', () => { card.dataset.pokemon = match.name; search.value = match.name; results.replaceChildren(); setStatus(`${match.name} seleccionado en el espacio ${slot}.`); });
        results.append(choice);
      }
    } catch (error) { setStatus(error.message, true); }
  }
  searchButton.addEventListener('click', searchPokemon);
  search.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); searchPokemon(); } });
  save.addEventListener('click', async () => {
    if (!card.dataset.pokemon) { setStatus('Busca y selecciona un Pokémon antes de guardar.', true); return; }
    try {
      setStatus('Consultando PokéAPI y guardando el sprite…');
      team = await request(`/api/pokemon/team/${slot}`, { method: 'PUT', body: JSON.stringify({ pokemon: card.dataset.pokemon, nickname: nickname.value }) });
      render(); setStatus(`Espacio ${slot} guardado.`);
    } catch (error) { setStatus(error.message, true); }
  });
  clear.addEventListener('click', async () => {
    try { team = await request(`/api/pokemon/team/${slot}`, { method: 'DELETE' }); render(); setStatus(`Espacio ${slot} vaciado.`); }
    catch (error) { setStatus(error.message, true); }
  });
  return card;
}

function render() { editor.replaceChildren(...[1, 2, 3, 4, 5, 6].map(makeSlot)); }

async function load() {
  try { team = await fetch('/api/pokemon/team').then((response) => response.json()); render(); }
  catch (error) { setStatus('No se pudo cargar el equipo.', true); }
}

load();
