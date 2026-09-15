const root=document.querySelector('#overlay');
const view={title:document.querySelector('#game-title'),zone:document.querySelector('#zone'),objective:document.querySelector('#objective'),console:document.querySelector('#console'),special:document.querySelector('#special'),timeline:document.querySelector('#timeline')};
const query=new URLSearchParams(location.search),positions=new Set(['top-left','top-right','bottom-left','bottom-right']);
const position=positions.has(query.get('position'))?query.get('position'):'bottom-left';
const requestedMode=query.get('mode');
const mode=requestedMode==='minimal'?'minimal':requestedMode==='timeline'?'timeline':'compact';
const cycleEnabled=query.get('cycle')==='timeline'&&mode!=='timeline';
const boundedSeconds=(value,fallback,min,max)=>{const parsed=Number.parseInt(value||'',10);return Number.isFinite(parsed)?Math.max(min,Math.min(max,parsed)):fallback};
const cycleEveryMs=boundedSeconds(query.get('cycle_every'),60,30,300)*1000;
const cycleForMs=boundedSeconds(query.get('cycle_for'),10,5,20)*1000;
let currentLayout='',showingTimeline=false,cycleTimer=null,returnTimer=null;
function clearCycle(){clearTimeout(cycleTimer);clearTimeout(returnTimer);cycleTimer=null;returnTimer=null;showingTimeline=false}
function applyPresentation(){root.classList.toggle('show-timeline',mode==='timeline'||showingTimeline)}
function scheduleCycle(){clearTimeout(cycleTimer);clearTimeout(returnTimer);if(currentLayout!=='16_9'||!cycleEnabled||root.hidden)return;cycleTimer=setTimeout(()=>{showingTimeline=true;applyPresentation();returnTimer=setTimeout(()=>{showingTimeline=false;applyPresentation();scheduleCycle()},cycleForMs)},cycleEveryMs)}
function render(data){root.hidden=!data.active;if(!data.active){clearCycle();currentLayout='';return}const layout=data.game.layout_key;if(layout!==currentLayout){clearCycle();currentLayout=layout}root.className=`layout-${layout} position-${position} mode-${mode}`;view.title.textContent=data.game.title;view.zone.textContent=`Zona: ${data.current_zone?.name||'sin marcar'}`;view.objective.textContent=`Objetivo: ${data.current_objective?.title||'sin marcar'}`;view.console.textContent=`Consola: ${data.console_name||'sin marcar'}`;view.special.hidden=!data.special_state;view.special.textContent=data.special_state?`Estado: ${data.special_state}`:'';view.timeline.replaceChildren();for(const entry of data.timeline){const item=document.createElement('li');item.textContent=entry.title;item.className=entry.current?'current':'';view.timeline.append(item)}applyPresentation();if(cycleEnabled&&layout==='16_9'&&!cycleTimer&&!returnTimer)scheduleCycle()}
async function refresh(){try{const res=await fetch('/api/tloz/current');if(res.ok)render(await res.json())}catch{}}
function connect(){const protocol=location.protocol==='https:'?'wss':'ws';const socket=new WebSocket(`${protocol}://${location.host}/ws/overlay`);socket.onmessage=event=>{const message=JSON.parse(event.data);if(message.type==='tloz.state')render(message.data)};socket.onclose=()=>setTimeout(connect,1500)}
connect();refresh();setInterval(refresh,60000);
