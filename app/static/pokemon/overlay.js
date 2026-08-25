const party = document.querySelector('#pokemon-party');

function render(team) {
  party.replaceChildren();
  for (const member of team.members || []) {
    const card = document.createElement('article');
    card.className = 'pokemon-card';
    const sprite = document.createElement('img');
    sprite.src = member.sprite_url;
    sprite.alt = member.display_name;
    const info = document.createElement('div');
    info.className = 'pokemon-info';
    const name = document.createElement('span');
    name.className = 'pokemon-name';
    name.textContent = member.display_name;
    const nickname = document.createElement('span');
    nickname.className = 'pokemon-nickname';
    nickname.textContent = member.nickname || member.pokemon_name;
    const types = document.createElement('span');
    types.className = 'pokemon-types';
    types.textContent = member.types.join(' · ');
    info.append(name, nickname, types);
    card.append(sprite, info);
    party.append(card);
  }
}

async function load() {
  try {
    const response = await fetch('/api/pokemon/team');
    if (response.ok) render(await response.json());
  } catch (_) { /* The WebSocket will retry independently. */ }
}

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const socket = new WebSocket(`${protocol}://${location.host}/ws/overlay`);
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    if (message.type === 'pokemon_team') render(message.data);
  });
  socket.addEventListener('close', () => setTimeout(connect, 1500));
}

load();
connect();
