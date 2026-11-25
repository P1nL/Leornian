export function createRelaySequence(root,score) {
  const viewport=root.querySelector('[data-seq-window]');
  const headers=root.querySelector('[data-seq-heads]');
  const guides=root.querySelector('[data-seq-guides]');
  const list=root.querySelector('[data-seq-list]');
  headers.replaceChildren(); guides.replaceChildren(); list.replaceChildren();
  const roleById=new Map(score.roles.map(role=>[role.id,role]));
  const order=['author','blind','sandbox','scope','level','technical','wording','safety','stress','release'];
  const columns=new Map();
  for (const [index,id] of order.entries()) {
    const role=roleById.get(id);
    const heading=document.createElement('span'), name=document.createElement('span'), guide=document.createElement('span');
    heading.setAttribute('role','listitem'); heading.setAttribute('aria-label',role.label);
    name.textContent=role.short.replace(/审$/u,'');
    heading.append(name); headers.append(heading); guides.append(guide);
    columns.set(id,{heading,guide,center:100*(index+.5)/order.length});
  }

  const rows=score.messages.map(event=>{
    const start=columns.get(event.from).center, end=columns.get(event.to).center;
    const row=document.createElement('li'), caption=document.createElement('span');
    const path=document.createElement('span'), shaft=document.createElement('span');
    row.className='seq-row'; caption.className='seq-action'; caption.textContent=event.action;
    const sender=roleById.get(event.from).label, receiver=roleById.get(event.to).label;
    row.setAttribute('aria-label',`${event.action}：${start===end ? sender : `${sender}到${receiver}`}`);
    path.className='seq-path'; path.setAttribute('aria-hidden','true');
    shaft.className='seq-shaft'; shaft.style.left=`${Math.min(start,end)}%`; shaft.style.width=`${Math.abs(end-start)}%`;
    if (start>end) shaft.classList.add('reverse');
    if (start===end) shaft.classList.add('local');
    path.append(shaft); row.append(caption,path);
    return row;
  });

  let shown=0, active='';
  return function syncSequence(timing,started,smooth) {
    const count=started ? timing.index+1 : 0;
    if (count!==shown) {
      const previous=shown;
      if (previous) rows[previous-1].removeAttribute('aria-current');
      while (shown>count) rows[--shown].remove();
      if (shown<count) {
        const added=document.createDocumentFragment();
        while (shown<count) added.append(rows[shown++]);
        list.append(added);
      }
      if (count) rows[count-1].setAttribute('aria-current','step');
      const bottom=Math.max(0,viewport.scrollHeight-viewport.clientHeight);
      if (smooth && count===previous+1 && bottom>0 && viewport.scrollTo) viewport.scrollTo({top:bottom,behavior:'smooth'});
      else viewport.scrollTop=bottom;
    }
    const next=started ? timing.activeRole : '';
    if (next===active) return;
    if (active) {
      columns.get(active).heading.removeAttribute('aria-current');
      columns.get(active).guide.classList.remove('executing');
    }
    if (next) {
      columns.get(next).heading.setAttribute('aria-current','true');
      columns.get(next).guide.classList.add('executing');
    }
    active=next;
  };
}
