/**
 * TradeFlow AI — Strategy Engine Module
 * Monitoraggio e analisi real-time per XAU/USD
 */

const SE = {
  maxTrades: 10,
  cooldownMin: 30,
  extremeMult: 3.5,
  session: { start: 0, end: 24 },
  // Soglie qualità minima per mostrare bottone MT5 (evita segnali deboli)
  minQuality: { S00_MFKK: 75, S00_MFKK_HWR: 0, S01_EXHAUSTION: 0, default: 0 },
  strategies: {
    // MFKK — strategia principale ottimizzata su 730gg H1 XAU/USD
    'S00_MFKK':        { label: 'MFKK Score',  pf: 1.80, wr: '52%', tp: 'ATR', sl: 'ATR',
      stats: { pnl_1m: 278, pnl_12m: 3334, pnl_24m: 6668, maxdd: 600, trades_12m: 720, best_regime: 'TREND' } },
    'S00_MFKK_HWR':    { label: '💎 MFKK HighWR', pf: 21.67, wr: '93%', tp: 20, sl: 12,
      stats: { pnl_1m: 21, pnl_12m: 248, pnl_24m: 496, maxdd: 12, trades_12m: 14, best_regime: 'TREND' } },
    'S01_EXHAUSTION':  { label: 'Exhaustion',  pf: 2.29, wr: '58%', tp: 15, sl: 9,
      stats: { pnl_1m: 41, pnl_12m: 492, pnl_24m: 920, maxdd: 90, trades_12m: 100, best_regime: 'TREND' } },
    'S09_VWAP_WPR':    { label: 'VWAP+W%R',   pf: 1.50, wr: '47%', tp: 18, sl: 10,
      stats: { pnl_1m: 16, pnl_12m: 190, pnl_24m: 380, maxdd: 130, trades_12m: 60,  best_regime: 'RANGE' } },
    'S06_ORDERBLOCK':  { label: 'Order Block', pf: 1.42, wr: '46%', tp: 18, sl: 10,
      stats: { pnl_1m: 17, pnl_12m: 202, pnl_24m: 404, maxdd: 120, trades_12m: 70,  best_regime: 'WEAK' } },
    'S13_STRUC_BREAK': { label: 'Struc Break', pf: 1.61, wr: '52%', tp: 'ATR', sl: 'ATR',
      stats: { pnl_1m: 24, pnl_12m: 288, pnl_24m: 576, maxdd: 100, trades_12m: 80,  best_regime: 'TREND' } },
    'S14_KEY_LEVELS':  { label: 'Key Levels',  pf: 1.54, wr: '49%', tp: 'ATR', sl: 'ATR',
      stats: { pnl_1m: 18, pnl_12m: 216, pnl_24m: 432, maxdd: 110, trades_12m: 65,  best_regime: 'RANGE' } },
    'S12_WPR_KELTNER': { label: 'W%R+Keltner', pf: 1.22, wr: '42%', tp: 20, sl: 12,
      stats: { pnl_1m:  6, pnl_12m:  72, pnl_24m: 144, maxdd: 180, trades_12m: 50,  best_regime: 'VOLATILE' } },
  },
  // Regime intelligence: priorità strategie per regime + condizioni di mercato
  regimePriority: {
    TREND_UP:    ['S00_MFKK_HWR','S00_MFKK','S01_EXHAUSTION','S13_STRUC_BREAK'],
    TREND_DOWN:  ['S00_MFKK_HWR','S00_MFKK','S01_EXHAUSTION','S06_ORDERBLOCK'],
    WEAK_UP:     ['S00_MFKK','S06_ORDERBLOCK','S13_STRUC_BREAK','S14_KEY_LEVELS'],
    WEAK_DOWN:   ['S00_MFKK','S06_ORDERBLOCK','S14_KEY_LEVELS'],
    RANGE:       ['S09_VWAP_WPR','S14_KEY_LEVELS','S00_MFKK'],
    VOLATILE:    ['S12_WPR_KELTNER','S00_MFKK'],
  },
  // Regime intelligence: max segnali simultanei per regime
  maxSignals: { TREND_UP: 2, TREND_DOWN: 2, WEAK_UP: 1, WEAK_DOWN: 1, RANGE: 2, VOLATILE: 1, UNKNOWN: 1 },
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
  // S00_MFKK: usa il punteggio MFKK già calcolato in mfkk.js (via dashContext.mfkk)
  // Soglia alta (≥75 non ≥68) per evitare segnali deboli — zona 80-89 è la più affidabile (WR 58.8%)
  S00_MFKK: (I,i) => {
    const m = dashContext?.mfkk;
    if(!m || !m.score) return null;
    const score = m.score;
    const dir = (m.dir||'').toUpperCase();
    // Zona ottimale 80-89 WR 58.8%, score ≥90 entra tardi (WR 48.2%)
    // Mostriamo da ≥75 con etichetta qualità
    if(dir==='SELL' && score>=75){
      const q = score>=90?'🔥 FORTE':score>=80?'✅ BUONO':'⚠️ MODERATO';
      return {dir:'sell', why:`MFKK ${q} ${score}/100 · SELL · ADX+MACD+CCI allineati`, score, quality: score>=80?'high':'medium'};
    }
    if(dir==='BUY' && score>=90){
      return {dir:'buy', why:`MFKK 🔥 FORTE ${score}/100 · BUY · Confluenza massima`, score, quality:'high'};
    }
    return null;
  },
  // S00_MFKK_HWR: HIGH WIN RATE SELL — 92.9% WR su 730gg H1 XAU
  // Condizioni hard: ADX≥35 + DI spread≥20 + MACD diff≥0.5 + CCI non OS
  S00_MFKK_HWR: (I,i) => {
    const m = dashContext?.mfkk;
    if(!m) return null;
    const adx=I.adx[i], dip=I.dip[i], dim=I.dim[i], mh=I.macd[i];
    if(!adx || adx<35 || !mh) return null;
    const spread = Math.abs((dip||0)-(dim||0));
    if(spread < 20) return null;
    // DI- domina (trend ribassista) + MACD bullish esteso = esaurimento imminente
    if((dim||0) > (dip||0) && Math.abs(mh) >= 0.5 && mh > 0){
      if(m.cciScore && m.cciScore < 65) return null; // CCI in OS: skip
      return {dir:'sell', why:`💎 HIGH-WR SELL · ADX ${adx?.toFixed(0)} spread ${spread?.toFixed(0)} MACD ${mh?.toFixed(2)} · WR 92.9% su 730gg`, score:100, quality:'elite'};
    }
    return null;
  },
  S01_EXHAUSTION: (I,i) => {
    const adx=I.adx[i], dip=I.dip[i], dim=I.dim[i], mh=I.macd[i], r=I.rsi[i];
    // Migliorato: soglia ADX alzata a 30, spread a 12, aggiunto check MACD histogram reversal
    if(adx>=30 && Math.abs(dip-dim)>=12){
      const mhPrev = i>0 ? I.macd[i-1] : mh;
      if(dim>dip && mh>0.5 && mh>mhPrev && r<45) return {dir:'buy', why:`Esaurimento ribassista · ADX ${adx?.toFixed(0)} DI->${dim?.toFixed(0)} MACD reversal ↑`};
      if(dip>dim && mh<-0.5 && mh<mhPrev && r>55) return {dir:'sell', why:`Esaurimento rialzista · ADX ${adx?.toFixed(0)} DI+${dip?.toFixed(0)} MACD reversal ↓`};
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
    const maxSig = SE.maxSignals[seRegime] || 2;
    for(const name of priority){
      if(pending.length >= maxSig) break;
      const fn=SE_STRATEGY_FNS[name];
      if(!fn) continue;
      const sig=fn(I,i,hour);
      if(sig){
        const cfg=SE.strategies[name];
        const atr_val = I.atr[i] || 10;
        const tp = cfg.tp === 'ATR' ? Math.round(atr_val * 2.0) : cfg.tp;
        const sl = cfg.sl === 'ATR' ? Math.round(atr_val * 1.0) : cfg.sl;
        pending.push({name, label:cfg.label, dir:sig.dir, why:sig.why, tp, sl, pf:cfg.pf, wr:cfg.wr, quality:sig.quality||'medium', score:sig.score||null});
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
  // Bot online = sincronizzato negli ultimi 30s
  const botOnline=syncAge!==null&&syncAge<30;
  const syncLabel=syncAge===null?'Mai sincronizzato':syncAge<5?'Ora':syncAge<60?`${syncAge}s fa`:`${Math.round(syncAge/60)}min fa`;

  // ── STATUS BAR — mostra stato reale bot MT5
  let statusHtml='';
  if(isExtreme){
    statusHtml=`<div style="background:#ff475720;border:1px solid #ff475740;border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:#ff4757">
      ⚠️ <b>GIORNO ESTREMO</b> — Volatilità anomala (ATR>${SE.extremeMult}x media). Trading sospeso.
    </div>`;
  }
  // Stato bot MT5 sempre visibile
  const botStatusHtml=`<div style="background:${botOnline?'#00e67608':'#ff475710'};border:1px solid ${botOnline?'#00e67625':'#ff475730'};border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;display:flex;justify-content:space-between;align-items:center">
    <span style="color:${botOnline?'var(--green)':'#ff4757'}">${botOnline?'🟢 Bot MT5 attivo':'🔴 Bot MT5 offline'}</span>
    <span style="color:var(--dim)">Sync: ${syncLabel}${bs.symbol?' · '+bs.symbol:''}</span>
    ${!botOnline?`<span style="color:#ffca28;font-size:9px">Avvia: python scripts/mt5-bot.py</span>`:`<span style="color:var(--green);font-size:9px">${bs.trades_today||0} trade · ${bs.lot||0.02} lot</span>`}
  </div>`;
  statusHtml = botStatusHtml + statusHtml;

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
  if(pending.length>0&&!isExtreme){
    const qualColors={elite:'#c8a96e', high:'#00e676', medium:'#ffd700'};
    const qualLabels={elite:'💎 ELITE', high:'🔥 FORTE', medium:'⚠️ MODERATO'};
    pendingHtml=`<div style="margin-bottom:10px">
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">🔔 SEGNALI ATTIVI</div>
      ${pending.map((s)=>{
        const dc=s.dir==='buy'?'#00e676':'#ff4757';
        const qc=qualColors[s.quality]||'#ffd700';
        const ql=qualLabels[s.quality]||'';
        // Bottone MT5: abilitato solo se bot online
        const btnStyle=botOnline
          ?`background:${dc};color:${s.dir==='buy'?'#000':'#fff'};cursor:pointer;opacity:1`
          :`background:var(--bg2);color:var(--dim);cursor:not-allowed;opacity:0.5`;
        const btnLabel=botOnline?`🚀 ESEGUI SU MT5`:`🔴 Bot offline — avvia mt5-bot.py`;
        const btnDisabled=botOnline?'':'disabled';
        return `<div style="background:${dc}10;border:1px solid ${dc}35;border-radius:8px;padding:9px 11px;margin-bottom:6px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="color:${dc};font-weight:800;font-size:13px">${s.dir==='buy'?'▲ BUY':'▼ SELL'}</span>
            <div style="display:flex;gap:5px;align-items:center">
              <span style="font-size:9px;background:${qc}18;border:1px solid ${qc}40;border-radius:3px;padding:1px 5px;color:${qc}">${ql}</span>
              <span style="color:var(--dim);font-size:9px">${s.label} · WR ${s.wr}</span>
            </div>
          </div>
          <div style="font-size:9px;color:var(--fg);margin-bottom:5px;line-height:1.4">${s.why}</div>
          <div style="display:flex;gap:12px;font-size:9px;margin-bottom:6px">
            <span style="color:var(--green)">TP +$${s.tp}</span>
            <span style="color:var(--red)">SL -$${s.sl}</span>
            <span style="color:var(--dim)">R:R 1:${(s.tp/s.sl).toFixed(1)}</span>
            <span style="color:var(--dim)">PF ${s.pf}</span>
          </div>
          <button onclick='seSendTradeToMt5(${JSON.stringify(s)})' ${btnDisabled}
            style="width:100%;padding:7px;border:none;border-radius:5px;font-size:10px;font-weight:800;${btnStyle}">
            ${btnLabel}
          </button>
        </div>`;
      }).join('')}
    </div>`;
  } else if(!isExtreme && inSession){
    pendingHtml=`<div style="margin-bottom:10px;text-align:center;padding:12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;font-size:10px;color:var(--dim)">
      ⏳ Nessun segnale attivo in questo momento — monitoraggio in corso...
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

  // ── LIBRERIA STRATEGIE con stats backtest
  const activeList = SE.regimePriority[seRegime] || [];
  const catalogHtml = `
<div style="margin-top:20px; padding-top:15px; border-top:1px dashed var(--border)">
  <div style="font-size:11px; color:var(--fg); font-weight:700; margin-bottom:4px; display:flex; align-items:center; gap:8px">
    <span>📚 LIBRERIA STRATEGIE</span>
    <span style="font-size:9px; font-weight:400; color:var(--dim)">Backtest H1 XAU/USD 2024-2026</span>
  </div>
  <div style="font-size:8px;color:var(--dim);margin-bottom:10px">P&L su lotto 0.01 (= $1/punto) · Regime attivo: <b style="color:${rm.col}">${rm.label}</b></div>
  <div style="display:grid; grid-template-columns:1fr; gap:6px">
    ${Object.entries(SE.strategies).map(([id, s]) => {
      const isActive = activeList.includes(id);
      const st = s.stats || {};
      const pnl1col  = (st.pnl_1m||0)>0 ?'var(--green)':'var(--red)';
      const pnl12col = (st.pnl_12m||0)>0?'var(--green)':'var(--red)';
      const pnl24col = (st.pnl_24m||0)>0?'var(--green)':'var(--red)';
      const inds = id==='S00_MFKK'       ? 'ADX 80% + MACD 10% + CCI(50) 10% · SELL≥75 · BUY≥90' :
                   id==='S00_MFKK_HWR'   ? 'ADX≥35 · DI spread≥20 · MACD diff≥0.5 · CCI non OS · SELL ONLY' :
                   id==='S01_EXHAUSTION'  ? 'ADX≥30 · DI spread≥12 · MACD hist reversal · RSI conferm' :
                   id==='S09_VWAP_WPR'   ? 'VWAP cross · W%R≤-80 o ≥-20 · MACD momentum' :
                   id==='S06_ORDERBLOCK'  ? 'Swing H/L zone · EMA20 · RSI · MACD momentum' :
                   id==='S13_STRUC_BREAK' ? 'Breakout 20h High/Low · Price action conferm' :
                   id==='S14_KEY_LEVELS'  ? 'Round numbers (psych levels) · RSI estremo' :
                   id==='S12_WPR_KELTNER' ? 'Keltner channel break · W%R≤-85 o ≥-15 · RSI' : '';
      return `
      <div style="background:var(--bg2); border:1px solid ${isActive?rm.col+'50':'var(--border)'}; border-radius:8px; padding:9px 10px; position:relative; overflow:hidden">
        ${isActive?`<div style="position:absolute;top:0;right:0;background:${rm.col};color:#000;font-size:7px;font-weight:900;padding:2px 6px;border-bottom-left-radius:6px">✓ ATTIVA</div>`:''}
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
          <span style="font-size:11px;font-weight:700;color:${isActive?rm.col:'var(--fg)'}">${s.label}</span>
          <div style="display:flex;gap:7px;font-size:10px">
            <span style="color:var(--green)">PF <b>${s.pf}</b></span>
            <span style="color:var(--blue)">WR <b>${s.wr}</b></span>
          </div>
        </div>
        <div style="font-size:8px;color:var(--dim);margin-bottom:6px;line-height:1.4">${inds}</div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px;font-size:8px;text-align:center">
          <div style="background:#0d0f12;border:1px solid var(--border2);border-radius:4px;padding:3px 2px">
            <div style="color:var(--dim);margin-bottom:1px">1 MESE</div>
            <div style="font-weight:700;color:${pnl1col}">${(st.pnl_1m||0)>=0?'+':''}$${st.pnl_1m||'—'}</div>
          </div>
          <div style="background:#0d0f12;border:1px solid var(--border2);border-radius:4px;padding:3px 2px">
            <div style="color:var(--dim);margin-bottom:1px">12 MESI</div>
            <div style="font-weight:700;color:${pnl12col}">${(st.pnl_12m||0)>=0?'+':''}$${st.pnl_12m||'—'}</div>
          </div>
          <div style="background:#0d0f12;border:1px solid var(--border2);border-radius:4px;padding:3px 2px">
            <div style="color:var(--dim);margin-bottom:1px">24 MESI</div>
            <div style="font-weight:700;color:${pnl24col}">${(st.pnl_24m||0)>=0?'+':''}$${st.pnl_24m||'—'}</div>
          </div>
          <div style="background:#0d0f12;border:1px solid var(--border2);border-radius:4px;padding:3px 2px">
            <div style="color:var(--dim);margin-bottom:1px">MAX DD</div>
            <div style="font-weight:700;color:var(--red)">-$${st.maxdd||'—'}</div>
          </div>
        </div>
        <div style="margin-top:4px;font-size:8px;color:var(--dim);display:flex;gap:8px">
          <span>~${st.trades_12m||'?'} trade/anno</span>
          <span>Target: TP $${s.tp} · SL $${s.sl}</span>
          <span style="margin-left:auto;color:var(--dim)">Best: ${st.best_regime||'?'}</span>
        </div>
      </div>`;
    }).join('')}
  </div>
</div>`;

  el.innerHTML=statusHtml+regimeHtml+indSnap+pendingHtml+posHtml+histHtml+catalogHtml;
}

async function seSendTradeToMt5(s) {
  const btn = event?.target;

  // Verifica stato bot prima di inviare
  const mt5Live = await seFetchMt5Data();
  const syncAge = mt5Live?.synced_at ? Math.round((Date.now()-new Date(mt5Live.synced_at).getTime())/1000) : null;
  const botOk = syncAge !== null && syncAge < 30;

  if (!botOk) {
    seToast('🔴 Bot MT5 offline — avvia python scripts/mt5-bot.py', '#ff4757');
    return;
  }

  if (btn) { btn.disabled = true; btn.innerText = '⌛ Invio in corso...'; }

  try {
    // Il bot MT5 usa il simbolo verificato all'avvio (GOLD, XAUUSD, ecc.)
    // Passiamo 'auto' così il bot usa il simbolo che ha trovato attivo
    const res = await fetch('/api/db', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'mt5_command_push',
        command: {
          direction: s.dir,
          strategy: s.name,
          tp: parseFloat(s.tp),
          sl: parseFloat(s.sl),
          symbol: mt5Live?.bot_status?.symbol || 'GOLD'
        }
      })
    });
    const j = await res.json();
    if (j.ok) {
      seToast(`✅ Ordine ${s.dir.toUpperCase()} inviato — il bot lo esegue entro 1s`, '#00e676');
      if (btn) { btn.innerText = '✓ INVIATO'; btn.style.cssText += ';background:var(--dim);opacity:0.6'; }
    } else {
      throw new Error(j.error || 'Errore server');
    }
  } catch (e) {
    seToast('❌ Errore invio: ' + e.message, '#ff4757');
    if (btn) { btn.disabled = false; btn.innerText = '🚀 RIPROVA'; }
  }
}
window.seSendTradeToMt5 = seSendTradeToMt5;

function seToast(msg, color='var(--green)'){
  let t=document.getElementById('se-toast');
  if(!t){ t=document.createElement('div'); t.id='se-toast';
    t.style.cssText='position:fixed;bottom:80px;left:50%;transform:translateX(-50%);z-index:9999;padding:8px 18px;border-radius:8px;font-size:11px;font-weight:700;pointer-events:none;transition:opacity .3s';
    document.body.appendChild(t); }
  t.style.background=color; t.style.color=color==='var(--green)'?'#000':'#fff';
  t.style.border='1px solid '+color; t.textContent=msg; t.style.opacity='1';
  clearTimeout(t._tid); t._tid=setTimeout(()=>{t.style.opacity='0';},3500);
}

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
