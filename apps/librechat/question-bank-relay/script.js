/*
  "Mesh gradient background" from Animorio · https://animorio.com
  License: free on your own sites and your clients’ sites, paid work included.
  Not for resale, redistribution, templates or code collections · https://animorio.com/en/license/
*/
import { createRelaySequence } from './sequence.js';

export function mountRelay(root, relayScore, gsap, widget = null) {
const BREATH = 10;           /* quanti secondi dura un respiro dei punti */
const BREATH_AMP = 0.009;    /* quanto si muovono i punti quando respirano (0 li ferma) */
const SPRING = 170;          /* quanto è rigida la molla dei punti */
const BOUNCE = 0.38;         /* quanto rimbalzano i punti quando arrivano (0 niente, 0.8 molto) */
const GRID_FADE = 2.6;       /* dopo quanti secondi senza toccare la griglia sfuma via */
const HANDLE = 6;            /* il raggio dei punti in pixel */
const AUTO_DRAG = 8;         /* dopo quanti secondi senza toccare un punto si trascina da solo (0 mai) */

const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
const lifetime = new window.AbortController();
const listen = (target,type,handler) => target.addEventListener(type,handler,{signal:lifetime.signal});
let REDUCED = motion.matches;
const pick = selector => root.querySelector(selector);
const stage = pick('[data-stage]');
const canvas = pick('[data-field]');
const ctx = canvas.getContext('2d');
const playBtn = pick('[data-play]'), slider = pick('[data-time]');
const entering = [...root.querySelectorAll('[data-in]')];
const track = pick('.timeline'), counter = pick('[data-count]'), who = pick('[data-who]');
const phase = pick('[data-phase]'), body = pick('[data-message]'), clock = pick('[data-clock]');
const {roles,beat} = relayScore;
let {messages,edges,duration} = relayScore;
let syncSequence = createRelaySequence(root,relayScore);
const clamp = (value,low,high) => Math.max(low,Math.min(high,value));
const points = roles.map((role,index) => {
  const rest = {x:role.x,y:role.y}, label = document.createElement('button');
  label.type = 'button'; label.className = 'role'; label.dataset.role = role.id;
  label.setAttribute('aria-label',role.label); label.setAttribute('aria-pressed','false');
  pick('[data-roles]').append(label);
  return {role, label, rest, base:{...rest}, pos:{...rest}, vel:{x:0,y:0},
    phase:index*2.3 % (Math.PI*2), grow:REDUCED ? 1 : 0, hover:0, held:0,
    angle:Math.atan2(rest.y-.5,rest.x-.5), radius:Math.hypot(rest.x-.5,rest.y-.5)};
});
const pointFor = new Map(points.map(point => [point.role.id,point]));
const angleDelta = angle => Math.atan2(Math.sin(angle),Math.cos(angle));
for (const [index,point] of points.entries()) {
  point.before = Math.abs(angleDelta(point.angle-points[(index+points.length-1)%points.length].angle))*.43;
  point.after = Math.abs(angleDelta(points[(index+1)%points.length].angle-point.angle))*.43;
}
function bounded(point,horizontal,vertical) {
  const dx=horizontal-.5, dy=vertical-.5;
  const angle=point.angle+clamp(angleDelta(Math.atan2(dy,dx)-point.angle),-point.before,point.after);
  const cosine=Math.cos(angle), sine=Math.sin(angle);
  const maximum=Math.min(point.radius+.13,.42/Math.max(.001,Math.abs(cosine)),.43/Math.max(.001,Math.abs(sine)));
  const radius=clamp(Math.hypot(dx,dy),point.radius*.62,maximum);
  return {x:.5+cosine*radius,y:.5+sine*radius};
}
let selected = '', cursor = 0, playing = !REDUCED && messages.length>0, visible = true, gesture = null;
let strands = [], timing = relayScore.at(0), lastUi = '', lastSecond = -1;
let dirty = true, customLayout = false, savedKey = '', paintedTime = -1;
let ink, paper, accent;
function readTheme() {
  const style=getComputedStyle(root);
  ink=style.color; paper=style.backgroundColor; accent=getComputedStyle(phase).color;
}

let W = 0;
let H = 0;
let dpr = 1;
let gridA = REDUCED ? 1 : 0;      /* how visible the grid is */
let lastTouch = -10;              /* when someone last moved or touched, in seconds */
let now = 0;
let hovered = -1;
let dragging = -1;
let ghost = null;                 /* the timeline of the self-drag */
let ghostCount = 0;
let idleCall = null;
const pointer = { x: 0, y: 0 };

function resize() {
  dirty = true;
  const rect = stage.getBoundingClientRect();
  W = Math.max(1, rect.width);
  H = Math.max(1, rect.height);
  dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(W * dpr);
  canvas.height = Math.round(H * dpr);
  for (const point of points) {
    point.label.textContent = W < 460 ? point.role.short : point.role.label;
    point.textWidth=point.label.offsetWidth; point.textHeight=point.label.offsetHeight;
  }
  readTheme();
}

function paintField() {
  ctx.clearRect(0,0,canvas.width,canvas.height);
  ctx.save(); ctx.beginPath();
  for (const [index,point] of points.entries()) {
    const horizontal=point.pos.x*W*dpr, vertical=point.pos.y*H*dpr;
    if (index===0) ctx.moveTo(horizontal,vertical); else ctx.lineTo(horizontal,vertical);
  }
  ctx.closePath(); ctx.fillStyle=ink; ctx.globalAlpha=.045; ctx.fill();
  ctx.lineWidth=dpr; ctx.strokeStyle=ink; ctx.globalAlpha=.37; ctx.stroke(); ctx.restore();
}

/* ---------------------------------------------------------------- the grid: Catmull-Rom curves through the points */
function curve(list, pen = ctx) {
  const P = list.map((p) => [p.pos.x * W * dpr, p.pos.y * H * dpr]);
  pen.moveTo(P[0][0], P[0][1]);
  for (let i = 0; i < P.length - 1; i++) {
    const p0 = P[i - 1] || P[i];
    const p1 = P[i];
    const p2 = P[i + 1];
    const p3 = P[i + 2] || p2;
    pen.bezierCurveTo(
      p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
      p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6,
      p2[0], p2[1]
    );
  }
}

function onStrand(strand,progress) {
  const scaled=clamp(progress,0,1)*strand.length, index=Math.min(strand.length-1,Math.floor(scaled));
  const part=scaled-index, rest=1-part, segment=strand[index];
  const first=rest**3, second=3*rest*rest*part, third=3*rest*part*part, last=part**3;
  return [first*segment[0]+second*segment[2]+third*segment[4]+last*segment[6],
          first*segment[1]+second*segment[3]+third*segment[5]+last*segment[7]];
}
function inRim(sample) {
  const horizontal=sample[0]/(W*dpr), vertical=sample[1]/(H*dpr);
  let inside=false;
  for (let index=0, previous=points.length-1; index<points.length; previous=index++) {
    const first=points[index].pos, last=points[previous].pos;
    if ((first.y>vertical)!==(last.y>vertical) &&
        horizontal<(last.x-first.x)*(vertical-first.y)/(last.y-first.y)+first.x) inside=!inside;
  }
  return inside;
}
function buildStrand(event) {
  const start=pointFor.get(event.from), end=pointFor.get(event.to);
  const midX=(start.pos.x+end.pos.x)/2+event.bowX, midY=(start.pos.y+end.pos.y)/2+event.bowY;
  let previous, segments=[];
  const pen={
    moveTo(horizontal,vertical) { previous=[horizontal,vertical]; },
    bezierCurveTo(...coords) { segments.push([...previous,...coords]); previous=coords.slice(4); }
  };
  for (const pull of [0,.35,.70,1]) {
    segments=[];
    curve([start,{pos:{x:midX+(.5-midX)*pull,y:midY+(.5-midY)*pull}},end],pen);
    if ([.05,.16,.32,.5,.68,.84,.95].every(amount=>inRim(onStrand(segments,amount)))) break;
  }
  return segments;
}
function strokeStrand(strand) {
  ctx.beginPath(); ctx.moveTo(strand[0][0],strand[0][1]);
  for (const segment of strand) ctx.bezierCurveTo(...segment.slice(2));
  ctx.stroke();
}
function strokeWindow(strand,tail,head) {
  if (head-tail<=.0001) return;
  ctx.beginPath(); ctx.moveTo(...onStrand(strand,tail));
  const steps=Math.max(2,Math.ceil((head-tail)*44));
  for (let sample=1; sample<=steps; sample++) ctx.lineTo(...onStrand(strand,tail+(head-tail)*sample/steps));
  ctx.stroke();
}
function pulse(position,progress) {
  if (progress<=0 || progress>=1) return;
  ctx.save(); ctx.globalAlpha=1-progress; ctx.strokeStyle=accent; ctx.lineWidth=1.6*dpr;
  ctx.beginPath(); ctx.arc(...position,(HANDLE+2+11*progress)*dpr,0,Math.PI*2); ctx.stroke(); ctx.restore();
}
function paintMessage(strand) {
  ctx.save(); ctx.strokeStyle=accent; ctx.fillStyle=accent; ctx.lineCap='round'; ctx.lineJoin='round';
  if (REDUCED) {
    ctx.lineWidth=2*dpr; strokeStrand(strand);
  } else {
    pulse(onStrand(strand,0),timing.send); pulse(onStrand(strand,1),timing.receive);
    ctx.lineWidth=2.5*dpr; strokeWindow(strand,timing.tail,timing.head);
    if (timing.head>0 && timing.head<1) {
      ctx.beginPath(); ctx.arc(...onStrand(strand,timing.head),3.5*dpr,0,Math.PI*2); ctx.fill();
    }
  }
  ctx.restore();
}
function placeLabel(point,placed) {
  const {side}=point.role, width=point.textWidth, height=point.textHeight;
  const horizontal=side.includes('W') ? -width-8 : side.includes('E') ? 8 : -width/2;
  const vertical=side.includes('N') ? -height-5 : side.includes('S') ? 5 : -height/2;
  const left=clamp(point.pos.x*W+horizontal,0,W-width), preferred=clamp(point.pos.y*H+vertical,0,H-height);
  const across=placed.filter(box=>left<box.right+2 && left+width+2>box.left);
  const fits=top=>top>=0 && top+height<=H && across.every(box=>top+height+2<=box.top || top>=box.bottom+2);
  const top=fits(preferred) ? preferred : across.flatMap(box=>[box.top-height-2,box.bottom+2])
    .filter(fits).sort((first,last)=>Math.abs(first-preferred)-Math.abs(last-preferred))[0] ?? preferred;
  placed.push({left,right:left+width,top,bottom:top+height});
  point.label.style.transform=`translate(${left.toFixed(2)}px,${top.toFixed(2)}px)`;
}
function paintGrid() {
  strands=edges.map(buildStrand);
  ctx.save(); ctx.strokeStyle=ink; ctx.lineCap='round'; ctx.lineWidth=dpr;
  for (const [index,strand] of strands.entries()) {
    const event=edges[index], related=selected && (event.from===selected || event.to===selected);
    ctx.globalAlpha=related ? .65 : selected ? .11 : .19+gridA*.22;
    strokeStrand(strand);
  }
  ctx.restore();
  if (timing.event?.edge>=0) paintMessage(strands[timing.event.edge]);
  else if (timing.event && !REDUCED) {
    const {x,y}=pointFor.get(timing.activeRole).pos;
    pulse([x*W*dpr,y*H*dpr],timing.send);
  }

  const placed=[];
  for (const p of points) {
    placeLabel(p,placed);
    const x = p.pos.x * W * dpr;
    const y = p.pos.y * H * dpr;
    const scale = p.grow * (1 + 0.32 * p.hover + 0.12 * p.held);
    if (scale < 0.01) continue;
    const rad = HANDLE * dpr * scale;
    ctx.save();
    ctx.globalAlpha = 1;
    /* the accent ring of the grabbed point */
    if (p.held > 0.01) {
      ctx.beginPath();
      ctx.arc(x, y, rad + 5 * dpr * p.held, 0, Math.PI * 2);
      ctx.strokeStyle = ink;
      ctx.globalAlpha = p.held;
      ctx.lineWidth = 1.5 * dpr;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.shadowColor = 'rgba(21,23,28,0.28)';
    ctx.shadowBlur = (6 + 6 * p.held) * dpr;
    ctx.shadowOffsetY = (1.5 + 2 * p.held) * dpr;
    ctx.beginPath();
    ctx.arc(x, y, rad, 0, Math.PI * 2);
    ctx.fillStyle = paper;
    ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.strokeStyle = ink; ctx.lineWidth = dpr*.9; ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, rad * 0.48, 0, Math.PI * 2);
    ctx.fillStyle = p.role.id===timing.activeRole ? accent : ink;
    ctx.fill();
    ctx.restore();
  }
}

/* ---------------------------------------------------------------- motion */
function step(dt) {
  const k = SPRING;
  const c = 2 * Math.sqrt(k) * (1 - BOUNCE * 0.8);
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    let tx, ty;
    if (i === dragging) {
      const target=bounded(p,pointer.x/W,pointer.y/H);
      tx = target.x; ty = target.y;
    } else {
      const a = REDUCED ? 0 : BREATH_AMP * Math.sin((now / BREATH) * Math.PI * 2 + p.phase);
      const b = REDUCED ? 0 : BREATH_AMP * Math.cos((now / BREATH) * Math.PI * 2 + p.phase * 1.3);
      tx = p.base.x + a; ty = p.base.y + b;
    }
    if (REDUCED) {
      p.pos.x = tx; p.pos.y = ty; p.vel.x = 0; p.vel.y = 0;
    } else {
      p.vel.x += (k * (tx - p.pos.x) - c * p.vel.x) * dt;
      p.vel.y += (k * (ty - p.pos.y) - c * p.vel.y) * dt;
      p.pos.x += p.vel.x * dt;
      p.pos.y += p.vel.y * dt;
    }
    const onRim=bounded(p,p.pos.x,p.pos.y);
    p.pos.x=onRim.x; p.pos.y=onRim.y;
    const ease = 1 - Math.exp(-dt * 14);
    p.hover += ((i === hovered ? 1 : 0) - p.hover) * ease;
    p.held += ((i === dragging ? 1 : 0) - p.held) * ease;
  }
  const busy = dragging >= 0 || (now - lastTouch) < GRID_FADE;
  const target = busy ? 1 : (REDUCED ? 0.55 : 0);
  gridA += (target - gridA) * (1 - Math.exp(-dt * (busy ? 9 : 2.2)));
}

function frame() {
  const elapsed = gsap.ticker.deltaRatio(60) / 60;
  const dt = Math.min(1 / 30, elapsed);
  now = gsap.ticker.time;
  if (!W || !visible || document.hidden || (REDUCED && !playing && !dirty && dragging<0)) return;
  dirty=false;
  if (playing) {
    cursor=Math.min(duration,cursor+Math.min(elapsed,.25));
    if (cursor>=duration) { playing=false; scheduleGhost(); remember(); }
  }
  timing=relayScore.at(cursor);
  step(dt);
  if (ctx) { paintField(); paintGrid(); }
  syncTransport();
}

function timestamp(seconds) {
  return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
}
function syncTransport() {
  const tag=timing.event && cursor===0 && !playing ? '待发' : timing.phase;
  const key=`${timing.index}:${tag}:${playing}:${selected}`;
  if (key!==lastUi) {
    const event=timing.event, sender=pointFor.get(event?.from)?.role.label, receiver=pointFor.get(event?.to)?.role.label;
    const route=!event ? '暂无阶段记录' : sender===receiver ? sender : `${sender} → ${receiver}`;
    const put=(element,value) => { if (element.textContent!==value) element.textContent=value; };
    put(counter,event ? `${String(timing.index+1).padStart(2,'0')} / ${messages.length}` : '');
    put(who,route); put(phase,tag); put(body,event?.text ?? '');
    const action=playing ? '暂停' : event && cursor>=duration ? '重播' : '播放';
    playBtn.dataset.playing=String(playing); playBtn.setAttribute('aria-label',`${action}消息`);
    playBtn.disabled=slider.disabled=!event;
    slider.setAttribute('aria-valuetext',event ? `第 ${timing.index+1} 条，${route}，${tag}` : route);
    stage.dataset.message=String(timing.index+1); stage.dataset.phase=tag;
    for (const point of points) {
      point.label.setAttribute('aria-pressed',String(point.role.id===selected));
      point.label.dataset.tone=point.role.id===event?.from || point.role.id===event?.to || point.role.id===selected ? 'active' : 'quiet';
    }
    syncSequence(timing,cursor>0 || playing,playing && !REDUCED);
    lastUi=key;
  }
  const seconds=cursor>=duration ? Math.ceil(duration) : Math.floor(cursor);
  if (seconds!==lastSecond) { clock.textContent=`${timestamp(seconds)} / ${timestamp(Math.ceil(duration))}`; lastSecond=seconds; }
  if (cursor!==paintedTime) {
    slider.value=String(cursor); const part=duration ? cursor/duration : 0;
    track.style.setProperty('--position',String(part)); track.style.setProperty('--percent',`${part*100}%`);
    paintedTime=cursor;
  }
}
function remember() {
  const api=widget;
  if (typeof api?.setWidgetState!=='function') return;
  const layout=customLayout ? Object.fromEntries(points.map(point=>[point.role.id,[point.base.x,point.base.y]])) : null;
  const state={kind:'mesh-relay',time:cursor,selected,layout}; savedKey=JSON.stringify(state);
  api.setWidgetState({privateContent:state,modelContent:{角色:pointFor.get(selected)?.role.label||null,
    消息:relayScore.at(cursor).event?.text ?? null}}).catch(()=>{});
}
function restore(snapshot) {
  const state=snapshot?.privateContent;
  if (state?.kind!=='mesh-relay' || !Number.isFinite(state.time) || JSON.stringify(state)===savedKey) return;
  savedKey=JSON.stringify(state); stopGhost(); playing=false; cursor=clamp(state.time,0,duration);
  selected=pointFor.has(state.selected) ? state.selected : ''; customLayout=Boolean(state.layout);
  for (const point of points) {
    const pair=state.layout?.[point.role.id];
    const base=Array.isArray(pair) && pair.length===2 && pair.every(Number.isFinite) ? bounded(point,...pair) : point.rest;
    point.base={...base}; point.pos={...base}; point.vel={x:0,y:0};
  }
  timing=relayScore.at(cursor); dirty=true; syncTransport(); scheduleGhost();
}
function seek(time) {
  stopGhost(); playing=false; cursor=clamp(time,0,duration); dirty=true;
  timing=relayScore.at(cursor); syncTransport();
}
function selectRole(index) {
  const id=points[index].role.id;
  if (selected===id) { selected=''; dirty=true; syncTransport(); scheduleGhost(); remember(); return; }
  selected=id;
  let messageIndex=messages.findIndex(event=>event.from===id);
  if (messageIndex<0) messageIndex=messages.findIndex(event=>event.to===id);
  if (messageIndex>=0) seek((messageIndex+.36)*beat);
  else { dirty=true; syncTransport(); }
  remember();
}
function selectStrand(index) {
  const messageIndex=messages.findIndex(event=>event.edge===index);
  if (messageIndex<0) return;
  selected=''; seek(messageIndex*beat); playing=!REDUCED; dirty=true; syncTransport(); remember();
}
function nearestStrand(horizontal,vertical) {
  let closest=-1, best=(8*dpr)**2;
  for (const [index,strand] of strands.entries()) {
    let prior=onStrand(strand,0);
    for (let mark=1;mark<=20;mark++) {
      const next=onStrand(strand,mark/20), dx=next[0]-prior[0], dy=next[1]-prior[1];
      const px=horizontal*dpr-prior[0], py=vertical*dpr-prior[1];
      const at=clamp((px*dx+py*dy)/(dx*dx+dy*dy||1),0,1);
      const distance=(px-at*dx)**2+(py-at*dy)**2;
      if (distance<best) { closest=index; best=distance; }
      prior=next;
    }
  }
  return closest;
}
function setTicks() {
  slider.max=String(duration); const ticks=pick('.ticks'); ticks.replaceChildren();
  for (let index=0;messages.length && index<=messages.length;index++) {
    const tick=document.createElement('i'); tick.style.left=`${index/messages.length*100}%`; ticks.append(tick);
  }
}
setTicks();
playBtn.addEventListener('click',()=>{
  stopGhost(); selected=''; if (cursor>=duration) cursor=0;
  playing=!playing; dirty=true; timing=relayScore.at(cursor); syncTransport(); scheduleGhost(); remember();
});
slider.addEventListener('pointerdown',()=>{ selected=''; seek(cursor); });
slider.addEventListener('input',()=>{ selected=''; seek(slider.valueAsNumber); });
slider.addEventListener('change',remember);
slider.addEventListener('keydown',event=>{
  const step=event.shiftKey ? .10 : beat;
  const jumps={ArrowLeft:-step,ArrowDown:-step,ArrowRight:step,ArrowUp:step,Home:-duration,End:duration};
  if (!(event.key in jumps)) return;
  event.preventDefault(); selected=''; seek(cursor+jumps[event.key]); remember();
});

/* ---------------------------------------------------------------- pointer */
function local(e) {
  const rect = stage.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}
function nearest(x, y) {
  let best = -1;
  let bd = (HANDLE + 16) * (HANDLE + 16);
  points.forEach((p, i) => {
    const dx = p.pos.x * W - x;
    const dy = p.pos.y * H - y;
    const d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = i; }
  });
  return best;
}
function touched() {
  dirty = true;
  lastTouch = gsap.ticker.time;
  stopGhost();
  scheduleGhost();
}

function hitRole(event,position) {
  const id=event.target.closest?.('[data-role]')?.dataset.role;
  return id ? points.indexOf(pointFor.get(id)) : nearest(position.x,position.y);
}
stage.addEventListener('pointermove', (e) => {
  if (!e.isPrimary || (gesture && gesture.pointerId!==e.pointerId)) return;
  if (e.pointerType === 'mouse' || gesture) touched();
  const q=local(e);
  if (gesture) {
    if (Math.hypot(q.x-gesture.start.x,q.y-gesture.start.y)>4) gesture.moved=true;
    if (gesture.index<0 || !gesture.moved) return;
    pointer.x=q.x+gesture.offsetX; pointer.y=q.y+gesture.offsetY;
  }
  if (dragging < 0) {
    hovered = hitRole(e,q);
    canvas.classList.toggle('is-over', hovered >= 0);
  }
});
stage.addEventListener('pointerdown', (e) => {
  if (!e.isPrimary || e.button!==0) return;
  touched();
  const q = local(e);
  const i = hitRole(e,q);
  gesture={pointerId:e.pointerId,index:i,start:q,moved:false,offsetX:0,offsetY:0};
  stage.setPointerCapture(e.pointerId);
  if (i < 0) return;
  pointer.x=points[i].pos.x*W; pointer.y=points[i].pos.y*H;
  gesture.offsetX=pointer.x-q.x; gesture.offsetY=pointer.y-q.y;
  dragging = i;
  hovered = i;
  canvas.classList.add('is-drag');
});
function release(keep = true) {
  if (dragging < 0) return;
  const p = points[dragging];
  if (keep) p.base=bounded(p,pointer.x/W,pointer.y/H);
  dragging = -1;
  canvas.classList.remove('is-drag');
  lastTouch = gsap.ticker.time;
  dirty=true;
}
function endGesture(event) {
  if (!gesture || event.pointerId!==gesture.pointerId) return;
  const interaction=gesture, cancelled=event.type==='pointercancel';
  gesture=null; release(!cancelled && interaction.moved);
  if (!cancelled && interaction.moved && interaction.index>=0) { customLayout=true; remember(); }
  if (!cancelled && !interaction.moved) {
    if (interaction.index>=0) selectRole(interaction.index);
    else {
      const location=local(event), edge=nearestStrand(location.x,location.y);
      if (edge>=0) selectStrand(edge);
      else { selected=''; dirty=true; syncTransport(); remember(); }
    }
  }
  scheduleGhost();
}
stage.addEventListener('pointerup', endGesture);
stage.addEventListener('pointercancel', endGesture);
stage.addEventListener('pointerleave', () => { if (dragging < 0) { hovered = -1; canvas.classList.remove('is-over'); } });

/* keyboard: Tab onto the field, arrows move the chosen point, Enter picks the next one */
canvas.tabIndex = 0;
let chosen = 0;
canvas.addEventListener('focus', () => { hovered = chosen; touched(); });
canvas.addEventListener('blur', () => { hovered = -1; });
function nudge(event,index) {
  const point=points[index], increment=event.shiftKey ? .06 : .02;
  const move={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
  if (!move) return false;
  event.preventDefault(); touched(); customLayout=true;
  point.base=bounded(point,point.base.x+move[0]*increment,point.base.y+move[1]*increment);
  remember(); return true;
}
canvas.addEventListener('keydown', (event) => {
  if (nudge(event,chosen)) return;
  if (event.key==='Enter' || event.key===' ') {
    event.preventDefault(); chosen=(chosen+1)%points.length; hovered=chosen; touched(); selectRole(chosen);
  }
});
for (const [index,point] of points.entries()) {
  point.label.addEventListener('click',event=>{ if (event.detail===0) selectRole(index); });
  point.label.addEventListener('keydown',event=>nudge(event,index));
  point.label.addEventListener('focus',()=>{ chosen=index; hovered=index; touched(); });
}
root.addEventListener('keydown',event=>{
  if (event.key==='Escape') { selected=''; dirty=true; syncTransport(); remember(); }
});

/* ---------------------------------------------------------------- reset */
function resetMesh() {
  points.forEach((p) => { p.base.x = p.rest.x; p.base.y = p.rest.y; });
  lastTouch = gsap.ticker.time;
}

/* ---------------------------------------------------------------- the self-drag when nobody touches */
const GHOST_ORDER = [5, 2, 9, 6];
const GHOST_MOVE = [[.0225,-.025],[.0175,.030],[.0275,-.0175],[-.020,.025]];
function stopGhost() {
  if (ghost) { ghost.kill(); ghost = null; }
  if (idleCall) { idleCall.kill(); idleCall = null; }
  if (dragging >= 0 && ghostHeld) { ghostHeld = false; release(); }
}
let ghostHeld = false;
function scheduleGhost() {
  if (REDUCED || !AUTO_DRAG || playing || selected || customLayout || !visible || document.hidden || gesture) return;
  if (idleCall) idleCall.kill();
  idleCall = gsap.delayedCall(AUTO_DRAG, runGhost);
}
function runGhost() {
  idleCall = null;
  if (dragging >= 0 || playing || selected || customLayout || !visible || document.hidden || gesture) return;
  if (ghostCount > 0 && ghostCount % GHOST_ORDER.length === 0) {
    /* after a round, the mesh springs back to where it was born */
    ghostCount++;
    resetMesh();
    lastTouch = gsap.ticker.time;
    idleCall = gsap.delayedCall(AUTO_DRAG + 0.6, runGhost);
    return;
  }
  const slot = ghostCount % GHOST_ORDER.length;
  const i = GHOST_ORDER[slot];
  const p = points[i];
  const from = { x: p.pos.x * W, y: p.pos.y * H };
  const to = {
    x: Math.min(0.98, Math.max(0.02, p.base.x + GHOST_MOVE[slot][0])) * W,
    y: Math.min(0.98, Math.max(0.02, p.base.y + GHOST_MOVE[slot][1])) * H
  };
  const proxy = { x: from.x, y: from.y };
  ghostCount++;
  ghost = gsap.timeline({ onComplete: () => { ghost = null; idleCall = gsap.delayedCall(AUTO_DRAG, runGhost); } });
  ghost
    .call(() => { hovered = i; lastTouch = gsap.ticker.time; }, null, 0)
    .call(() => { pointer.x = from.x; pointer.y = from.y; dragging = i; ghostHeld = true; }, null, 0.35)
    .to(proxy, {
      x: to.x, y: to.y, duration: 1.3, ease: 'power2.inOut',
      onUpdate: () => { pointer.x = proxy.x; pointer.y = proxy.y; lastTouch = gsap.ticker.time; }
    }, 0.4)
    .call(() => { ghostHeld = false; release(); }, null, 1.95)
    .call(() => { hovered = -1; }, null, 2.3);
}

/* ---------------------------------------------------------------- start */
resize();
restore(widget?.widgetState);
timing=relayScore.at(cursor); syncTransport();
if (widget) listen(window,'openai:set_globals',event=>restore(event.detail?.globals?.widgetState));
listen(window,'resize',resize);
const sizeObserver=window.ResizeObserver && new window.ResizeObserver(resize);
sizeObserver?.observe(stage);
document.fonts?.ready.then(()=>{ if (!lifetime.signal.aborted) resize(); });
listen(window.matchMedia('(prefers-color-scheme: dark)'),'change',()=>{readTheme(); dirty=true;});
const themeObserver=new MutationObserver(()=>{readTheme(); dirty=true;});
themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['class','style','data-theme']});
function visibilityChanged() {
  stopGhost(); if (visible && !document.hidden) { dirty=true; scheduleGhost(); }
}
listen(document,'visibilitychange',visibilityChanged);
const viewObserver=window.IntersectionObserver && new window.IntersectionObserver(entries=>{ visible=entries[0].isIntersecting; visibilityChanged(); });
viewObserver?.observe(root);
listen(motion,'change',event=>{
  REDUCED=event.matches; stopGhost(); dirty=true;
  if (REDUCED) { playing=false; for (const point of points) point.grow=1; syncTransport(); }
  else scheduleGhost();
});
gsap.ticker.add(frame);

if (REDUCED) {
  gsap.set(entering, { opacity: 1 });
} else {
  gsap.from(entering, { y: 14, opacity: 0, duration: 0.9, ease: 'power3.out', stagger: 0.08, delay: 0.15 });
  /* the grid draws itself in, the points pop one by one, then everything rests */
  lastTouch = 1.6;
  points.forEach((p, i) => {
    gsap.to(p, { grow: 1, duration: 0.6, ease: 'back.out(2.2)', delay: 0.35 + i * 0.045 });
  });
  scheduleGhost();
}
return {
  update(next) {
    const previous=timing, wasAtEnd=cursor===duration && duration>0;
    relayScore=next; ({messages,edges,duration}=next);
    const index=messages.findIndex(event=>event.key===previous.event?.key);
    if (index>=0) cursor=wasAtEnd && index===messages.length-1 ? duration : (index+Math.min(previous.part,.999999))*beat;
    else cursor=clamp(cursor,0,duration);
    if (!duration) playing=false;
    syncSequence=createRelaySequence(root,next); setTicks();
    timing=next.at(cursor); lastUi=''; lastSecond=-1; paintedTime=-1; dirty=true; syncTransport();
  },
  destroy() {
    lifetime.abort(); stopGhost(); gsap.ticker.remove(frame);
    gsap.killTweensOf(entering); gsap.killTweensOf(points);
    sizeObserver?.disconnect(); viewObserver?.disconnect(); themeObserver.disconnect();
  },
};
}
