// TradeFlow AI — modules/backtest-report.js (2026-09-17)
// Pannello "Report Backtest" nel tab Strategie: equity curve + confronto attive/roster
// completo + validazione regime (stesso contenuto/stile dell'artifact di analisi), più
// "Lancia backtest" on-demand (coda verso scripts/backtest_worker.py) e toggle
// attiva/blocca (scrive un commit reale su GitHub via api/db.js::hardBlocksToggle).

const BR_NAMES = {
  S00_MFKK:'S00 · MFKK Score', S09_MFKK_SCALPING:'S09 · MFKK Scalping',
  S10_OB_FVG_SCALP:'S10 · OB+FVG Scalp', S16_GOLDEN_SQUEEZE:'S16 · Golden Squeeze',
  S17_CONVERGENCE_SCALP:'S17 · Convergence', S18_RANGE_REVERSAL:'S18 · Range Reversal',
  S20_FIB_CONFLUENCE:'S20 · Fib Confluence', S31_LAYOUT_SMART:'S31 · Layout Smart',
  S30_DOW_DIP:'S30 · Dow Dip (US30)',
};
const BR_ORDER = ['S30_DOW_DIP','S31_LAYOUT_SMART','S17_CONVERGENCE_SCALP','S20_FIB_CONFLUENCE',
                  'S16_GOLDEN_SQUEEZE','S10_OB_FVG_SCALP','S09_MFKK_SCALPING','S18_RANGE_REVERSAL','S00_MFKK'];

let brData = null;          // ultimo report ricevuto da backtest_report_get
let brHeroKey = null;       // null = combinata
let brHeroMode = 'active';  // 'active' | 'full'
let brPolling = {};         // {strategy_id: intervalId} — poll dei risultati on-demand

function brFmt(n, d=1){ n = n||0; return (n>=0?'+':'') + n.toFixed(d); }

// ── Canvas line chart minimale (stesso disegno dell'artifact, palette app) ───────
function brDrawLine(canvas, series, opts){
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(rect.width, 40), h = Math.max(rect.height, 30);
  canvas.width = w*dpr; canvas.height = h*dpr;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,w,h);
  if(!series || series.length<2) return null;
  const pad = opts.pad || {t:6,r:6,b:6,l:6};
  const xs = series.map(p=>p.t), ys = series.map(p=>p.v);
  const xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(0,...ys), ymax=Math.max(0,...ys);
  const xr = xmax-xmin||1, yr = ymax-ymin||1;
  const X = t => pad.l + (t-xmin)/xr * (w-pad.l-pad.r);
  const Y = v => h-pad.b - (v-ymin)/yr * (h-pad.t-pad.b);
  if(opts.zeroLine){
    ctx.strokeStyle = 'rgba(255,255,255,.08)'; ctx.lineWidth=1;
    ctx.beginPath(); ctx.moveTo(pad.l,Y(0)); ctx.lineTo(w-pad.r,Y(0)); ctx.stroke();
  }
  if(opts.fill){
    ctx.beginPath(); ctx.moveTo(X(xs[0]),Y(0));
    series.forEach(p=>ctx.lineTo(X(p.t),Y(p.v)));
    ctx.lineTo(X(xs[xs.length-1]),Y(0)); ctx.closePath();
    const grad = ctx.createLinearGradient(0,0,0,h);
    grad.addColorStop(0, opts.color+'33'); grad.addColorStop(1, opts.color+'02');
    ctx.fillStyle = grad; ctx.fill();
  }
  ctx.beginPath();
  series.forEach((p,i)=> i===0 ? ctx.moveTo(X(p.t),Y(p.v)) : ctx.lineTo(X(p.t),Y(p.v)));
  ctx.strokeStyle = opts.color; ctx.lineWidth = opts.lw||1.6; ctx.lineJoin='round'; ctx.stroke();
  return {X,Y,xmin,xmax,ymin,ymax,w,h,pad};
}

function brCombinedSeries(mode){
  const src = mode==='active' ? (brData.active_combined_stats?.equity_curve||[]) : (brData.combined_stats?.equity_curve||[]);
  const byDay = {};
  src.forEach(p=>{ byDay[p.date]=p.cum_pnl; });
  return Object.keys(byDay).sort().map(d=>({t:new Date(d+'T00:00:00Z').getTime(), v:byDay[d]}));
}
function brStrategySeries(key){
  const info = (brData.shared_pool && brData.shared_pool[key]) || (brData.isolated && brData.isolated[key]);
  return (brData.equity_curves?.[key]||info?.equity_curve||[]).map(p=>({t:p.t*1000, v:p.cum_pnl}));
}

function brRenderHero(){
  const canvas = document.getElementById('br-hero');
  const tooltip = document.getElementById('br-tooltip');
  if(!canvas) return;
  const series = brHeroKey ? brStrategySeries(brHeroKey) : brCombinedSeries(brHeroMode);
  canvas._brSeries = series;
  const color = brHeroKey ? '#F4B860' : '#62E6A6';
  canvas._brGeom = brDrawLine(canvas, series, {color, fill:true, lw:2, zeroLine:true, pad:{t:14,r:10,b:14,l:10}});
  const label = document.getElementById('br-hero-label');
  if(label) label.textContent = brHeroKey ? (BR_NAMES[brHeroKey]||brHeroKey) : (brHeroMode==='active' ? 'Combinata · solo attive' : 'Combinata · roster completo');
  document.querySelectorAll('.br-card').forEach(c=>{ c.style.borderColor = c.dataset.key===brHeroKey ? 'var(--g)' : 'var(--border2)'; });
  if(tooltip) tooltip.style.opacity = 0;
}

function brSetViewBtn(mode){
  const a = document.getElementById('br-view-active'), f = document.getElementById('br-view-full');
  if(!a || !f) return;
  const on = 'background:var(--g);border:none;border-radius:6px;padding:5px 10px;color:#000;font-size:10px;font-weight:700;cursor:pointer;font-family:inherit';
  const off = 'background:var(--card);border:1px solid var(--border2);border-radius:6px;padding:5px 10px;color:var(--dim);font-size:10px;font-weight:700;cursor:pointer;font-family:inherit';
  a.style.cssText = mode==='active' ? on : off;
  f.style.cssText = mode==='full' ? on : off;
}

function brWireHero(){
  const canvas = document.getElementById('br-hero');
  const tooltip = document.getElementById('br-tooltip');
  if(!canvas || canvas._brWired) return;
  canvas._brWired = true;
  canvas.addEventListener('mousemove', e=>{
    const series = canvas._brSeries, geom = canvas._brGeom;
    if(!series || !series.length || !geom) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const frac = Math.min(1,Math.max(0,(mx-geom.pad.l)/(geom.w-geom.pad.l-geom.pad.r)));
    const t = geom.xmin + frac*(geom.xmax-geom.xmin);
    let best = series[0], bd = Infinity;
    for(const p of series){ const dd = Math.abs(p.t-t); if(dd<bd){bd=dd;best=p;} }
    const px = geom.X(best.t), py = geom.Y(best.v);
    tooltip.style.left = Math.min(px+10, rect.width-130)+'px';
    tooltip.style.top = Math.max(py-36,0)+'px';
    tooltip.innerHTML = `${new Date(best.t).toLocaleDateString('it-IT',{day:'2-digit',month:'short',year:'numeric'})}<br><b>${brFmt(best.v)}</b>`;
    tooltip.style.opacity = 1;
  });
  canvas.addEventListener('mouseleave', ()=>{ tooltip.style.opacity = 0; });
  window.addEventListener('resize', ()=>{ if(document.getElementById('brsheet')?.classList.contains('on')) brRenderHero(); });
}

// ── Card per singola strategia ───────────────────────────────────────────────
function brCard(key){
  const info = (brData.shared_pool && brData.shared_pool[key]) || (brData.isolated && brData.isolated[key]);
  if(!info) return '';
  const disabled = (brData.disabled||[]).includes(key);
  const good = (info.holdout?.pf||0) >= 1;
  const badge = disabled ? {t:'⛔ DISATTIVATA', c:'#FF8A8A', bg:'rgba(255,138,138,.12)'}
              : good ? {t:'STABILE', c:'var(--green)', bg:'rgba(0,230,118,.12)'}
              : {t:'DECADUTA', c:'#FF8A8A', bg:'rgba(255,138,138,.12)'};
  return `
  <div class="br-card" data-key="${key}" style="background:var(--card);border:1px solid var(--border2);border-radius:10px;padding:11px 12px;${disabled?'opacity:.65':''}">
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px">
      <span style="font-size:12px;font-weight:700;color:var(--text)">${BR_NAMES[key]||key}</span>
      <span style="font-size:9px;color:var(--dim)">${info.tf}</span>
    </div>
    <canvas class="br-spark" style="width:100%;height:40px;display:block;margin:5px 0 6px;cursor:pointer"></canvas>
    <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--dim)">
      <span>full PF <b style="color:var(--text)">${(info.full?.pf??0).toFixed(2)}</b></span>
      <span>holdout PF <b style="color:${good?'var(--green)':'#FF8A8A'}">${(info.holdout?.pf??0).toFixed(2)}</b></span>
    </div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:5px">
      <span style="font-size:9.5px;color:var(--dim)">n=${info.n_trades}</span>
      <span style="font-size:9px;font-weight:800;padding:1px 6px;border-radius:5px;color:${badge.c};background:${badge.bg}" data-badge="${key}">${badge.t}</span>
    </div>
    <div style="display:flex;gap:5px;margin-top:8px">
      <button data-br-run="${key}" style="flex:1;background:var(--bg2);border:1px solid var(--border2);border-radius:6px;padding:5px;color:var(--g);font-size:10px;cursor:pointer;font-family:inherit">🔄 Backtest</button>
      <button data-br-toggle="${key}" data-disabled="${disabled}" style="flex:1;background:var(--bg2);border:1px solid var(--border2);border-radius:6px;padding:5px;color:${disabled?'var(--green)':'#FF8A8A'};font-size:10px;cursor:pointer;font-family:inherit">${disabled?'🔓 Attiva':'⛔ Blocca'}</button>
    </div>
    <button data-br-genome="${key}" style="width:100%;margin-top:5px;background:rgba(229,189,108,.06);border:1px solid rgba(229,189,108,.22);border-radius:6px;padding:5px;color:var(--g);font-size:10px;cursor:pointer;font-family:inherit">🧬 Apri genoma</button>
  </div>`;
}

function brRenderCards(){
  const grid = document.getElementById('br-grid');
  if(!grid) return;
  grid.innerHTML = BR_ORDER.map(brCard).join('');
  grid.querySelectorAll('.br-spark').forEach(c=>{
    const key = c.closest('.br-card').dataset.key;
    const series = brStrategySeries(key);
    const positive = series.length && series[series.length-1].v >= 0;
    requestAnimationFrame(()=> brDrawLine(c, series, {color: positive?'#62E6A6':'#FF8A8A', fill:true, lw:1.3, pad:{t:2,r:2,b:2,l:2}}));
    c.addEventListener('click', ()=>{ brHeroKey = (brHeroKey===key ? null : key); brRenderHero(); });
  });
}

function brRenderCompare(){
  const el = document.getElementById('br-compare');
  if(!el) return;
  const cs = brData.combined_stats, ca = brData.active_combined_stats;
  if(!cs || !ca){ el.innerHTML=''; return; }
  const rows = [
    {l:'Profit Factor', b:cs.pf, a:ca.pf, dp:2, higher:true},
    {l:'Win Rate %', b:cs.wr, a:ca.wr, dp:1, higher:true},
    {l:'P&L totale', b:cs.total_pnl, a:ca.total_pnl, dp:0, higher:true},
    {l:'Max Drawdown', b:cs.max_dd, a:ca.max_dd, dp:0, higher:false},
  ];
  el.innerHTML = rows.map(r=>{
    const d = r.a - r.b;
    const good = r.higher ? d>=0 : d<=0;
    return `<div style="background:var(--card);border:1px solid var(--border2);border-radius:9px;padding:9px 11px">
      <div style="font-size:9px;color:var(--dim);letter-spacing:.05em;text-transform:uppercase;margin-bottom:5px">${r.l}</div>
      <div style="display:flex;align-items:baseline;gap:6px">
        <span style="font-size:11px;color:var(--dim);text-decoration:line-through">${r.b.toFixed(r.dp)}</span>
        <span style="font-size:15px;font-weight:700;color:var(--text)">${r.a.toFixed(r.dp)}</span>
        <span style="font-size:10px;font-weight:700;color:${good?'var(--green)':'#FF8A8A'}">${d>=0?'+':''}${d.toFixed(Math.max(r.dp,2))}</span>
      </div>
    </div>`;
  }).join('');
}

function brRenderRegime(){
  const el = document.getElementById('br-regime');
  if(!el || !brData.regime_validation) return;
  let rows = '';
  Object.keys(brData.regime_validation).forEach(sid=>{
    const rv = brData.regime_validation[sid];
    rows += `<div style="margin-top:10px;font-size:11.5px;font-weight:700;color:var(--g)">${BR_NAMES[sid]||sid} <span style="font-size:9.5px;color:var(--dim);font-weight:400">optimal: ${rv.optimal_regimes_coded.join(', ')}</span></div>`;
    Object.entries(rv.observed).sort((a,b)=>b[1].pnl-a[1].pnl).forEach(([reg,s])=>{
      const ok = rv.optimal_regimes_coded.includes(reg);
      rows += `<div style="display:flex;justify-content:space-between;font-size:10.5px;color:var(--dim);padding:3px 0;border-bottom:1px solid var(--border)">
        <span style="color:var(--text)">${reg}</span><span>n=${s.n}</span><span>PF ${Math.min(s.pf,99.9).toFixed(2)}</span>
        <span style="color:${s.pnl>=0?'var(--green)':'#FF8A8A'}">${brFmt(s.pnl)}</span>
        <span style="color:${ok?'var(--green)':'var(--yellow)'}">${ok?'✓':'⚠ fuori config'}</span>
      </div>`;
    });
  });
  el.innerHTML = rows;
}

function brRenderAll(){
  if(!brData) return;
  const meta = document.getElementById('br-meta');
  if(meta) meta.textContent = brData.synced_at ? `Aggiornato ${new Date(brData.synced_at).toLocaleString('it-IT')}` : '';
  brRenderCompare();
  brRenderCards();
  brRenderHero();
  brWireHero();
  brRenderRegime();
}

async function brLoad(){
  const body = document.getElementById('brsheet-body');
  if(body) body.style.opacity = '.5';
  try{
    const r = await fetch('/api/db', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'backtest_report_get'})});
    const d = await r.json();
    if(d.ok && d.data){ brData = d.data; brRenderAll(); }
    else if(body) body.innerHTML = '<div style="color:var(--dim);font-size:12px;padding:20px 0;text-align:center">Nessun report ancora disponibile — gira <code>python scripts/portfolio_backtest.py --push</code> una prima volta (poi lo fa da solo ogni giorno).</div>';
  }catch(e){
    if(body) body.innerHTML = `<div style="color:#FF8A8A;font-size:12px">Errore caricamento report: ${e.message}</div>`;
  }
  if(body) body.style.opacity = '1';
}

// ── Lancia backtest on-demand ─────────────────────────────────────────────────
async function brRunBacktest(key){
  const badgeEl = document.querySelector(`[data-badge="${key}"]`);
  const btn = document.querySelector(`[data-br-run="${key}"]`);
  if(btn){ btn.textContent='⏳ In coda...'; btn.disabled = true; }
  try{
    await fetch('/api/db', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'backtest_cmd_push', strategy_id:key})});
  }catch(e){ alert('Errore invio richiesta: '+e.message); if(btn){btn.textContent='🔄 Backtest';btn.disabled=false;} return; }

  const requestedAt = Date.now();
  if(brPolling[key]) clearInterval(brPolling[key]);
  let tries = 0;
  brPolling[key] = setInterval(async ()=>{
    tries++;
    if(tries > 40){ // ~6 min a 9s/poll
      clearInterval(brPolling[key]); delete brPolling[key];
      if(btn){btn.textContent='🔄 Backtest';btn.disabled=false;}
      alert(`Nessuna risposta dal worker per ${key} — è in esecuzione scripts/backtest_worker.py?`);
      return;
    }
    try{
      const r = await fetch('/api/db', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'backtest_result_get', strategy_id:key})});
      const d = await r.json();
      if(!d.ok || !d.data) return;
      const syncedAt = new Date(d.data.synced_at||0).getTime();
      if(syncedAt < requestedAt) return; // risultato vecchio, non ancora arrivato quello nuovo
      clearInterval(brPolling[key]); delete brPolling[key];
      if(btn){btn.textContent='🔄 Backtest';btn.disabled=false;}
      if(d.data.error){ alert(`Backtest ${key} fallito: ${d.data.error}`); return; }
      // Aggiorna in-place i dati locali + ri-renderizza quella card
      const bucket = brData.shared_pool?.[key] ? 'shared_pool' : 'isolated';
      brData[bucket][key] = { tf:d.data.tf, full:d.data.full, holdout:d.data.holdout, holdout_start:d.data.holdout_start, n_trades:d.data.n_trades };
      if(!brData.equity_curves) brData.equity_curves = {};
      brData.equity_curves[key] = d.data.equity_curve;
      brRenderCards(); brRenderHero();
    }catch(e){ /* rete instabile, ritenta al prossimo giro */ }
  }, 9000);
}

// ── Toggle attiva/blocca (scrive un commit reale su GitHub, richiede login) ──
async function brToggleBlock(key, currentlyDisabled){
  if(!window.sessionToken){ alert('Devi essere loggato per attivare/bloccare una strategia.'); return; }
  const name = BR_NAMES[key]||key;
  const mode = currentlyDisabled ? 'unblock' : 'block';
  let reason = null;
  if(mode === 'block'){
    reason = prompt(`Motivo del blocco di ${name}:`, 'Holdout PF sotto 1 nell\'ultimo re-backtest.');
    if(reason === null) return; // annullato
  }
  const verb = mode==='block' ? 'BLOCCARE' : 'RIATTIVARE';
  if(!confirm(`Vuoi ${verb} ${name}?\n\nQuesto scrive un commit reale su GitHub (data/hard_blocks.json). Il bot lo applica al prossimo git pull + restart, non è immediato.`)) return;

  const btn = document.querySelector(`[data-br-toggle="${key}"]`);
  if(btn){ btn.textContent='⏳...'; btn.disabled = true; }
  try{
    // NB: "action" qui sotto è il dispatcher dell'API (hard_blocks_toggle) — il verbo
    // block/unblock viaggia come "mode" per non collidere sulla stessa chiave JSON.
    const r = await fetch('/api/db', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'hard_blocks_toggle', token:window.sessionToken, strategy_id:key, mode, reason})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.error||'Errore sconosciuto');
    brData.disabled = Object.keys(d.blocked);
    brRenderCards();
    alert(`✅ ${name} ${mode==='block'?'bloccata':'riattivata'}. Ricorda: serve git pull + restart del bot sulla VPS per avere effetto.`);
  }catch(e){
    alert('Errore: '+e.message);
  }
  if(btn){ btn.disabled = false; }
}

// ── GENOMA · dettaglio confidenza per singola strategia ─────────────────────
// Punteggio "struttura dell'edge" derivato SOLO da metriche già in brData (full/holdout PF,
// n_trades, regime_validation) — NON è Sharpe/DSR accademico (quei valori oggi non sono
// persistiti lato Python, vedi opt_harness.dsr_check/pbo_check). Pesi arbitrari ma documentati:
// 30% consistenza recente (holdout/full PF) + 30% durabilità (PF holdout assoluto)
// + 25% copertura regime (quota regimi osservati con PF>=1) + 15% ampiezza campione (n_trades).
function gnScore(info, regime){
  const full = info.full||{}, holdout = info.holdout||{};
  const fPf = full.pf||0, hPf = holdout.pf||0;
  const consistency = fPf>0 ? Math.max(0,Math.min(1, hPf/fPf)) : 0;
  const durability = Math.max(0, Math.min(1, (hPf-1)/1.5));
  let coverage = 0.5, regimeNote = 'nessun dato di regime per questa strategia';
  if(regime && regime.observed){
    const obs = Object.entries(regime.observed);
    if(obs.length){
      const okN = obs.filter(([,st])=>st.pf>=1).length;
      coverage = okN/obs.length;
      regimeNote = `${okN}/${obs.length} regimi osservati con PF≥1`;
    }
  }
  const sample = Math.max(0, Math.min(1, Math.log10(Math.max(info.n_trades||0,1)/20) / Math.log10(150/20)));
  const score = Math.round((consistency*0.30 + durability*0.30 + coverage*0.25 + sample*0.15) * 100);
  let tier, tierColor;
  if(score>=70){ tier='TIER 1 · Credibile'; tierColor='var(--green)'; }
  else if(score>=45){ tier='TIER 2 · Da confermare'; tierColor='#F4B860'; }
  else { tier='TIER 3 · Fragile'; tierColor='#FF8A8A'; }
  return {score, tier, tierColor, consistency, durability, coverage, sample, regimeNote};
}

// Bootstrap resample dai delta giornalieri dell'equity curve reale — "fortuna o edge":
// se la % di resample profittevoli è alta il P&L non dipende da una manciata di trade fortunati.
function gnBootstrap(equityCurve, iters=800){
  const pts = (equityCurve||[]).map(p=> p.cum_pnl!==undefined?p.cum_pnl:p.v).filter(v=>typeof v==='number');
  if(pts.length<6) return null;
  const deltas = [];
  for(let i=1;i<pts.length;i++) deltas.push(pts[i]-pts[i-1]);
  const results = [];
  for(let it=0; it<iters; it++){
    let sum=0;
    for(let i=0;i<deltas.length;i++) sum += deltas[(Math.random()*deltas.length)|0];
    results.push(sum);
  }
  results.sort((a,b)=>a-b);
  const median = results[Math.floor(results.length/2)];
  const profitable = results.filter(r=>r>0).length/results.length;
  return {results, median, profitable};
}

// Istogramma resample come colonne CSS (.nb-cols) invece di canvas — coerente con lo stile
// del resto delle viste Nebula e riusa l'animazione "nb-rise" già definita.
function gnHistCols(boot){
  const nBins=22;
  const min=boot.results[0], max=boot.results[boot.results.length-1];
  const range=(max-min)||1;
  const bins=new Array(nBins).fill(0);
  boot.results.forEach(v=>{ const b=Math.min(nBins-1,Math.max(0,Math.floor((v-min)/range*nBins))); bins[b]++; });
  const maxCount=Math.max(...bins,1);
  return bins.map((c,i)=>{
    const h=Math.max(3,Math.round((c/maxCount)*84));
    const binStart=min+(i/nBins)*range;
    const col=binStart>=0?'rgba(79,224,168,.75)':'rgba(255,138,138,.7)';
    return `<span style="height:${h}px;background:${col};--delay:${(i*0.025).toFixed(2)}s"></span>`;
  }).join('');
}

// "Periodi profittevoli": bucket reali dell'equity curve (non dati inventati) — delta di
// P&L cumulato per decile della serie storica disponibile.
function gnPeriodCols(equityCurve){
  const pts=(equityCurve||[]).map(p=>p.cum_pnl!==undefined?p.cum_pnl:p.v).filter(v=>typeof v==='number');
  if(pts.length<4) return null;
  const nBuckets=Math.min(10, pts.length-1);
  const bucketSize=Math.max(1, Math.floor(pts.length/nBuckets));
  const deltas=[];
  for(let i=0;i<nBuckets;i++){
    const a=pts[i*bucketSize], b=pts[Math.min((i+1)*bucketSize, pts.length-1)];
    deltas.push(b-a);
  }
  const maxAbs=Math.max(...deltas.map(Math.abs),1);
  const profitable=deltas.filter(d=>d>=0).length;
  const cols=deltas.map((d,i)=>{
    const h=Math.max(4,Math.round(Math.abs(d)/maxAbs*70));
    return `<span style="height:${h}px;background:${d>=0?'rgba(79,224,168,.75)':'rgba(255,138,138,.7)'};--delay:${(i*0.06).toFixed(2)}s"></span>`;
  }).join('');
  return {cols, profitable, total:deltas.length};
}

function gnRender(key){
  const body = document.getElementById('genomesheet-body');
  if(!body) return;
  if(!brData){ body.innerHTML = '<div style="color:var(--nb-muted);font-size:12px">Report backtest non disponibile — riprova con "🔃 Ricarica" nel Report Backtest.</div>'; return; }
  const info = (brData.shared_pool && brData.shared_pool[key]) || (brData.isolated && brData.isolated[key]);
  if(!info){ body.innerHTML = '<div style="color:var(--nb-muted);font-size:12px">Nessun dato per questa strategia.</div>'; return; }
  const meta = (typeof SE!=='undefined' && SE.strategies?.[key]) || {};
  const regime = brData.regime_validation?.[key];
  const s = gnScore(info, regime);
  const eqCurve = info.equity_curve || brData.equity_curves?.[key];
  const boot = gnBootstrap(eqCurve);
  const periods = gnPeriodCols(eqCurve);
  const disabled = (brData.disabled||[]).includes(key);

  const R1=70, C1=2*Math.PI*R1, off1=(C1*(100-s.score)/100).toFixed(1);
  const R2=45, C2=2*Math.PI*R2, off2=(C2*(1-s.coverage)).toFixed(1);

  const bar = (label, val, sub) => `
    <div class="nb-stack nb-stack--tight" style="margin-bottom:2px">
      <div class="nb-between" style="align-items:baseline">
        <span style="font-size:13px;color:var(--nb-dim)">${label}</span>
        <span class="nb-num" style="font-size:14px;font-weight:600;color:${val>=0.6?'var(--nb-up)':val>=0.35?'var(--nb-accent)':'var(--nb-down)'}">${Math.round(val*100)}/100</span>
      </div>
      <div class="nb-bar"><div class="nb-bar__fill" style="width:${Math.round(val*100)}%;background:linear-gradient(90deg,${val>=0.6?'var(--nb-up),#8FF0CE':val>=0.35?'var(--nb-accent),var(--nb-accent3)':'var(--nb-down),#FFB6B6'})"></div></div>
      <span style="font-size:11px;line-height:1.4;color:var(--nb-muted)">${sub}</span>
    </div>`;

  body.innerHTML = `
    <div class="nb-panels" style="grid-template-columns:1fr">
      <div class="nb-stack" style="gap:16px">
        <div class="nb-between" style="align-items:flex-start">
          <div>
            <div class="nb-lbl">${info.tf||''} · ${info.n_trades||0} trade${disabled?' · <span style="color:var(--nb-down)">DISATTIVATA</span>':''}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:21px;font-weight:700;margin-top:3px">${meta.label || BR_NAMES[key] || key}</div>
          </div>
        </div>

        <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap">
          <svg width="140" height="140" viewBox="0 0 176 176" fill="none">
            <circle cx="88" cy="88" r="${R1}" stroke="var(--nb-line)" stroke-width="13"/>
            <circle class="nb-gauge__arc" cx="88" cy="88" r="${R1}" stroke="${s.tierColor}" stroke-width="13" stroke-linecap="round" stroke-dasharray="${C1.toFixed(1)}" stroke-dashoffset="${off1}" transform="rotate(-90 88 88)"/>
            <circle class="nb-gauge__arc--thin" cx="88" cy="88" r="${R2}" stroke="rgba(111,168,255,.5)" stroke-width="3" stroke-linecap="round" stroke-dasharray="${C2.toFixed(1)}" stroke-dashoffset="${off2}" transform="rotate(-90 88 88)"/>
            <text class="nb-mono" x="88" y="84" text-anchor="middle" fill="var(--nb-txt)" font-size="38" font-weight="600">${s.score}</text>
            <text class="nb-mono" x="88" y="104" text-anchor="middle" fill="var(--nb-muted)" font-size="12">/100</text>
          </svg>
          <div class="nb-stack nb-stack--tight" style="flex:1 1 200px;min-width:0">
            <span style="font-family:'JetBrains Mono',monospace;font-size:22px;font-weight:700;color:${s.tierColor}">${s.tier.split(' · ')[1]||s.tier}</span>
            <p style="margin:0;font-size:12.5px;line-height:1.5;color:var(--nb-muted)">Score derivato da PF full/holdout + regime — non è Sharpe/DSR accademico (non ancora persistiti lato Python).</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <span class="nb-badge">${s.tier.split(' · ')[0]}</span>
              <span class="nb-badge" style="color:var(--nb-accent);border-color:rgba(232,193,115,.45)">PF full ${(info.full?.pf??0).toFixed(2)}</span>
              <span class="nb-badge">PF holdout ${(info.holdout?.pf??0).toFixed(2)}</span>
            </div>
          </div>
        </div>

        <hr class="nb-hr">
        <div class="nb-lbl">Struttura dell'edge</div>
        <div class="nb-stack">
          ${bar('Consistenza recente', s.consistency, `holdout PF ${(info.holdout?.pf??0).toFixed(2)} su full PF ${(info.full?.pf??0).toFixed(2)}`)}
          ${bar('Durabilità', s.durability, `PF holdout ${(info.holdout?.pf??0).toFixed(2)}`)}
          ${bar('Copertura mercato', s.coverage, s.regimeNote)}
          ${bar('Ampiezza campione', s.sample, `${info.n_trades||0} trade nel periodo testato`)}
        </div>

        ${periods ? `
        <hr class="nb-hr">
        <div class="nb-stack nb-stack--tight">
          <div class="nb-lbl">Periodi profittevoli</div>
          <div class="nb-cols" style="height:84px">${periods.cols}</div>
          <div class="nb-between nb-mono" style="font-size:11px;color:var(--nb-muted)"><span>${periods.profitable} su ${periods.total} in profitto</span><span class="nb-up">${Math.round(periods.profitable/periods.total*100)}%</span></div>
        </div>` : ''}

        <hr class="nb-hr">
        <div class="nb-between" style="align-items:baseline">
          <span class="nb-lbl">Fortuna o edge · resample bootstrap</span>
          ${boot ? `<span class="nb-num nb-up" style="font-size:16px;font-weight:600">${Math.round(boot.profitable*100)}%</span>` : ''}
        </div>
        ${boot ? `
        <div class="nb-cols" style="height:80px">${gnHistCols(boot)}</div>
        <p style="margin:0;font-size:11.5px;line-height:1.5;color:var(--nb-muted)">Rimescolando la sequenza dei delta reali dell'equity curve, ${Math.round(boot.profitable*100)}% delle ${boot.results.length.toLocaleString('it-IT')} simulazioni resta in profitto (mediana ${brFmt(boot.median,0)}) — il risultato non dipende da una singola serie fortunata.</p>
        ` : `<p style="margin:0;font-size:11.5px;color:var(--nb-muted)">Equity curve troppo corta per un resample affidabile.</p>`}

        ${regime ? `
        <hr class="nb-hr">
        <div class="nb-lbl">Elementi scoperti · regimi con miglior fit</div>
        <div class="nb-metrics" style="grid-template-columns:repeat(auto-fill,minmax(130px,1fr))">
          ${Object.entries(regime.observed||{}).sort((a,b)=>b[1].pf-a[1].pf).slice(0,4).map(([reg,st])=>`
            <div class="nb-metric"><span class="nb-metric__k">${reg}</span><span class="nb-metric__v" style="font-size:14px">PF ${Math.min(st.pf,99.9).toFixed(2)}</span><span style="font-size:10px;color:var(--nb-muted)">n=${st.n}</span></div>`).join('')}
        </div>` : ''}
      </div>
    </div>
  `;
}

function gnOpen(key){
  openOvl('genomesheet');
  if(brData) gnRender(key);
  else brLoad().then(()=> gnRender(key));
}

// ── Wiring (listener delegato — coerente con la regola "mai onclick su HTML rigenerato") ──
document.addEventListener('click', (e)=>{
  if(e.target.closest('[data-action="open-backtest-report"]')){
    openOvl('brsheet');
    if(!brData) brLoad();
    else brRenderAll();
    return;
  }
  const runBtn = e.target.closest('[data-br-run]');
  if(runBtn){ brRunBacktest(runBtn.dataset.brRun); return; }
  const toggleBtn = e.target.closest('[data-br-toggle]');
  if(toggleBtn){ brToggleBlock(toggleBtn.dataset.brToggle, toggleBtn.dataset.disabled === 'true'); return; }
  const genomeBtn = e.target.closest('[data-br-genome]');
  if(genomeBtn){ gnOpen(genomeBtn.dataset.brGenome); return; }
  if(e.target.closest('#br-view-active')){ brHeroMode='active'; brHeroKey=null; brSetViewBtn('active'); brRenderHero(); return; }
  if(e.target.closest('#br-view-full')){ brHeroMode='full'; brHeroKey=null; brSetViewBtn('full'); brRenderHero(); return; }
  if(e.target.closest('#btn-br-refresh')){ brLoad(); return; }
});
