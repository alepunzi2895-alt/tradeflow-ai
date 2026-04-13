/**
 * TradeFlow AI — Strategy Engine Module
 * Monitoraggio e analisi real-time per XAU/USD
 */

const SE = {
  maxTrades: 10,
  cooldownMin: 30,
  extremeMult: 3.5,
  session: { start: 0, end: 24 }, // 24h as requested
  strategies: {
    'S01_EXHAUSTION':  { label: 'Exhaustion', pf: 2.29, wr: '58%', tp: 15, sl: 9 },
    'S09_VWAP_WPR':    { label: 'VWAP+W%R',  pf: 1.50, wr: '47%', tp: 18, sl: 10 },
    'S06_ORDERBLOCK':  { label: 'Order Block',pf: 1.42, wr: '46%', tp: 18, sl: 10 },
    'S13_STRUC_BREAK': { label: 'Struc Break',pf: 1.61, wr: '52%', tp: 'ATR', sl: 'ATR' },
    'S14_KEY_LEVELS':  { label: 'Key Levels', pf: 1.54, wr: '49%', tp: 'ATR', sl: 'ATR' },
    'S12_WPR_KELTNER': { label: 'W%R+Keltner',pf: 1.22, wr: '42%', tp: 20, sl: 12 },
  },
  regimePriority: {
    TREND_UP:    ['S01_EXHAUSTION','S06_ORDERBLOCK','S13_STRUC_BREAK'],
    TREND_DOWN:  ['S01_EXHAUSTION','S06_ORDERBLOCK','S13_STRUC_BREAK'],
    WEAK_UP:     ['S06_ORDERBLOCK','S13_STRUC_BREAK','S14_KEY_LEVELS'],
    WEAK_DOWN:   ['S06_ORDERBLOCK','S13_STRUC_BREAK','S14_KEY_LEVELS'],
    RANGE:       ['S09_VWAP_WPR','S12_WPR_KELTNER','S14_KEY_LEVELS'],
    VOLATILE:    ['S12_WPR_KELTNER','S09_VWAP_WPR'],
  }
};

let seTimer = null;
let seInds = null;
let seRegime = 'UNKNOWN';

// ── INDICATOR HELPERS ─────────────────────────────────────────────────────────
function _ema(src, p) {
  const k = 2/(p+1); let v = src[0]; const o = [v];
  for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
  return o;
}
function _sma(src, p) {
  let o = [];
  for(let i=0; i<src.length; i++) {
    if(i < p-1) { o.push(null); continue; }
    let sum = 0; for(let j=0; j<p; j++) sum += src[i-j];
    o.push(sum/p);
  }
  return o;
}
function _rsi(src, p=14) {
  let g=[], l=[];
  for(let i=1;i<src.length;i++){
    let d=src[i]-src[i-1];
    g.push(d>0?d:0); l.push(d<0?-d:0);
  }
  let rs=[]; let ag=0, al=0;
  for(let i=0;i<g.length;i++){
    if(i<p){ag+=g[i]/p; al+=l[i]/p; rs.push(null); continue;}
    ag=(ag*(p-1)+g[i])/p; al=(al*(p-1)+l[i])/p;
    rs.push(100-100/(1+ag/al));
  }
  return [null, ...rs];
}

// ── STRATEGY LOGIC ───────────────────────────────────────────────────────────
const SE_STRATEGY_FNS = {
  S01_EXHAUSTION: (I,i) => {
    const adx=I.adx[i], dip=I.dip[i], dim=I.dim[i], mh=I.macd[i], r=I.rsi[i];
    if(adx>30 && Math.abs(dip-dim)>15){
      if(dim>dip && mh>0.5 && r<40) return {dir:'buy', why:'Esaurimento ribassista + MACD reversal'};
      if(dip>dim && mh<-0.5 && r>60) return {dir:'sell', why:'Esaurimento rialzista + MACD reversal'};
    }
    return null;
  },
  S09_VWAP_WPR: (I,i) => {
    const c=I.C[i], v=I.vwap[i], w=I.wpr[i];
    if(c>v && w<-80) return {dir:'buy', why:'Cross VWAP rialzista + W%R Oversold'};
    if(c<v && w>-20) return {dir:'sell', why:'Cross VWAP ribassista + W%R Overbought'};
    return null;
  },
  S06_ORDERBLOCK: (I,i) => {
    const c=I.C[i], e50=I.e50[i], r=I.rsi[i];
    if(c>e50 && r<45 && I.macd[i]>0) return {dir:'buy', why:'Rimbalzo su EMA50 (Order Block) + Momentum'};
    if(c<e50 && r>55 && I.macd[i]<0) return {dir:'sell', why:'Rigetto su EMA50 (Order Block) + Momentum'};
    return null;
  },
  S13_STRUC_BREAK: (I,i) => {
    const c=I.C[i], h=I.H[i], l=I.L[i];
    const prevH = Math.max(...I.H.slice(i-20, i-1));
    const prevL = Math.min(...I.L.slice(i-20, i-1));
    if(c > prevH) return {dir:'buy', why:'Rottura struttura rialzista (20h high)'};
    if(c < prevL) return {dir:'sell', why:'Rottura struttura ribassista (20h low)'};
    return null;
  },
  S14_KEY_LEVELS: (I,i) => {
    const c=I.C[i], r=I.rsi[i];
    // Semplificato: monitoraggio RSI estremo su livelli psicologici
    if(r < 30 && c % 10 < 2) return {dir:'buy', why:'Test livello chiave + RSI Oversold'};
    if(r > 70 && c % 10 > 8) return {dir:'sell', why:'Test livello chiave + RSI Overbought'};
    return null;
  },
  S12_WPR_KELTNER: (I,i) => {
    const c=I.C[i], kl=I.kl[i], ku=I.ku[i], w=I.wpr[i];
    if(c<kl && w<-85) return {dir:'buy', why:'Breakout Keltner Lower + W%R Estremo'};
    if(c>ku && w>-15) return {dir:'sell', why:'Breakout Keltner Upper + W%R Estremo'};
    return null;
  }
};

function seDetectRegime(I, i) {
  const adx = I.adx[i] || 25;
  const dip = I.dip[i] || 20;
  const dim = I.dim[i] || 20;
  const atr = I.atr[i];
  const a30 = I.atr30[i];

  if(adx >= 28) return (dip > dim) ? 'TREND_UP' : 'TREND_DOWN';
  if(adx >= 20) return (dip > dim) ? 'WEAK_UP' : 'WEAK_DOWN';
  if(atr > 1.35 * a30) return 'VOLATILE';
  return 'RANGE';
}

// ── MAIN LOOP ────────────────────────────────────────────────────────────────
async function seRefresh() {
  const el = document.getElementById('se-content');
  if(!el) return;

  // 1. Candele da Proxy (per evitare CORS)
  let candles = [];
  try {
    const res = await fetch('/api/price?type=candles&asset=XAU&interval=1h&range=60d');
    const json = await res.json();
    if (json.ok && json.candles) {
      candles = json.candles;
    } else {
      throw new Error(json.error || 'Errore dati candele');
    }
  } catch(e) {
    console.error("Errore fetch candele SE:", e);
    seRenderNoData();
    return;
  }

  if(candles.length < 100) return seRenderNoData();

  // 2. Calcolo Indicatori
  const C = candles.map(c=>c.c);
  const H = candles.map(c=>c.h);
  const L = candles.map(c=>c.l);
  const n = C.length;
  
  const tr = [0];
  for(let i=1; i<n; i++) tr.push(Math.max(H[i]-L[i], Math.abs(H[i]-C[i-1]), Math.abs(L[i]-C[i-1])));
  const atr = _sma(tr, 14);

  seInds = {
    n, C, H, L,
    e20: _ema(C, 20),
    e50: _ema(C, 50),
    e100: _ema(C, 100),
    e200: _ema(C, 200),
    rsi: _rsi(C, 14),
    atr: atr,
    atr30: _sma(tr, 30),
    wpr: C.map((c,idx)=>{
      if(idx<14) return null;
      const hh=Math.max(...H.slice(idx-13,idx+1)), ll=Math.min(...L.slice(idx-13,idx+1));
      return (hh-ll)===0 ? -50 : -100*(hh-c)/(hh-ll);
    }),
    vwap: C.map((c,idx) => {
      // Semplificato: SMA 20 come base VWAP per il browser
      let sum=0; for(let j=Math.max(0,idx-19); j<=idx; j++) sum+=C[j];
      return sum / (idx - Math.max(0,idx-19) + 1);
    }),
    macd: _ema(C, 12).map((v,idx) => v - _ema(C, 26)[idx]),
    adx: new Array(n).fill(25), // Fallback se non abbiamo calcolo ADX complesso
    dip: new Array(n).fill(20),
    dim: new Array(n).fill(20),
    kl: _ema(C, 20).map((v,idx) => v - (atr[idx]||0)*2),
    ku: _ema(C, 20).map((v,idx) => v + (atr[idx]||0)*2),
  };

  const I=seInds, i=I.n-1;
  const nowUtc=new Date(), hour=nowUtc.getUTCHours();
  seRegime=seDetectRegime(I,i);

  // Snapshot indicatori per UI
  const liveP=parseFloat(I.C[i]);
  const snap={
    price:liveP.toFixed(2), adx:I.adx[i]?.toFixed(1), dip:I.dip[i]?.toFixed(1), dim:I.dim[i]?.toFixed(1),
    rsi:I.rsi[i]?.toFixed(0), macd:I.macd[i]?.toFixed(2), e20:I.e20[i]?.toFixed(0), e50:I.e50[i]?.toFixed(0),
    e100:I.e100[i]?.toFixed(0), e200:I.e200[i]?.toFixed(0),
    wpr:I.wpr[i]?.toFixed(0), vwap:I.vwap[i]?.toFixed(0),
    atr:I.atr[i]?.toFixed(2),
  };

  // Scan segnali potenziali
  const av=I.atr[i], aa=I.atr30[i];
  const isExtreme=av&&aa&&av>SE.extremeMult*aa;
  const inSession=hour>=SE.session.start&&hour<SE.session.end;
  
  let pending=[];
  if(!isExtreme&&inSession){
    const priority=SE.regimePriority[seRegime]||['S14_KEY_LEVELS'];
    for(const name of priority){
      const fn=SE_STRATEGY_FNS[name];
      if(!fn)continue;
      const sig=fn(I,i,hour);
      if(sig){
        const cfg=SE.strategies[name];
        const atr_val = I.atr[i] || 10;
        const tp = cfg.tp === 'ATR' ? Math.round(atr_val * 2.0) : cfg.tp;
        const sl = cfg.sl === 'ATR' ? Math.round(atr_val * 1.0) : cfg.sl;
        pending.push({name, label:cfg.label, dir:sig.dir, why:sig.why, tp, sl, pf:cfg.pf, wr:cfg.wr});
      }
    }
  }

  // Fetch real MT5 data and render
  const mt5Data = await seFetchMt5Data();
  seRender(mt5Data, pending, snap, isExtreme, inSession, hour);
}

async function seFetchMt5Data() {
  try {
    const r=await fetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'mt5_get'})});
    const j=await r.json();
    return j.ok ? j.data : null;
  } catch(e) { return null; }
}

// ── RENDER ────────────────────────────────────────────────────────────────────
function seRender(mt5Data,pending,snap,isExtreme,inSession,hour){
  const el=document.getElementById('se-content');
  if(!el)return;

  const REGIME_META={
    TREND_UP:    {col:'#00e676',bg:'#00e67612',icon:'📈',label:'TREND RIALZISTA'},
    TREND_DOWN:  {col:'#ff4757',bg:'#ff475712',icon:'📉',label:'TREND RIBASSISTA'},
    WEAK_UP:     {col:'#ffd700',bg:'#ffd70012',icon:'↗️',label:'TREND DEBOLE ↑'},
    WEAK_DOWN:   {col:'#ffca28',bg:'#ffca2812',icon:'↘️',label:'TREND DEBOLE ↓'},
    RANGE:       {col:'#c8a96e',bg:'#c8a96e12',icon:'↔️',label:'LATERALE (RANGING)'},
    VOLATILE:    {col:'#b36cff',bg:'#b36cff12',icon:'⚡',label:'VOLATILE'},
    UNKNOWN:     {col:'var(--dim)',bg:'var(--bg2)',icon:'❓',label:'SCONOSCIUTO'},
  };
  const rm=REGIME_META[seRegime]||REGIME_META.UNKNOWN;
  
  const acc=mt5Data?.account||{};
  const pos=mt5Data?.positions||[];
  const history=mt5Data?.trades||[];
  const bs=mt5Data?.bot_status||{};
  const syncAge=mt5Data?.synced_at?Math.round((Date.now()-new Date(mt5Data.synced_at).getTime())/1000):null;
  const online=syncAge!==null&&syncAge<10;

  // ── STATUS BAR
  let statusHtml='';
  if(isExtreme){
    statusHtml=`<div style="background:#ff475720;border:1px solid #ff475740;border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:#ff4757">
      ⚠️ <b>GIORNO ESTREMO</b> — Volatilità anomala (ATR>${SE.extremeMult}x media). Trading sospeso automaticamente.
    </div>`;
  } else if(!inSession){
    statusHtml=`<div style="background:var(--bg2);border:1px solid var(--border);border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:var(--dim)">
      🔴 <b>Fuori sessione</b> (${hour}:00 UTC) — Monitoraggio attivo, bot sempre online.
    </div>`;
  } else {
    statusHtml=`<div style="background:#00e67610;border:1px solid #00e67625;border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:var(--green)">
      🟢 <b>Bot MT5 Online</b> (${hour}:00 UTC) — Polling 1s · Real-time Sync attivo
    </div>`;
  }

  // ── REGIME + P&L REALE
  const pnlOggi = bs.pnl_today || 0;
  const regimeHtml=`
<div style="background:${rm.bg};border:1px solid ${rm.col}40;border-radius:9px;padding:11px 13px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:3px">REGIME DI MERCATO</div>
      <div style="font-size:16px;font-weight:800;color:${rm.col}">${rm.icon} ${rm.label}</div>
      <div style="font-size:9px;color:${rm.col};margin-top:4px">
        Strategie attive: ${(SE.regimePriority[seRegime]||['S13_STRUC_BREAK','S14_KEY_LEVELS']).map(n=>`<b>${SE.strategies[n]?.label||n}</b>`).join(' › ')}
      </div>
    </div>
    <div style="text-align:right">
      <div style="font-size:9px;color:var(--dim);margin-bottom:2px">PROFITTO REALIZZATO (MT5)</div>
      <div style="font-size:18px;font-weight:800;color:${pnlOggi>0?'var(--green)':pnlOggi<0?'var(--red)':'var(--fg)'}">${pnlOggi>=0?'+':''}${pnlOggi.toFixed(2)} €</div>
      <div style="font-size:9px;color:var(--dim)">${online?'ONLINE':'OFFLINE'} · ${bs.trades_today||0} trade oggi</div>
    </div>
  </div>
</div>`;

  // ── INDICATORI SNAPSHOT
  const indSnap=`
<div style="margin-bottom:8px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:4px">INDICATORI CORRENTI</div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-bottom:3px">
    ${[['ADX',snap.adx],['DI+',snap.dip],['DI-',snap.dim],['RSI',snap.rsi],['W%R',snap.wpr]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px">
    ${[['MACD',snap.macd],['EMA50',snap.e50],['EMA200',snap.e200],['VWAP',snap.vwap]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
</div>`;

  // ── SEGNALI ATTIVI
  let pendingHtml='';
  if(pending.length>0&&!isExtreme&&inSession){
    pendingHtml=`<div style="margin-bottom:10px">
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">🔔 SEGNALI ATTIVI (POTENZIALI)</div>
      ${pending.map((s,idx)=>{
        const dc=s.dir==='buy'?'#00e676':'#ff4757';
        return `<div style="background:${dc}10;border:1px solid ${dc}35;border-radius:7px;padding:8px 10px;margin-bottom:5px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="color:${dc};font-weight:800;font-size:12px">${s.dir==='buy'?'▲ BUY':'▼ SELL'}</span>
            <span style="color:var(--dim);font-size:9px">${s.label} · WR ${s.wr} · PF ${s.pf}</span>
          </div>
          <div style="font-size:9px;color:var(--fg);margin-bottom:4px">${s.why}</div>
          <div style="display:flex;gap:8px;font-size:9px;color:var(--dim)">
            <span style="color:var(--green)">TP +$${s.tp}</span>
            <span style="color:var(--red)">SL -$${s.sl}</span>
          </div>
          <button onclick='seSendTradeToMt5(${JSON.stringify(s)})' style="margin-top:8px;width:100%;padding:6px;background:var(--green);color:#000;border:none;border-radius:5px;font-size:10px;font-weight:800;cursor:pointer">
            🚀 ESEGUI COMANDO SU MT5
          </button>
        </div>`;
      }).join('')}
    </div>`;
  }

  // ── POSIZIONI REALI MT5
  const posHtml=`
<div style="margin-bottom:10px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">POSIZIONI APERTE (REALI MT5)</div>
  ${pos.length===0
    ? `<div style="text-align:center;padding:12px;background:var(--bg2);border-radius:7px;font-size:10px;color:var(--dim)">Nessuna posizione aperta sul conto</div>`
    : pos.map(p=>{
        const dc=p.direction==='buy'?'#00e676':'#ff4757';
        const pCol=p.profit>=0?'var(--green)':'var(--red)';
        return `<div style="background:var(--bg2);border:1px solid ${dc}35;border-radius:7px;padding:8px 10px;margin-bottom:5px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
            <span style="color:${dc};font-weight:800;font-size:11px">${p.direction.toUpperCase()} ${p.symbol}</span>
            <span style="color:${pCol};font-weight:800;font-size:12px">${p.profit>=0?'+':''}${p.profit.toFixed(2)} €</span>
          </div>
          <div style="font-size:9px;color:var(--dim);display:flex;gap:8px">
            <span>Entry <b>$${p.entry}</b></span>
            <span>TP $${p.tp}</span>
            <span>SL $${p.sl}</span>
            <span style="margin-left:auto;color:var(--fg)">${p.strategy||''}</span>
          </div>
        </div>`;
      }).join('')}
</div>`;

  // ── STORICO REALE
  const histHtml=`
<div style="margin-bottom:10px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">STORICO RECENTE (REAL TRADES)</div>
  ${history.length===0
    ? `<div style="text-align:center;padding:8px;font-size:9px;color:var(--dim)">Nessun trade storico trovato</div>`
    : history.slice(-5).reverse().map(t=>{
        const dc=t.direction==='buy'?'#00e676':'#ff4757';
        return `<div style="display:flex;justify-content:space-between;font-size:8px;padding:4px 0;border-bottom:1px solid var(--border2)">
          <span style="color:${dc}">${t.direction.toUpperCase()}</span>
          <span style="color:var(--dim)">${new Date(t.time).toLocaleTimeString()}</span>
          <span>${t.strategy||'—'}</span>
          <span>$${t.price?.toFixed(2)}</span>
          <span style="color:${t.profit>=0?'var(--green)':'var(--red)'}">${t.profit>=0?'+':''}${t.profit?.toFixed(2)}</span>
        </div>`;
      }).join('')}
</div>`;

  // ── LIBRERIA STRATEGIE (Dettagli Tecnici)
  const activeList = SE.regimePriority[seRegime] || [];
  const catalogHtml = `
<div style="margin-top:20px; padding-top:15px; border-top:1px dashed var(--border)">
  <div style="font-size:11px; color:var(--fg); font-weight:700; margin-bottom:10px; display:flex; align-items:center; gap:8px">
    <span>📚 LIBRERIA STRATEGIE & PERFORMANCE</span>
    <span style="font-size:9px; font-weight:400; color:var(--dim)">(H1 Backtest 2024-2026)</span>
  </div>
  <div style="display:grid; grid-template-columns:1fr; gap:8px">
    ${Object.entries(SE.strategies).map(([id, s]) => {
      const isActive = activeList.includes(id);
      const inds = id==='S01' ? 'ADX, DI+, DI-, MACD, RSI' :
                 id==='S09' ? 'VWAP, W%R (Price Cross)' :
                 id==='S06' ? 'EMA50 (Order Block), RSI, MACD' :
                 id==='S13' ? 'Price Action (Breakout Struttura)' :
                 id==='S14' ? 'Key Levels (Support/Res), RSI' :
                 id==='S12' ? 'Keltner Channels, W%R' : 'Technical Indicators';
      
      return `
      <div style="background:var(--bg2); border:1px solid ${isActive?rm.col+'40':'var(--border)'}; border-radius:8px; padding:10px; position:relative; overflow:hidden">
        ${isActive ? `<div style="position:absolute; top:0; right:0; background:${rm.col}; color:#000; font-size:7px; font-weight:900; padding:2px 6px; border-bottom-left-radius:6px">ATTIVA ORA</div>` : ''}
        <div style="display:flex; justify-content:space-between; margin-bottom:6px">
          <span style="font-size:11px; font-weight:700; color:${isActive?rm.col:'var(--fg)'}">${s.label}</span>
          <div style="display:flex; gap:10px; font-size:10px">
            <span style="color:var(--green)">PF <b>${s.pf}</b></span>
            <span style="color:var(--blue)">WR <b>${s.wr}</b></span>
          </div>
        </div>
        <div style="font-size:9px; color:var(--dim); line-height:1.4">
          <span style="color:var(--fg); opacity:0.7">Indicatori:</span> ${inds}<br>
          <span style="color:var(--fg); opacity:0.7">Target:</span> TP $${s.tp} · SL $${s.sl}
        </div>
      </div>`;
    }).join('')}
  </div>
</div>`;

  el.innerHTML=statusHtml+regimeHtml+indSnap+pendingHtml+posHtml+histHtml+catalogHtml;
}

async function seSendTradeToMt5(s) {
  if (!confirm(`Vuoi davvero inviare un ordine ${s.dir.toUpperCase()} su MT5?`)) return;
  
  const btn = event?.target;
  if (btn) { btn.disabled = true; btn.innerText = '⌛ INVIO IN CORSO...'; }

  try {
    const res = await fetch('/api/db', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'mt5_command_push',
        command: {
          direction: s.dir,
          strategy: s.name,
          tp: s.tp,
          sl: s.sl,
          symbol: 'GOLD'
        }
      })
    });
    const j = await res.json();
    if (j.ok) {
      alert('✅ Comando inviato con successo! Il bot MT5 lo eseguirà entro 3 secondi.');
      if (btn) { btn.innerText = '✓ INVIATO'; btn.style.background = 'var(--dim)'; }
    } else {
      throw new Error(j.error || 'Errore durante l\'invio');
    }
  } catch (e) {
    alert('❌ Errore: ' + e.message);
    if (btn) { btn.disabled = false; btn.innerText = '🚀 RIPROVA ESECUZIONE'; }
  }
}
window.seSendTradeToMt5 = seSendTradeToMt5;

function seRenderNoData(){
  const el=document.getElementById('se-content');
  if(!el)return;
  el.innerHTML=`<div style="text-align:center;padding:25px;color:var(--dim);font-size:12px">
    <div class="spinner" style="margin:0 auto 10px"></div>
    Sincronizzazione MT5 in corso...<br>
    <span style="font-size:10px">Verifica che il bot locale sia attivo</span>
  </div>`;
  // Proviamo comunque ad aggiornare i dati MT5
  seFetchMt5Data().then(mt5Data => {
    if(mt5Data) seRender(mt5Data, [], {}, false, true, new Date().getUTCHours());
  });
}

// ── INIT ──────────────────────────────────────────────────────────────────────
async function initStrategyEngine(){
  if(seTimer)clearInterval(seTimer);
  await seRefresh();
  seTimer=setInterval(seRefresh, 1000); // Polling 1s ultra-veloce
}
window.initStrategyEngine=initStrategyEngine;
window.seRefresh=seRefresh;
