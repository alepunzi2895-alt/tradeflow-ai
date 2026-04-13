// TradeFlow AI — Strategy Engine (live)
// Implementa 4 strategie validate da backtest 730gg H1 XAU/USD
// Regime detection + selezione automatica strategia ottimale per ogni giorno
// Max 3 trade/giorno, cooldown 60 min, skip giorno estremo (ATR>3x media)

// ── CONFIG (calibrata da strategy-engine.py backtest) ────────────────────────
const SE_TP = 20, SE_SL = 12;
const SE_MAX_TRADES = 3;
const SE_COOLDOWN_H = 1;
const SE_SESSION_START = 7, SE_SESSION_END = 17; // UTC

// Profitability ranking (dal backtest 730gg):
// EXHAUSTION PF=2.29, RSI_EXTREME PF=1.38, SESSION_MOM PF=1.11, MACD_ZERO PF=1.09
// EMA_TREND PF=1.01 e BB_REVERSAL PF=0.98 ESCLUSE (non profittevoli)

// ── STATE ─────────────────────────────────────────────────────────────────────
let seCandles = [];       // H1 candles cache (da mfkk.js / proxy)
let seLastUpdate = 0;
let seSignalsToday = [];  // segnali generati oggi
let seRegime = 'UNKNOWN';
let seActiveStrategies = [];
let seRefreshTimer = null;
let seCanvasData = {};    // dati per il mini chart

// ── MATH HELPERS (mirror di strategy-engine.py) ───────────────────────────────
function _seEma(src, p) {
  const k = 2/(p+1); let v = src[0]; const o = [v];
  for (let i=1; i<src.length; i++) { v = src[i]*k + v*(1-k); o.push(v); }
  return o;
}
function _seSma(src, p) {
  const o = new Array(src.length).fill(null);
  for (let i=p-1; i<src.length; i++) {
    let s=0; for(let j=0;j<p;j++) s+=(src[i-j]||0);
    o[i]=s/p;
  }
  return o;
}
function _seRsi(src, p=14) {
  const n=src.length, out=new Array(n).fill(null);
  if(n<=p) return out;
  const gains=[], losses=[];
  for(let i=1;i<n;i++){
    gains.push(Math.max(0,src[i]-src[i-1]));
    losses.push(Math.max(0,src[i-1]-src[i]));
  }
  let ag=gains.slice(0,p).reduce((a,b)=>a+b,0)/p;
  let al=losses.slice(0,p).reduce((a,b)=>a+b,0)/p;
  out[p]=100-100/(1+(al>0?ag/al:100));
  for(let i=p;i<gains.length;i++){
    ag=(ag*(p-1)+gains[i])/p; al=(al*(p-1)+losses[i])/p;
    out[i+1]=100-100/(1+(al>0?ag/al:100));
  }
  return out;
}
function _seBollinger(src, p=20, mult=2.0) {
  const mid=_seSma(src,p), up=[], lo=[];
  for(let i=0;i<src.length;i++){
    if(mid[i]==null){up.push(null);lo.push(null);continue;}
    const sl=src.slice(i-p+1,i+1);
    const mn=sl.reduce((a,b)=>a+b,0)/p;
    const std=Math.sqrt(sl.reduce((a,b)=>a+(b-mn)**2,0)/p);
    up.push(mid[i]+mult*std); lo.push(mid[i]-mult*std);
  }
  return {up,mid,lo};
}
function _seStoch(H,L,C,kp=14,dp=3,sp=3) {
  const n=C.length, rk=new Array(n).fill(null);
  for(let i=kp-1;i<n;i++){
    const h=Math.max(...H.slice(i-kp+1,i+1));
    const l=Math.min(...L.slice(i-kp+1,i+1));
    rk[i]=h>l?(C[i]-l)/(h-l)*100:50;
  }
  const sk=_seSma(rk.map(x=>x??50),dp);
  const sd=_seSma(sk.map(x=>x??50),sp);
  return {sk,sd};
}
function _seAdx(H,L,C,p=14) {
  const n=C.length;
  const TR=[0],DMP=[0],DMM=[0];
  for(let i=1;i<n;i++){
    TR.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));
    const up=H[i]-H[i-1], dn=L[i-1]-L[i];
    DMP.push(up>dn&&up>0?up:0);
    DMM.push(dn>up&&dn>0?dn:0);
  }
  const sTR=[0],sDMP=[0],sDMM=[0];
  for(let i=1;i<n;i++){
    sTR.push(sTR[i-1]-sTR[i-1]/p+TR[i]);
    sDMP.push(sDMP[i-1]-sDMP[i-1]/p+DMP[i]);
    sDMM.push(sDMM[i-1]-sDMM[i-1]/p+DMM[i]);
  }
  const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
  const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
  const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
  const ADX=_seSma(DX,p);
  return {adx:ADX,dip:DIP,dim:DIM};
}
function _seAtr(H,L,C,p=14) {
  const tr=[0];
  for(let i=1;i<C.length;i++)
    tr.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));
  return _seSma(tr,p);
}

// ── COMPUTE ALL INDICATORS FROM CANDLE ARRAY ──────────────────────────────────
function seComputeAll(candles) {
  if (!candles || candles.length < 220) return null;
  const H=candles.map(c=>c.h), L=candles.map(c=>c.l), C=candles.map(c=>c.c);
  const n=C.length;

  const e12=_seEma(C,12), e26=_seEma(C,26);
  const macd=e12.map((v,i)=>v-e26[i]);
  const sig=_seEma(macd,9);
  const hist=macd.map((v,i)=>v-sig[i]);

  const {adx,dip,dim}=_seAdx(H,L,C,14);
  const atr=_seAtr(H,L,C,14);
  const atr30=_seSma(atr.map(x=>x||0),30);
  const rsi=_seRsi(C,14);
  const bb=_seBollinger(C,20,2.0);
  const {sk,sd}=_seStoch(H,L,C,14,3,3);
  const e20=_seEma(C,20), e50=_seEma(C,50), e200=_seEma(C,200);

  return {H,L,C,n,macd,sig,hist,adx,dip,dim,atr,atr30,rsi,
          bbUp:bb.up,bbMid:bb.mid,bbLo:bb.lo,sk,sd,e20,e50,e200};
}

// ── REGIME DETECTION ──────────────────────────────────────────────────────────
function seDetectRegime(inds, i) {
  const {adx,dip,dim,atr,atr30,e20,e50,e200} = inds;
  const a=adx[i], dp=dip[i], dm=dim[i];
  const av=atr[i], aa=atr30[i];
  if (a==null||av==null||aa==null) return 'UNKNOWN';
  const relVol = aa>0 ? av/aa : 1;
  if (a>=30 && dp>dm) return 'TREND_UP';
  if (a>=30 && dm>dp) return 'TREND_DOWN';
  if (a>=22 && dp>dm) return 'WEAK_TREND_UP';
  if (a>=22 && dm>dp) return 'WEAK_TREND_DOWN';
  if (relVol>1.4)     return 'VOLATILE_RANGE';
  return 'RANGE';
}

// ── STRATEGY SIGNAL GENERATORS ────────────────────────────────────────────────
// Ritornano: { dir: 'buy'|'sell', strategy, reason, strength } o null

function seCheckExhaustion(inds, i) {
  const a=inds.adx[i], dp=inds.dip[i], dm=inds.dim[i];
  const m=inds.macd[i], s=inds.sig[i];
  if (a==null||dp==null||m==null) return null;
  const diff=m-s, spread=Math.abs(dp-dm);
  // SELL: ADX forte + DI- domina + MACD bullish esteso
  if (a>=30 && dm>dp && spread>=15 && diff>=1.0) {
    const wr = diff>=2 ? '92%' : '82%';
    return {dir:'sell',strategy:'EXHAUSTION',
      reason:`ADX ${a.toFixed(1)} + DI-${dm.toFixed(1)} vs DI+${dp.toFixed(1)} · MACD +${diff.toFixed(2)} esaurito`,
      strength: spread>=20&&diff>=1.5 ? 'HIGH' : 'MED', wr};
  }
  // BUY: ADX forte + DI+ domina + MACD bearish esteso
  if (a>=28 && dp>dm && spread>=15 && diff<=-1.0) {
    return {dir:'buy',strategy:'EXHAUSTION',
      reason:`ADX ${a.toFixed(1)} + DI+${dp.toFixed(1)} vs DI-${dm.toFixed(1)} · MACD ${diff.toFixed(2)} esaurito`,
      strength:'MED', wr:'65%'};
  }
  return null;
}

function seCheckRsiExtreme(inds, i) {
  const r=inds.rsi[i], a=inds.adx[i];
  const bu=inds.bbUp[i], bl=inds.bbLo[i], c=inds.C[i];
  if (r==null||a==null||bu==null) return null;
  if (a>=28) return null; // solo ranging
  if (r<=32 && c<=bl*1.003)
    return {dir:'buy',strategy:'RSI_EXTREME',
      reason:`RSI ${r.toFixed(0)} oversold + prezzo su BB lower ${bl.toFixed(0)}`,
      strength:'MED', wr:'55%'};
  if (r>=68 && c>=bu*0.997)
    return {dir:'sell',strategy:'RSI_EXTREME',
      reason:`RSI ${r.toFixed(0)} overbought + prezzo su BB upper ${bu.toFixed(0)}`,
      strength:'MED', wr:'53%'};
  return null;
}

function seCheckSessionMom(inds, i, hour) {
  if (hour<7||hour>10) return null; // solo apertura London
  const m=inds.macd[i], s=inds.sig[i], r=inds.rsi[i];
  const a=inds.adx[i], e50=inds.e50[i], c=inds.C[i];
  if (m==null||r==null||a==null||e50==null) return null;
  const diff=m-s;
  if (diff>0.3 && r>=50 && c>e50*0.999 && a>=15)
    return {dir:'buy',strategy:'SESSION_MOM',
      reason:`London open: MACD +${diff.toFixed(2)} · RSI ${r.toFixed(0)} · sopra EMA50`,
      strength:'LOW', wr:'45%'};
  if (diff<-0.3 && r<=50 && c<e50*1.001 && a>=15)
    return {dir:'sell',strategy:'SESSION_MOM',
      reason:`London open: MACD ${diff.toFixed(2)} · RSI ${r.toFixed(0)} · sotto EMA50`,
      strength:'LOW', wr:'44%'};
  return null;
}

function seCheckMacdZero(inds, i) {
  if (i<1) return null;
  const h=inds.hist, e20=inds.e20[i], e50=inds.e50[i];
  const r=inds.rsi[i], a=inds.adx[i];
  if (h[i]==null||h[i-1]==null||r==null||a==null) return null;
  // Cross rialzista + EMA20>EMA50 + RSI momentum
  if (h[i-1]<0&&h[i]>0&&e20>e50&&r>=40&&r<=65)
    return {dir:'buy',strategy:'MACD_ZERO',
      reason:`MACD hist cross zero rialzista · RSI ${r.toFixed(0)} · EMA trend up`,
      strength:'LOW', wr:'40%'};
  if (h[i-1]>0&&h[i]<0&&e20<e50&&r>=35&&r<=60)
    return {dir:'sell',strategy:'MACD_ZERO',
      reason:`MACD hist cross zero ribassista · RSI ${r.toFixed(0)} · EMA trend down`,
      strength:'LOW', wr:'40%'};
  return null;
}

// ── REGIME → STRATEGY PRIORITY ───────────────────────────────────────────────
// Ordinate per PF: EXHAUSTION>RSI_EXTREME>SESSION_MOM>MACD_ZERO
function seGetStrategyPriority(regime) {
  const map = {
    'TREND_UP':         ['EXHAUSTION','SESSION_MOM','MACD_ZERO'],
    'TREND_DOWN':       ['EXHAUSTION','SESSION_MOM','MACD_ZERO'],
    'WEAK_TREND_UP':    ['SESSION_MOM','MACD_ZERO','RSI_EXTREME'],
    'WEAK_TREND_DOWN':  ['SESSION_MOM','MACD_ZERO','RSI_EXTREME'],
    'RANGE':            ['RSI_EXTREME','MACD_ZERO','SESSION_MOM'],
    'VOLATILE_RANGE':   ['RSI_EXTREME','SESSION_MOM'],
    'UNKNOWN':          ['SESSION_MOM','RSI_EXTREME'],
  };
  return map[regime] || ['SESSION_MOM','RSI_EXTREME'];
}

// ── SCAN: genera segnali per la candela corrente ───────────────────────────────
function seScanSignals(candles, regime) {
  if (!candles || candles.length < 220) return null;
  const inds = seComputeAll(candles);
  if (!inds) return null;
  const i = inds.n - 1;

  const nowUtc = new Date();
  const hour = nowUtc.getUTCHours();

  // Check extreme day: ATR > 3x avg
  const av=inds.atr[i], aa=inds.atr30[i];
  if (av && aa && av > 3*aa) return { extreme: true };

  // Sessione valida
  if (hour < SE_SESSION_START || hour >= SE_SESSION_END) return { offSession: true, hour };

  const priority = seGetStrategyPriority(regime);
  const checkers = {
    'EXHAUSTION': ()=>seCheckExhaustion(inds,i),
    'RSI_EXTREME': ()=>seCheckRsiExtreme(inds,i),
    'SESSION_MOM': ()=>seCheckSessionMom(inds,i,hour),
    'MACD_ZERO': ()=>seCheckMacdZero(inds,i),
  };

  const signals = [];
  for (const name of priority) {
    const fn = checkers[name];
    if (!fn) continue;
    const sig = fn();
    if (sig) signals.push(sig);
  }

  // Aggiunge indicatori snapshot per debug
  const snap = {
    price: inds.C[i].toFixed(2),
    adx: inds.adx[i]?.toFixed(1),
    dip: inds.dip[i]?.toFixed(1),
    dim: inds.dim[i]?.toFixed(1),
    rsi: inds.rsi[i]?.toFixed(0),
    macd: inds.macd[i]?.toFixed(2),
    e20: inds.e20[i]?.toFixed(0),
    e50: inds.e50[i]?.toFixed(0),
  };

  return {signals, snapshot:snap, regime};
}

// ── DAILY STATE (localStorage) ────────────────────────────────────────────────
function seGetDailyState() {
  const today = new Date().toISOString().split('T')[0];
  try {
    const s = JSON.parse(localStorage.getItem('se_daily') || '{}');
    if (s.date !== today) return { date:today, trades:[], regime:'UNKNOWN', lastHour:-1 };
    return s;
  } catch(e) { return { date:today, trades:[], regime:'UNKNOWN', lastHour:-1 }; }
}

function seSaveDailyState(state) {
  try { localStorage.setItem('se_daily', JSON.stringify(state)); } catch(e) {}
}

// ── MAIN REFRESH LOOP ─────────────────────────────────────────────────────────
async function seRefresh() {
  const state = seGetDailyState();
  const nowH = new Date().getUTCHours();

  // Carica candles se non disponibili (usa quelle di mfkk.js se già caricate)
  if (window.mfkkCandles && window.mfkkCandles.length >= 220) {
    seCandles = window.mfkkCandles;
  } else if (seCandles.length < 220) {
    try {
      const asset = window.activeAsset || 'XAU';
      const r = await fetch(`/api/candles?asset=${asset}&range=60d&interval=1h`);
      const d = await r.json();
      if (d?.ok && d.candles?.length >= 220) seCandles = d.candles;
    } catch(e) { console.log('se candles:', e.message); }
  }

  if (seCandles.length < 220) { seRenderNoData(); return; }

  const inds = seComputeAll(seCandles);
  if (!inds) return;

  // Regime detection con i dati attuali
  const regime = seDetectRegime(inds, inds.n-1);
  seRegime = regime;
  seActiveStrategies = seGetStrategyPriority(regime);
  if (state.date === new Date().toISOString().split('T')[0]) {
    state.regime = regime;
  }

  // Scan segnali
  const scan = seScanSignals(seCandles, regime);

  // Controlla se possiamo aprire un trade
  const canTrade =
    scan && !scan.extreme && !scan.offSession &&
    state.trades.length < SE_MAX_TRADES &&
    nowH - (state.lastHour || -99) >= SE_COOLDOWN_H;

  if (canTrade && scan.signals?.length > 0) {
    // Scegli il segnale migliore (primo = priorità più alta)
    const best = scan.signals[0];
    const dup = state.trades.find(t=>t.hour===nowH&&t.dir===best.dir&&t.strategy===best.strategy);
    if (!dup) {
      const trade = {
        ...best,
        hour: nowH,
        time: new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'}),
        price: parseFloat(scan.snapshot.price),
        tp: parseFloat(scan.snapshot.price) + (best.dir==='buy' ? SE_TP : -SE_TP),
        sl: parseFloat(scan.snapshot.price) + (best.dir==='buy' ? -SE_SL : SE_SL),
        status: 'open'
      };
      state.trades.push(trade);
      state.lastHour = nowH;
      seSaveDailyState(state);
    }
  }

  // Segna trade chiusi (simulazione live: prezzo corrente vs TP/SL)
  const liveP = parseFloat(scan?.snapshot?.price || 0);
  if (liveP > 0) {
    for (const t of state.trades) {
      if (t.status !== 'open') continue;
      if (t.dir==='buy' && liveP>=t.tp)  { t.status='win'; t.closePrice=t.tp; }
      if (t.dir==='buy' && liveP<=t.sl)  { t.status='loss'; t.closePrice=t.sl; }
      if (t.dir==='sell' && liveP<=t.tp) { t.status='win'; t.closePrice=t.tp; }
      if (t.dir==='sell' && liveP>=t.sl) { t.status='loss'; t.closePrice=t.sl; }
    }
    seSaveDailyState(state);
  }

  seSignalsToday = state.trades;
  seRender(state, scan, inds);
}

// ── RENDER ────────────────────────────────────────────────────────────────────
function seRenderNoData() {
  const el = document.getElementById('se-content');
  if (!el) return;
  el.innerHTML = `<div style="text-align:center;padding:30px;color:var(--dim);font-size:13px">
    Caricamento dati candle in corso...<br><span style="font-size:10px">Le candele sono condivise con il modulo MFKK</span>
  </div>`;
}

function seRender(state, scan, inds) {
  const el = document.getElementById('se-content');
  if (!el) return;

  const regimeColors = {
    'TREND_UP':        {col:'#00e676',bg:'#00e67615',icon:'📈'},
    'TREND_DOWN':      {col:'#ff4757',bg:'#ff475715',icon:'📉'},
    'WEAK_TREND_UP':   {col:'#ffd700',bg:'#ffd70015',icon:'↗️'},
    'WEAK_TREND_DOWN': {col:'#ffca28',bg:'#ffca2815',icon:'↘️'},
    'RANGE':           {col:'#c8a96e',bg:'#c8a96e15',icon:'↔️'},
    'VOLATILE_RANGE':  {col:'#b36cff',bg:'#b36cff15',icon:'⚡'},
    'UNKNOWN':         {col:'var(--dim)',bg:'var(--bg2)',icon:'❓'},
  };
  const rc = regimeColors[seRegime] || regimeColors['UNKNOWN'];

  const today = state.date;
  const trades = state.trades;
  const wins = trades.filter(t=>t.status==='win').length;
  const losses = trades.filter(t=>t.status==='loss').length;
  const open = trades.filter(t=>t.status==='open').length;
  const pnl = wins*SE_TP - losses*SE_SL;
  const pnlCol = pnl>0?'var(--green)':pnl<0?'var(--red)':'var(--dim)';

  // Session / extreme status
  let statusBar = '';
  const nowH = new Date().getUTCHours();
  if (scan?.extreme) {
    statusBar = `<div style="background:#ff475720;border:1px solid #ff475740;border-radius:6px;padding:6px 9px;font-size:10px;color:#ff4757;margin-bottom:8px">⚠️ GIORNO ESTREMO: ATR >3x media — trading sospeso oggi</div>`;
  } else if (scan?.offSession) {
    statusBar = `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 9px;font-size:10px;color:var(--dim);margin-bottom:8px">🔴 Fuori sessione (${nowH}:00 UTC) — segnali attivi 07-17 UTC (London/NY)</div>`;
  } else {
    statusBar = `<div style="background:#00e67610;border:1px solid #00e67620;border-radius:6px;padding:6px 9px;font-size:10px;color:var(--green);margin-bottom:8px">🟢 Sessione attiva (${nowH}:00 UTC) — ${SE_MAX_TRADES-trades.length} trade rimanenti oggi</div>`;
  }

  // Regime box
  const regimeBox = `
<div style="background:${rc.bg};border:1px solid ${rc.col}40;border-radius:8px;padding:10px 12px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <div>
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:3px">REGIME DI MERCATO</div>
      <div style="font-size:15px;font-weight:800;color:${rc.col}">${rc.icon} ${seRegime.replace('_',' ')}</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:9px;color:var(--dim);margin-bottom:2px">P&L OGGI</div>
      <div style="font-size:16px;font-weight:800;color:${pnlCol}">${pnl>=0?'+':''}$${pnl.toFixed(0)}</div>
      <div style="font-size:8px;color:var(--dim)">${wins}W · ${losses}L · ${open}Open</div>
    </div>
  </div>
  <div style="margin-top:7px;font-size:9px;color:${rc.col}">
    Strategie attive: ${seActiveStrategies.map(s=>`<span style="background:${rc.col}20;padding:1px 5px;border-radius:3px;margin-right:3px">${s}</span>`).join('')}
  </div>
</div>`;

  // Snapshot indicatori
  const snap = scan?.snapshot;
  const snapBox = snap ? `
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px">
  ${[['ADX',snap.adx],['DI+',snap.dip],['DI-',snap.dim],['RSI',snap.rsi]].map(([k,v])=>`
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:5px;padding:4px;text-align:center">
    <div style="font-size:8px;color:var(--dim)">${k}</div>
    <div style="font-size:11px;font-weight:700;color:var(--fg)">${v??'—'}</div>
  </div>`).join('')}
</div>
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:8px">
  ${[['MACD',snap.macd],['EMA20',snap.e20],['EMA50',snap.e50],['PRICE','$'+snap.price]].map(([k,v])=>`
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:5px;padding:4px;text-align:center">
    <div style="font-size:8px;color:var(--dim)">${k}</div>
    <div style="font-size:11px;font-weight:700;color:var(--fg)">${v??'—'}</div>
  </div>`).join('')}
</div>` : '';

  // Trade list
  const tradeRows = trades.length === 0
    ? `<div style="text-align:center;padding:15px;color:var(--dim);font-size:11px">Nessun trade oggi — in attesa di setup</div>`
    : trades.map((t,idx)=>{
        const sCol = t.status==='win'?'#00e676':t.status==='loss'?'#ff4757':'#ffca28';
        const sIcon = t.status==='win'?'✅':t.status==='loss'?'❌':'⏳';
        const dirCol = t.dir==='buy'?'#00e676':'#ff4757';
        const dirIcon = t.dir==='buy'?'▲':'▼';
        const strWr = t.wr ? ` · WR ${t.wr}` : '';
        return `
<div style="background:var(--bg2);border:1px solid ${sCol}40;border-radius:7px;padding:8px 10px;margin-bottom:6px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <div>
      <span style="color:${dirCol};font-weight:700;font-size:11px">${dirIcon} ${t.dir.toUpperCase()}</span>
      <span style="font-size:9px;color:var(--dim);margin-left:6px">${t.time} UTC · ${t.strategy}${strWr}</span>
    </div>
    <div style="font-size:12px">${sIcon} <span style="color:${sCol};font-size:10px;font-weight:700">${t.status.toUpperCase()}</span></div>
  </div>
  <div style="font-size:9px;color:var(--dim);margin-bottom:4px">${t.reason}</div>
  <div style="display:flex;gap:8px;font-size:9px">
    <span>Entry <b>$${t.price?.toFixed(0)}</b></span>
    <span style="color:var(--green)">TP $${t.tp?.toFixed(0)} (+$${SE_TP})</span>
    <span style="color:var(--red)">SL $${t.sl?.toFixed(0)} (-$${SE_SL})</span>
    <span>R:R 1:1.67</span>
  </div>
</div>`;
      }).join('');

  // Pending signals (non ancora entrati)
  const pending = (scan?.signals || []).filter(s=>
    !state.trades.find(t=>t.strategy===s.strategy&&t.time)
  );
  const pendingHtml = pending.length>0 && !scan?.offSession && !scan?.extreme ? `
<div style="margin-bottom:8px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">SEGNALI ATTIVI ORA</div>
  ${pending.map(s=>{
    const sc=s.strength==='HIGH'?'#ffd700':s.strength==='MED'?'var(--green)':'var(--yellow)';
    const dc=s.dir==='buy'?'#00e676':'#ff4757';
    return `<div style="background:${sc}15;border:1px solid ${sc}40;border-radius:6px;padding:7px 9px;margin-bottom:5px">
      <div style="display:flex;justify-content:space-between">
        <span style="color:${dc};font-weight:700;font-size:11px">${s.dir==='buy'?'▲':'▼'} ${s.dir.toUpperCase()}</span>
        <span style="color:${sc};font-size:9px">● ${s.strength} · WR ${s.wr}</span>
      </div>
      <div style="font-size:9px;color:var(--dim);margin-top:3px">${s.strategy}: ${s.reason}</div>
    </div>`;
  }).join('')}
</div>` : '';

  // Strategy performance table (dal backtest)
  const perfTable = `
<div style="margin-top:10px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:6px">PERFORMANCE STORICA (730gg backtest)</div>
  <table style="width:100%;border-collapse:collapse;font-size:9px">
    <tr style="color:var(--dim);border-bottom:1px solid var(--border)">
      <td style="padding:3px 0">Strategia</td><td style="text-align:right">WR%</td>
      <td style="text-align:right">P&L</td><td style="text-align:right">PF</td>
    </tr>
    ${[
      ['EXHAUSTION','57.9%','$788','2.29','#00e676'],
      ['RSI_EXTREME','45.4%','$572','1.38','#ffd700'],
      ['SESSION_MOM','39.9%','$612','1.11','#ffca28'],
      ['MACD_ZERO','39.6%','$88','1.09','#c8a96e'],
    ].map(([n,wr,pnl,pf,col])=>`
    <tr style="border-bottom:1px solid var(--border2)">
      <td style="padding:4px 0;color:${col};font-weight:600">${n}</td>
      <td style="text-align:right;color:${col}">${wr}</td>
      <td style="text-align:right;color:var(--fg)">${pnl}</td>
      <td style="text-align:right;color:var(--dim)">${pf}</td>
    </tr>`).join('')}
  </table>
</div>`;

  el.innerHTML = `
${statusBar}
${regimeBox}
${snapBox}
${pendingHtml}
<div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:6px">TRADE OGGI (${today})</div>
${tradeRows}
${perfTable}
<div style="margin-top:8px;font-size:8px;color:var(--border2);text-align:center">
  Aggiornamento automatico ogni 5 min · TP $${SE_TP} · SL $${SE_SL} · Max ${SE_MAX_TRADES}/gg
</div>`;
}

// ── INIT & TIMER ──────────────────────────────────────────────────────────────
async function initStrategyEngine() {
  if (seRefreshTimer) clearInterval(seRefreshTimer);
  await seRefresh();
  seRefreshTimer = setInterval(seRefresh, 5 * 60 * 1000); // ogni 5 minuti
}

// Esponi globalmente per il tab switch
window.initStrategyEngine = initStrategyEngine;
window.seRefresh = seRefresh;
