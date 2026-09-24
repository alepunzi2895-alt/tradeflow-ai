// TradeFlow AI — modules/hive.js (2026-09-18)
// "The Hive": nebulosa del roster strategie — nodi = strategie reali (SE.strategies,
// strategy.js), non trial fittizi. Connessioni = strategie che condividono un regime in
// SE.regimePriority. Knowledge tiles = riuso delle summary già in kb.js (nessun dato inventato).
// "Stato roster" = snapshot dei badge STABILE/DECADUTA già usati in backtest-report.js,
// con timestamp reale di brData.synced_at — non un log live fittizio (nessuna sorgente
// dati con eventi timestampati per-singolo-evento esiste oggi lato backend).
// Stile: design system "nb-*" condiviso con Orbite/Genoma (vedi style.css).
// Stato ATTIVA/BLOCCATA = strategyState() (se-render.js) cioè il registro effettivo
// strategy_registry.json + hard_blocks.json, la stessa fonte del bot. Fix 2026-09-24: prima
// "STRATEGIE VIVE" contava anche le bloccate e lo "Stato roster" mostrava solo le strategie
// presenti nel report backtest, con lo stato congelato al giorno del run (brData.disabled)
// → ne risultavano 3 attive su 6 reali. Il PF di holdout resta un'informazione a parte.

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

function hvBtInfo(key){
  if(!brData) return null;
  return (brData.shared_pool && brData.shared_pool[key]) || (brData.isolated && brData.isolated[key]) || null;
}

function hvRenderStats(all){
  const el = document.getElementById('hive-stats');
  if(!el) return;
  const tradeable = all.filter(s=>!s.signalOnly);
  const active = tradeable.filter(s=>strategyState(s.key)==='active');
  const stopped = tradeable.filter(s=>['blocked','disabled'].includes(strategyState(s.key)));
  const research = all.filter(s=>s.signalOnly);
  const loading = tradeable.some(s=>strategyState(s.key)==='loading');
  // Win share pesata sui trade di backtest delle sole strategie attive.
  let wrSum = 0, wrN = 0;
  active.forEach(s=>{
    const info = hvBtInfo(s.key);
    if(info && typeof info.full?.wr === 'number'){ wrSum += info.full.wr * (info.n_trades||1); wrN += (info.n_trades||1); }
  });
  const winShare = wrN ? Math.round(wrSum/wrN) : null;
  const tiles = [
    {k:'ATTIVE SUL BOT', v: loading ? '…' : active.length, c:'var(--nb-accent)', w: tradeable.length ? active.length/tradeable.length*100 : 0},
    {k:'BLOCCATE / SPENTE', v: loading ? '…' : stopped.length, c:'var(--nb-down)', w: tradeable.length ? stopped.length/tradeable.length*100 : 0},
    {k:'IN RICERCA (SOLO SCORE)', v: research.length, c:'var(--nb-cyan)', w: Math.min(100, research.length*25)},
    {k:'WIN SHARE ATTIVE', v: winShare!=null ? winShare+'%' : '—', c:'var(--nb-up)', w: winShare||0},
  ];
  el.innerHTML = tiles.map(t=>`
    <div class="nb-panel nb-panel--pad nb-stack nb-stack--tight">
      <span class="nb-lbl">${t.k}</span>
      <span class="nb-num" style="font-size:22px;font-weight:600;color:${t.c}">${t.v}</span>
      <div class="nb-bar" style="height:3px"><div class="nb-bar__fill" style="width:${t.w}%;background:${t.c}"></div></div>
    </div>`).join('');
}

// Nodi a gauge (come i "token" del riferimento nebula-ui): arco colorato per PF reale,
// tratteggiato per le strategie solo-score. Posizione da hash stabile della key (nebulosa
// non fisicamente accurata, ma stabile tra un render e l'altro).
function hvRenderNebula(all){
  const el = document.getElementById('hive-nebula');
  if(!el) return;
  const W=900, H=340, cx=W/2, cy=H/2;
  const links = hvRegimeLinks(all);
  const pos = {};
  all.forEach(s=>{
    const a = (hvHash(s.key) % 360) * Math.PI/180;
    const r = 55 + (hvHash(s.key+'r') % 280);
    pos[s.key] = {x: cx + Math.cos(a)*r, y: cy + Math.sin(a)*r*0.62};
  });
  const linkSvg = links.map(([a,b])=>{
    if(!pos[a] || !pos[b]) return '';
    return `<line x1="${pos[a].x.toFixed(0)}" y1="${pos[a].y.toFixed(0)}" x2="${pos[b].x.toFixed(0)}" y2="${pos[b].y.toFixed(0)}" stroke="rgba(232,193,115,.14)" stroke-width="1"/>`;
  }).join('');
  const nodesSvg = all.map((s,i) => {
    const p = pos[s.key], d = s.signalOnly ? 46 : 54;
    const st = strategyState(s.key), off = !s.signalOnly && st!=='active' && st!=='loading';
    // Guardia numerica: una strategia senza ancora un backtest ha pf null/undefined — senza
    // questo fallback orbitTier()/.toFixed() mandano in crash l'intera nebulosa (audit 2026-09-18,
    // stesso pattern già presente in dashboard.js::orbitRoster()).
    const pf = typeof s.pf === 'number' ? s.pf : 0;
    const tier = s.signalOnly ? {hex:'#5a4a7a'} : off ? {hex:'#6b6f7a'} : orbitTier(pf);
    const pfNorm = s.signalOnly ? 0.3 : Math.max(0.08, Math.min(1, (pf-0.6)/2));
    const dashArr = s.signalOnly ? '2 6' : `${Math.round(2*Math.PI*40 * pfNorm)} 251`;
    return `<a class="nb-token" href="#" data-hive-key="${s.key}" style="left:${(p.x/W*100).toFixed(1)}%;top:${(p.y/H*100).toFixed(1)}%;--delay:${(-i*0.7).toFixed(1)}s;--glow:${tier.hex}66${off?';opacity:.45':''}" title="${off?'Bloccata/spenta sul bot':s.signalOnly?'Solo score, non tradata':'Attiva sul bot'}">
      <svg width="${d}" height="${d}" viewBox="0 0 100 100" fill="none">
        <circle cx="50" cy="50" r="40" stroke="var(--nb-line)" stroke-width="7"/>
        <circle class="nb-arc" cx="50" cy="50" r="40" stroke="${tier.hex}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${dashArr}"/>
        <circle cx="50" cy="50" r="27" fill="#04060a" fill-opacity=".8"/>
      </svg>
      <span class="nb-token__hash">${s.label.split(' ')[0]}</span>
      <span class="nb-token__v" style="color:${tier.hex}">${s.signalOnly?'solo score':off?'ferma':'PF '+pf.toFixed(2)}</span>
    </a>`;
  }).join('');
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="100%" style="position:absolute;inset:0">${linkSvg}</svg>${nodesSvg}`;
}

function hvRenderKnowledge(){
  const el = document.getElementById('hive-knowledge');
  if(!el) return;
  const items = (typeof kb !== 'undefined' ? kb : []).slice(-6).reverse();
  if(!items.length){ el.innerHTML = '<div style="font-size:11px;color:var(--nb-muted)">Nessuna nota in Knowledge Base ancora — caricane una dal tab 🧠.</div>'; return; }
  el.innerHTML = items.map(k=>`
    <article class="nb-panel nb-tile" style="padding:12px 14px;display:flex;flex-direction:column;gap:6px;min-width:0">
      <span style="font-size:12px;font-weight:600;color:var(--nb-txt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${k.name||'nota'}</span>
      <span style="font-size:11px;color:var(--nb-muted);line-height:1.4;max-height:2.8em;overflow:hidden">${(k.summary||'').slice(0,160)}</span>
    </article>`).join('');
}

function hvRenderRoster(all){
  const el = document.getElementById('hive-roster');
  if(!el) return;
  const STATE = {
    active:   {t:'ATTIVA', cls:'nb-badge--ok', ord:0},
    blocked:  {t:'BLOCCATA', cls:'', ord:1},
    disabled: {t:'SPENTA', cls:'', ord:1},
    loading:  {t:'…', cls:'', ord:2},
    unknown:  {t:'N/D', cls:'', ord:2},
  };
  // Tutte le tradeabili, anche senza report backtest (es. strategia appena aggiunta):
  // lo stato viene dal registro, il PF di holdout è solo informativo.
  const rows = all.filter(s=>!s.signalOnly).map(s=>{
    const st = strategyState(s.key);
    const badge = STATE[st] || STATE.unknown;
    const info = hvBtInfo(s.key);
    const hpf = typeof info?.holdout?.pf === 'number' ? info.holdout.pf : null;
    const sym = window.strategyRegistry?.strategies?.[s.key]?.symbol;
    return {key:s.key, label:s.label, badge, hpf, sym};
  }).sort((a,b)=> a.badge.ord-b.badge.ord || (b.hpf??-1)-(a.hpf??-1));
  const meta = document.getElementById('hive-roster-meta');
  const nAct = rows.filter(r=>r.badge.t==='ATTIVA').length;
  if(meta) meta.textContent = `${nAct}/${rows.length} attive · stato dal registro del bot`
    + (brData?.generated_at || brData?.synced_at ? ` · backtest del ${new Date(brData.generated_at||brData.synced_at).toLocaleDateString('it-IT')}` : ' · report backtest non caricato');
  el.innerHTML = rows.map(r=>{
    const hpfTxt = r.hpf==null ? 'holdout n/d' : `holdout PF ${r.hpf.toFixed(2)}`;
    const hpfCol = r.hpf==null ? 'var(--nb-muted)' : r.hpf>=1 ? 'var(--nb-up)' : 'var(--nb-down)';
    const warn = r.badge.t==='ATTIVA' && r.hpf!=null && r.hpf<1 ? ' title="Attiva sul bot ma con holdout PF < 1: da monitorare"' : '';
    return `<li><button type="button" class="nb-row" data-hive-key="${r.key}" style="min-height:48px">
    <span class="nb-row__main"><span class="nb-row__name" style="font-size:13px">${r.label.replace(/\s*⛔.*$/,'')}${r.sym && r.sym!=='XAUUSD' ? ` <span style="font-size:10px;color:var(--nb-muted)">${r.sym}</span>` : ''}</span></span>
    <span class="nb-row__side" style="flex-direction:row;align-items:center;gap:10px">
      <span class="nb-num" style="font-size:11px;color:${hpfCol}"${warn}>${hpfTxt}${warn?' ⚠':''}</span>
      <span class="nb-badge ${r.badge.cls}" style="color:${r.badge.cls?'':'var(--nb-down)'}">${r.badge.t}</span>
    </span>
  </button></li>`;
  }).join('');
}

function hvRender(){
  const all = hvAllStrategies();
  for(const fn of [()=>hvRenderStats(all), ()=>hvRenderNebula(all), hvRenderKnowledge, ()=>hvRenderRoster(all)]){
    try{ fn(); }catch(e){ console.error('[hive]', e); }
  }
}

document.addEventListener('click', (e)=>{
  if(e.target.closest('[data-action="open-hive"]')){
    openOvl('hivesheet');
    hvRender();
    Promise.all([ensureStrategyRegistry(), brData ? null : brLoad()]).then(hvRender);
    return;
  }
  const node = e.target.closest('[data-hive-key]');
  if(node){
    e.preventDefault();
    closeOvl('hivesheet');
    gnOpen(node.dataset.hiveKey);
  }
});
