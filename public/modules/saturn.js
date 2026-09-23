// Persistent scene: data refreshes update satellites without restarting their orbits.
// Visual direction: nebula-ui's warm planetary light, dust and inclined ellipses.
const SaturnScene = (() => {
  let host, scene, satellites = [], signature = '', raf = 0, elapsed = 0, last = 0;
  let visible = false, paused = false, hovered = false, focused = false;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const colors = ['#80d9d1', '#e9bd83', '#91b3f5', '#cfabed', '#efabab'];
  function frame(now) {
    raf = 0;
    if (last) elapsed += Math.min((now-last)/1000, .05);
    last = now;
    paint();
    if (canMove()) raf = requestAnimationFrame(frame);
  }
  function canMove() { return visible && !document.hidden && !paused && !hovered && !focused && !reduced.matches; }
  function color(index) { return colors[index % colors.length]; }
  function schedule() {
    cancelAnimationFrame(raf); raf = 0; last = 0;
    if (scene) scene.classList.toggle('is-still', !canMove());
    if (canMove()) raf = requestAnimationFrame(frame);
  }
  function paint() {
    const count = satellites.length;
    // left/top animati ogni frame forzano layout reflow; transform è compositato dalla GPU
    // e non lo tocca — stesso posizionamento, letto in translate() invece che riscritto in
    // left/top percentuale (audit 2026-09-18). left:50%/top:50% ora fissi via CSS, il
    // punto orbitale diventa un secondo translate in px, misurato sul contenitore reale.
    const rect = scene ? scene.getBoundingClientRect() : null;
    const cw = rect?.width || 600, ch = rect?.height || 360;
    satellites.forEach((node,i) => {
      const angle = i*Math.PI*2/Math.max(count,1) + .35 + elapsed*(.10-i*.006);
      const rx = 192 + (i%3)*21, ry = 78 + (i%3)*16;
      const x = Math.cos(angle)*rx, y = Math.sin(angle)*ry, tilt = -Math.PI/20;
      const px = x*Math.cos(tilt)-y*Math.sin(tilt), py=x*Math.sin(tilt)+y*Math.cos(tilt);
      const depth = (1+Math.sin(angle)*.09).toFixed(3);
      const offX = (px/6/100*cw).toFixed(2), offY = (py/3.6/100*ch).toFixed(2);
      node.style.transform = `translate(-50%,-50%) translate(${offX}px,${offY}px) scale(${depth})`;
      node.style.zIndex = Math.sin(angle)<0?'2':'6';
    });
  }
  function mount(el) {
    host=el; host.classList.add('saturn-system');
    host.innerHTML = `<div class="saturn-toolbar"><span>Sistema orbitale</span><button type="button" class="saturn-motion" aria-pressed="false" aria-label="Metti in pausa le animazioni">Ⅱ <span>Pausa</span></button></div>
      <div class="saturn-universe" role="group" aria-label="Strategie abilitate in orbita attorno a Saturno">
        <svg class="saturn-cosmos" viewBox="0 0 600 360" aria-hidden="true"><defs>
          <radialGradient id="cosmic-haze"><stop stop-color="#557087" stop-opacity=".23"/><stop offset="1" stop-color="#122230" stop-opacity="0"/></radialGradient>
        </defs><ellipse cx="300" cy="180" rx="265" ry="148" fill="url(#cosmic-haze)"/>
        <g class="saturn-tracks" transform="rotate(-9 300 180)">${[0,1,2].map(i=>`<ellipse cx="300" cy="180" rx="${192+i*21}" ry="${78+i*16}"/>`).join('')}</g>
        <g class="saturn-starlight">${Array.from({length:68},(_,i)=>`<circle cx="${(i*137.507+17)%590+5}" cy="${(i*i*23.37+11)%346+7}" r="${i%11===0?1.2:.55}" opacity="${.16+(i%5)*.12}"/>`).join('')}</g></svg>
        <div class="saturn-core" aria-hidden="true"><svg viewBox="0 0 300 220"><defs>
          <radialGradient id="ss-light" cx="24%" cy="19%" r="88%"><stop stop-color="#f9e3ba"/><stop offset=".4" stop-color="#cfad79"/><stop offset=".72" stop-color="#7a654b"/><stop offset="1" stop-color="#131d2a"/></radialGradient>
          <linearGradient id="ss-ring"><stop stop-color="#7a7775" stop-opacity=".35"/><stop offset=".35" stop-color="#f4dfb2"/><stop offset=".68" stop-color="#ccb38d" stop-opacity=".75"/><stop offset="1" stop-color="#8796a8" stop-opacity=".25"/></linearGradient>
          <radialGradient id="ss-shadow" cx="20%" cy="18%" r="85%"><stop offset=".2" stop-color="#fff0d5" stop-opacity=".12"/><stop offset=".6" stop-color="#302d30" stop-opacity="0"/><stop offset="1" stop-color="#050b15" stop-opacity=".95"/></radialGradient>
          <clipPath id="ss-disc"><circle cx="150" cy="110" r="49"/></clipPath>
        </defs><g transform="rotate(-21 150 110)">
          <g class="saturn-ring-back" fill="none" stroke="url(#ss-ring)"><ellipse cx="150" cy="110" rx="114" ry="33" stroke-width="13"/><ellipse cx="150" cy="110" rx="126" ry="37" stroke-width="3"/><ellipse cx="150" cy="110" rx="102" ry="29" stroke-width="5" opacity=".45"/></g>
          <circle cx="150" cy="110" r="49" fill="url(#ss-light)"/>
          <g clip-path="url(#ss-disc)" class="saturn-clouds" fill="none" stroke-linecap="round">
            <path d="M86 81 Q145 98 214 81 M86 91 Q144 107 214 90 M87 116 Q150 133 213 115 M87 134 Q151 147 214 131" stroke="#e5c89c" stroke-width="5" opacity=".4"/>
            <path d="M86 86 Q145 103 214 86 M86 105 Q145 124 214 104 M86 140 Q148 152 214 140" stroke="#77634e" stroke-width="3" opacity=".37"/>
          </g><circle cx="150" cy="110" r="49" fill="url(#ss-shadow)"/>
          <g fill="none" stroke="url(#ss-ring)"><path d="M36 110 A114 33 0 0 0 264 110" stroke-width="13"/><path d="M24 110 A126 37 0 0 0 276 110" stroke-width="3"/><path d="M48 110 A102 29 0 0 0 252 110" stroke-width="5" opacity=".45"/></g>
          <path d="M36 111 A114 33 0 0 0 264 111" fill="none" stroke="#fff0cd" stroke-width=".8" opacity=".7"/>
        </g></svg></div><div class="saturn-satellites"></div>
      </div><div class="saturn-caption"><span class="saturn-beacon"></span><span data-saturn-count></span><span class="saturn-hint">Seleziona un pianeta per esplorare la strategia</span></div>`;
    scene=host.querySelector('.saturn-universe');
    const control=host.querySelector('.saturn-motion');
    control.onclick=()=>{paused=!paused;control.setAttribute('aria-pressed',String(paused));control.setAttribute('aria-label',paused?'Riprendi le animazioni':'Metti in pausa le animazioni');control.innerHTML=paused?'▷ <span>Riprendi</span>':'Ⅱ <span>Pausa</span>';window.NebulaSky?.setPaused(paused);schedule();};
    scene.onpointerenter=()=>{hovered=true;schedule();};
    scene.onpointerleave=()=>{hovered=false;schedule();};
    scene.addEventListener('focusin',()=>{focused=true;schedule();});
    scene.addEventListener('focusout',e=>{if(!scene.contains(e.relatedTarget)){focused=false;schedule();}});
    new IntersectionObserver(([e])=>{visible=e.isIntersecting;schedule();},{threshold:.05}).observe(host);
    document.addEventListener('visibilitychange',schedule); reduced.addEventListener('change',schedule);
  }
  function update(el, roster, selected) {
    if(!host) mount(el);
    const sig=roster.map(r=>r.key).join('|');
    if(sig!==signature || !satellites.length) {
      signature=sig;
      const layer=host.querySelector('.saturn-satellites');layer.replaceChildren();
      satellites=roster.map((r,i)=>{
        const b=document.createElement('button');b.type='button';b.className='saturn-satellite';b.dataset.orbitKey=r.key;
        b.style.setProperty('--moon-color',color(i));
        b.innerHTML='<span class="saturn-moon"></span><span class="saturn-moon-label"></span>';
        b.querySelector('.saturn-moon-label').textContent=r.key.split('_')[0];
        b.setAttribute('aria-label',`${r.label}, strategia abilitata. Mostra dettagli`);
        b.title=r.label;layer.append(b);return b;
      });
      host.querySelector('[data-saturn-count]').textContent=roster.length?`${roster.length} strategie abilitate`:'Nessuna strategia abilitata';
      paint();schedule();
    }
    satellites.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.orbitKey===selected)));
  }
  return {update,color};
})();
