// TradeFlow AI — modules/hive.js (2026-09-18)
// "The Hive": nebulosa del roster strategie — nodi = strategie reali (SE.strategies,
// strategy.js), non trial fittizi. Connessioni = strategie che condividono un regime in
// SE.regimePriority. Knowledge tiles = riuso delle summary già in kb.js (nessun dato inventato).
// "Stato roster" = snapshot dei badge STABILE/DECADUTA già usati in backtest-report.js,
// con timestamp reale di brData.synced_at — non un log live fittizio (nessuna sorgente
// dati con eventi timestampati per-singolo-evento esiste oggi lato backend).

function hvHash(str){
  let h = 0;
  for(let i=0;i<str.length;i++) h = (h*31 + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}

// Tutte le strategie del roster (tradeabili + solo-score/ricerca) — riusa SE.strategies,
// stessa fonte di dashboard.js/backtest-report.js.
function hvAllStrategies(){
  return Object.entries(SE.strategies)
    .filter(([,s]) => !/RITIRATA/i.test(s.label||''))
    .map(([key,s]) => ({key, ...s}));
}

// Coppie di strategie che condividono almeno un regime in SE.regimePriority — relazione
// reale derivata dalla config, non inventata.
function hvRegimeLinks(all){
  const keys = new Set(all.map(s=>s.key));
  const pairs = new Set();
  Object.values(SE.regimePriority).forEach(list=>{
    const present = list.filter(k=>keys.has(k));
    for(let i=0;i<present.length;i++)
      for(let j=i+1;j<present.length;j++){
        const a=present[i], b=present[j];
        pairs.add(a<b ? `${a}|${b}` : `${b}|${a}`);
      }
  });
  return [...pairs].map(p=>p.split('|'));
}

function hvRenderStats(all){
  const el = document.getElementById('hive-stats');
  if(!el) return;
  const tradeable = all.filter(s=>!s.signalOnly);
  const research = all.filter(s=>s.signalOnly);
  let testedTrades = 0, wrSum = 0, wrN = 0;
  if(brData){
    tradeable.forEach(s=>{
      const info = (brData.shared_pool && brData.shared_pool[s.key]) || (brData.isolated && brData.isolated[s.key]);
      if(info){
        testedTrades += info.n_trades || 0;
        if(typeof info.full?.wr === 'number'){ wrSum += info.full.wr * (info.n_trades||1); wrN += (info.n_trades||1); }
      }
    });
  }
  const winShare = wrN ? (wrSum/wrN).toFixed(1)+'%' : '—';
  const tiles = [
    {k:'STRATEGIE VIVE', v: tradeable.length},
    {k:'IN RICERCA (solo score)', v: research.length},
    {k:'TRADE TESTATI', v: testedTrades ? testedTrades.toLocaleString('it-IT') : '—'},
    {k:'WIN SHARE (pesata)', v: winShare},
  ];
  el.innerHTML = tiles.map(t=>`
    <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:10px 12px">
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px">${t.k}</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700">${t.v}</div>
    </div>`).join('');
}

function hvRenderNebula(all){
  const el = document.getElementById('hive-nebula');
  if(!el) return;
  const W=900, H=420, cx=W/2, cy=H/2;
  const links = hvRegimeLinks(all);
  const pos = {};
  all.forEach(s=>{
    const a = (hvHash(s.key) % 360) * Math.PI/180;
    const r = 60 + (hvHash(s.key+'r') % 340);
    pos[s.key] = {x: cx + Math.cos(a)*r, y: cy + Math.sin(a)*r*0.62};
  });
  const linkSvg = links.map(([a,b])=>{
    if(!pos[a] || !pos[b]) return '';
    return `<line x1="${pos[a].x}" y1="${pos[a].y}" x2="${pos[b].x}" y2="${pos[b].y}" stroke="rgba(183,156,255,.18)" stroke-width="1"/>`;
  }).join('');
  const nodesSvg = all.map(s=>{
    const p = pos[s.key];
    if(s.signalOnly){
      return `<g data-hive-key="${s.key}" style="cursor:pointer">
        <circle cx="${p.x}" cy="${p.y}" r="10" fill="none" stroke="#5a4a7a" stroke-width="1.5" stroke-dasharray="2 3"/>
        <text x="${p.x}" y="${p.y+20}" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="8" fill="#8791B2">${s.label.split(' ')[0]}</text>
      </g>`;
    }
    const tier = orbitTier(s.pf);
    return `<g data-hive-key="${s.key}" style="cursor:pointer">
      <circle cx="${p.x}" cy="${p.y}" r="${9 + Math.min(s.pf,3)*3}" fill="${tier.color}" opacity=".88" style="filter:drop-shadow(0 0 6px ${tier.color})"/>
      <text x="${p.x}" y="${p.y+22}" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="9" fill="#C6D0E8">${s.label.split(' ')[0]}</text>
    </g>`;
  }).join('');
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="100%">${linkSvg}${nodesSvg}</svg>`;
}

function hvRenderKnowledge(){
  const el = document.getElementById('hive-knowledge');
  if(!el) return;
  const items = (typeof kb !== 'undefined' ? kb : []).slice(-6).reverse();
  if(!items.length){ el.innerHTML = '<div style="font-size:11px;color:var(--dim)">Nessuna nota in Knowledge Base ancora — caricane una dal tab 🧠.</div>'; return; }
  el.innerHTML = items.map(k=>`
    <div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:9px 11px">
      <div style="font-size:11px;font-weight:700;color:var(--text);margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${k.name||'nota'}</div>
      <div style="font-size:10px;color:var(--dim);line-height:1.4;max-height:2.8em;overflow:hidden">${(k.summary||'').slice(0,160)}</div>
    </div>`).join('');
}

function hvRenderRoster(all){
  const el = document.getElementById('hive-roster');
  if(!el) return;
  if(!brData){ el.innerHTML = '<div style="font-size:11px;color:var(--dim)">Report backtest non ancora caricato.</div>'; return; }
  const rows = all.filter(s=>!s.signalOnly).map(s=>{
    const info = (brData.shared_pool && brData.shared_pool[s.key]) || (brData.isolated && brData.isolated[s.key]);
    if(!info) return null;
    const disabled = (brData.disabled||[]).includes(s.key);
    const good = (info.holdout?.pf||0) >= 1;
    const badge = disabled ? {t:'⛔ DISATTIVATA', c:'#FF8A8A'} : good ? {t:'STABILE', c:'var(--green)'} : {t:'DECADUTA', c:'#FF8A8A'};
    return {key:s.key, label:s.label, badge, hpf: info.holdout?.pf ?? 0};
  }).filter(Boolean).sort((a,b)=> (a.badge.t==='STABILE'?0:1) - (b.badge.t==='STABILE'?0:1));
  const meta = document.getElementById('hive-roster-meta');
  if(meta) meta.textContent = brData.synced_at ? `stato al ${new Date(brData.synced_at).toLocaleString('it-IT')}` : '';
  el.innerHTML = rows.map(r=>`
    <div data-hive-key="${r.key}" style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border-bottom:1px solid var(--border);cursor:pointer">
      <span style="font-size:11px;color:var(--text)">${r.label.replace(/\s*⛔.*$/,'')}</span>
      <span style="display:flex;align-items:center;gap:8px">
        <span style="font-size:10px;font-family:'JetBrains Mono',monospace;color:var(--dim)">holdout PF ${r.hpf.toFixed(2)}</span>
        <span style="font-size:9px;font-weight:800;color:${r.badge.c}">${r.badge.t}</span>
      </span>
    </div>`).join('');
}

function hvRender(){
  const all = hvAllStrategies();
  hvRenderStats(all);
  hvRenderNebula(all);
  hvRenderKnowledge();
  hvRenderRoster(all);
}

document.addEventListener('click', (e)=>{
  if(e.target.closest('[data-action="open-hive"]')){
    openOvl('hivesheet');
    if(!brData) brLoad().then(hvRender); else hvRender();
    return;
  }
  const node = e.target.closest('[data-hive-key]');
  if(node){
    closeOvl('hivesheet');
    gnOpen(node.dataset.hiveKey);
  }
});
