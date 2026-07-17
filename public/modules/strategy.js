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
  minQuality: { S00_MFKK: 75, S05_MFKK_INTRADAY: 0, default: 0 },
  _autoExecuted: new Set(),  // mantenuto per compatibilità (non usato)
  strategies: {
    // ── STRATEGIE ATTIVE [BACKTEST MT5 GOLD · lot 0.01 · $1/punto] ──
    // Refresh 2026-07-17: SL allineato al live (1.5×ATR, era 1.0-1.2× nel backtester — vedi 07_self_learning_log.md)
    // + re-tuning parametri (nessun cambiamento adottato, config attuale confermata già ottima su IS/OOS).
    // Sistema adattivo H1: 1332 trade · WR 40.2% · PF 1.277 · +$33.28/gg · DD $4417.5 · 18/24 mesi+
    // P&L da adaptive_rm.by_strategy (bt_{h1,m30,h4}_2026-07-17.json) · eq = curva equità mensile cumulata
    'S00_MFKK': { label: 'MFKK Core [H1] V2', pf: 1.211, wr: '38.3%', tp: 'ATR×3.5', sl: 'ATR×1.5',
      stats: {
        pnl_1m: 1034.7, td_1m: 1.87, pnl_6m: 419.1, td_6m: 1.69,
        pnl_12m: 2588.7, td_12m: 1.62, pnl_24m: 5330.3, td_24m: 4.77,
        maxdd: 4251.1, maxdd_pct: '52.3%', trades_12m: 590, best_regime: 'ALL REGIMES · H1 best · 17/24 mesi+',
        eq: [128.9,296.1,450.6,232.0,552.9,657.0,696.6,1303.8,1570.1,2451.0,2920.4,2718.9,2842.0,2829.1,4121.1,5242.3,5093.0,5035.5,8133.6,5031.1,5577.9,4567.3,4960.5,5330.3]
      } },
    'S05_MFKK_INTRADAY': { label: 'MFKK Intraday [H4] V6 ⛔ RITIRATA', pf: 0.80, wr: '52.9%', tp: 'ATR×3.5', sl: 'ATR×1.5',
      stats: {
        pnl_1m: 58.1, td_1m: 0.23, pnl_6m: -523.4, td_6m: 0.19,
        pnl_12m: -927.4, td_12m: 0.2, pnl_24m: -519.5, td_24m: 1.73,
        maxdd: 1066.8, maxdd_pct: 'n/d', trades_12m: 73, best_regime: 'Ritirata dal roster live 2026-07-16 (PF standalone <1, unico slot vivo era H4) · dati standalone, non più selezionabile dal bot',
        eq: [-21.8,-9.8,-13.3,-162.8,-159.4,-211.1,-181.2,-101.0,488.9,446.5,382.0,427.9,379.4,363.0,210.1,83.8,47.8,-75.9,-143.2,-411.0,-458.5,-431.4,-519.5]
      } },
    'S09_MFKK_SCALPING': { label: 'MFKK Scalping [M30] V3', pf: 1.957, wr: '41.7%', tp: 'ATR×4.0', sl: 'ATR×1.5',
      stats: {
        pnl_1m: 64.3, td_1m: 0.03, pnl_6m: 71.9, td_6m: 0.03,
        pnl_12m: 98.6, td_12m: 0.03, pnl_24m: 98.6, td_24m: 1.33,
        maxdd: 48.8, maxdd_pct: '49.5%', trades_12m: 12, best_regime: 'VOLATILE/WEAK · M30 · regime-gated · 12 trade/24m (fragile)',
        eq: [-8.2,16.1,65.3,26.7,83.1,60.6,34.3,98.6]
      } },
    'S10_OB_FVG_SCALP': { label: 'OB+FVG Scalp [M30] V3', pf: 1.56, wr: '54.5%', tp: 'ATR×3.5', sl: 'ATR×1.5',
      stats: {
        pnl_1m: 31.1, td_1m: 0.07, pnl_6m: 217.4, td_6m: 0.06,
        pnl_12m: 197.0, td_12m: 0.03, pnl_24m: 197.0, td_24m: 1.1,
        maxdd: 261.9, maxdd_pct: 'n/d', trades_12m: 11, best_regime: 'WEAK/RANGE · M30 · ADX≥18 · OB+FVG confluenza (n piccolo, DD>picco storico — fragile)',
        eq: [-20.4,-63.9,-89.4,165.9,197.0]
      } },
    'S16_GOLDEN_SQUEEZE': { label: 'Golden Squeeze [H1] V5', pf: 1.728, wr: '48.6%', tp: 'ATR×3.5', sl: 'ATR×2.0',
      stats: {
        pnl_1m: -92.8, td_1m: 0.37, pnl_6m: 1113.0, td_6m: 0.31,
        pnl_12m: 1931.9, td_12m: 0.32, pnl_24m: 2729.1, td_24m: 2.08,
        maxdd: 663.4, maxdd_pct: '20.0%', trades_12m: 117, best_regime: 'TREND · H1 best · EMA200+ADX+MACD+OBV · 15/23 mesi+',
        eq: [164.4,246.3,262.0,184.8,155.2,270.3,197.1,185.2,327.4,588.2,763.9,770.5,789.6,811.3,1030.3,1463.2,1616.0,1507.8,3122.7,3319.7,3293.1,2821.8,2729.1]
      } },
    'S17_CONVERGENCE_SCALP': { label: 'Convergence Scalp [H4] V2', pf: 2.235, wr: '43.2%', tp: 'ATR×4.0', sl: 'ATR×1.5',
      stats: {
        pnl_1m: 418.5, td_1m: 0.13, pnl_6m: 2169.9, td_6m: 0.16,
        pnl_12m: 3283.8, td_12m: 0.14, pnl_24m: 3739.7, td_24m: 1.08,
        maxdd: 408.7, maxdd_pct: '10.9%', trades_12m: 51, best_regime: 'VOLATILE/TREND · H4 best · EMA13/34+StochRSI+BB · 14/21 mesi+',
        eq: [-0.3,-101.0,-91.0,-31.5,-11.2,-9.3,133.0,67.5,632.3,455.8,368.3,396.0,940.2,1569.7,1513.9,2687.1,2774.1,3345.0,3321.1,3446.4,3739.7]
      } },
    'S18_RANGE_REVERSAL': { label: 'Range Reversal [M30] V1', pf: 1.078, wr: '43.5%', tp: 'ATR×2.0', sl: 'ATR×1.2',
      stats: {
        pnl_1m: -44.3, td_1m: 0.27, pnl_6m: -72.7, td_6m: 0.23,
        pnl_12m: 51.5, td_12m: 0.26, pnl_24m: 51.5, td_24m: 1.23,
        maxdd: 159.7, maxdd_pct: '89.6%', trades_12m: 92, best_regime: 'RANGE/WEAK · M30 (bot) · BB exhaustion+RSI/WPR · ADX<22 · DD alto relativo al P&L — fragile',
        eq: [28.4,50.3,72.3,113.6,110.4,124.2,178.2,95.9,35.2,108.5,107.7,67.1,51.5]
      } },
  },
  // ── REGIME PRIORITY (allineata a REGIME_PRIORITY_H1 del backtester) ──
  regimePriority: {
    TREND_UP:   ['S16_GOLDEN_SQUEEZE', 'S00_MFKK'],
    TREND_DOWN: ['S16_GOLDEN_SQUEEZE', 'S00_MFKK'],
    WEAK_UP:    ['S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK'],
    WEAK_DOWN:  ['S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK'],
    VOLATILE:   ['S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'],
    RANGE:      ['S18_RANGE_REVERSAL', 'S10_OB_FVG_SCALP', 'S09_MFKK_SCALPING'],
  },
  // Regime intelligence: max segnali simultanei per regime
  maxSignals: { TREND_UP: 3, TREND_DOWN: 3, WEAK_UP: 3, WEAK_DOWN: 3, RANGE: 3, VOLATILE: 1, UNKNOWN: 1 },
};

let seTimer = null;
let seInds = null;
let seRegime = 'UNKNOWN';
let _lastScorePush = 0;
let _seIndsCacheTime = 0;   // timestamp ultimo calcolo indicatori riuscito
let _seCandlesStale = false; // true quando si usano indicatori cached
let _seRefreshRunning = false; // guard contro chiamate concorrenti
let _mt5LastFetchTime = 0;     // TTL cache MT5 (15s — bot synca ogni 20s)
// Trade history filter state (persiste attraverso i rebuild di seRender ogni 1s)
window._seTradeFilter = window._seTradeFilter || 'week';
window._seTradeFrom   = window._seTradeFrom   || '';
window._seTradeTo     = window._seTradeTo     || '';

// ── MAIN LOOP ────────────────────────────────────────────────────────────────
async function seRefresh() {
  // Non eseguire se il tab Strategy non è attivo — evita API calls e DOM churn inutili
  if(!document.getElementById('tp-strategy')?.classList.contains('on')) return;
  // Guard: evita istanze concorrenti che causano flickering online/offline
  if(_seRefreshRunning) return;
  _seRefreshRunning = true;
  const el = document.getElementById('se-content');
  if(!el) return;

  // 1. Candele da Proxy (per evitare CORS)
  let candles = [];
  let candlesFailed = false;
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
    candlesFailed = true;
  }

  // Se candele non disponibili ma abbiamo indicatori cached (<30min), li usiamo
  if(candlesFailed || candles.length < 100) {
    const cacheAge = Date.now() - _seIndsCacheTime;
    if(seInds && cacheAge < 30 * 60 * 1000) {
      _seCandlesStale = true;
      // Salta ricalcolo indicatori — procedi con snap cached
    } else {
      _seRefreshRunning = false;
      seRenderNoData();
      return;
    }
  } else {
    _seCandlesStale = false;
  }

  // 2. Calcolo Indicatori (saltato se si usano indicatori cached)
  if(!_seCandlesStale) {
  const O = candles.map(c=>c.o || c.c);
  const C = candles.map(c=>c.c);
  const H = candles.map(c=>c.h);
  const L = candles.map(c=>c.l);
  const V = candles.map(c=>c.v||0);
  const n = C.length;

  const tr = [0];
  for(let i=1; i<n; i++) tr.push(Math.max(H[i]-L[i], Math.abs(H[i]-C[i-1]), Math.abs(L[i]-C[i-1])));
  const atr = _sma(tr, 14);

  // OBV MACD T-Channel
  const _obvm = _calcOBVMACD(C, H, L, V);
  const _ursi = _calcUltimateRSI(C, 14, 14);
  const _ict  = _calcICTOrderFlow(O, H, L, C);
  const _adxd = _adxSma(H, L, C, 14);
  const _ob   = _calcOrderBlocks(O, H, L, C, 5, 0.0);

  // M15 candles — cache 15 min (non ri-fetchiamo ogni secondo)
  const M15_TTL = 15 * 60 * 1000;
  let _m15 = null;
  if (!window._seM15Cache || Date.now() - (window._seM15CacheTime||0) > M15_TTL) {
    try {
      const rm15 = await fetch('/api/price?type=candles&asset=XAU&interval=15m&range=5d');
      const jm15 = await rm15.json();
      if (jm15.ok && jm15.candles?.length > 50) {
        window._seM15Cache    = jm15.candles;
        window._seM15CacheTime = Date.now();
      }
    } catch(e) { /* silenzioso — usa cache vecchia se disponibile */ }
  }
  if (window._seM15Cache?.length > 50) {
    const m15c = window._seM15Cache;
    const mO = m15c.map(c=>c.o||c.c), mC = m15c.map(c=>c.c);
    const mH = m15c.map(c=>c.h), mL = m15c.map(c=>c.l);
    const m15n = mC.length;
    _m15 = {
      n: m15n, O: mO, C: mC, H: mH, L: mL,
      e20:  _ema(mC, 20),
      e50:  _ema(mC, 50),
      e200: _ema(mC, 200),
      fvg:  _calcICTFVG(mO, mH, mL, mC, 100, 2),
      ob:   _calcOrderBlocks(mO, mH, mL, mC, 5, 0.0),
      atr:  _sma((() => { const t=[0]; for(let i=1;i<m15n;i++) t.push(Math.max(mH[i]-mL[i],Math.abs(mH[i]-mC[i-1]),Math.abs(mL[i]-mC[i-1]))); return t; })(), 14),
    };
  }

  seInds = {
    n, C, H, L, V,
    ict: _ict,
    ursi: _ursi,
    mom: C.map((c, idx) => idx >= 10 ? c - C[idx - 10] : null),
    mom10: _roc(C, 10),
    obv_oc:  _obvm.oc,
    obv_b5:  _obvm.b5,
    obv_ml:  _obvm.macdLine,
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
    macd_sig: (() => { const ml = _ema(C,12).map((v,idx)=>v-_ema(C,26)[idx]); return _ema(ml,9); })(),
    adx: _adxd.adx,
    dip: _adxd.dip,
    dim: _adxd.dim,
    ob:  _ob,
    m15: _m15,
    e13: _ema(C, 13),
    e34: _ema(C, 34),
    bb_up: (() => { const bb = _bollinger(C, 20, 2.0); return bb.up; })(),
    bb_dn: (() => { const bb = _bollinger(C, 20, 2.0); return bb.lo; })(),
    srsi_k: (() => { const s = _stochRsi(C, 14, 14, 3, 3); return s.k; })(),
    srsi_d: (() => { const s = _stochRsi(C, 14, 14, 3, 3); return s.d; })(),
  };
  _seIndsCacheTime = Date.now();
  } // end if(!_seCandlesStale)

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
    const priority=SE.regimePriority[seRegime]||['S00_MFKK'];
    const maxSig = SE.maxSignals[seRegime] || 2;
    for(const name of priority){
      if(pending.length >= maxSig) break;
      const fn=SE_STRATEGY_FNS[name];
      if(!fn) continue;
      const sig=fn(I,i,hour);
      if(sig){
        const cfg=SE.strategies[name];
        const atr_val = I.atr[i] || 10;
        // Risolvi ATR variants e strip simboli ($) → numero sempre numerico
        // Supporta qualsiasi formato ATR×N.N (es. ATR×3.0, ATR×1.2) via regex
        const _resolveATR = (v) => {
          if (typeof v !== 'string') return v;
          const m = v.match(/ATR[×x*](\d+\.?\d*)/i);
          if (m) return Math.round(atr_val * parseFloat(m[1]));
          if (v === 'ATR') return Math.round(atr_val * 2.0);
          return parseFloat(v.replace(/[^0-9.]/g,'')) || 20;
        };
        const tp = _resolveATR(cfg.tp);
        const sl = _resolveATR(cfg.sl);
        const isCounterTrend=(seRegime==='TREND_UP'&&sig.dir==='sell')||(seRegime==='TREND_DOWN'&&sig.dir==='buy');
        pending.push({name, label:cfg.label, dir:sig.dir, why:sig.why, tp, sl, pf:cfg.pf, wr:cfg.wr, quality:sig.quality||'medium', score:sig.score||null, counterTrend:isCounterTrend});
      }
    }
  }

  // MT5 data: ri-fetcha solo ogni 15s (bot synca ogni 20s).
  // Se fetch fallisce usa l'ultimo dato valido → evita flickering online/offline.
  if (!window._seLastMt5Data || Date.now() - _mt5LastFetchTime > 15000) {
    const fresh = await seFetchMt5Data();
    if (fresh) {
      window._seLastMt5Data = fresh;
      _mt5LastFetchTime = Date.now();
    }
  }
  const mt5Data = window._seLastMt5Data || null;

  seRender(mt5Data, pending, snap, isExtreme, inSession, hour);

  // Push AI score al DB ogni 60s così il bot Python può leggerlo
  const nowTs = Date.now();
  if (nowTs - _lastScorePush > 60000) {
    const score = dashContext?.confidence?.score;
    if (typeof score === 'number') {
      _lastScorePush = nowTs;
      fetch('/api/db', { method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ action:'score_push', score }) }).catch(()=>{});
    }
  }

  _seRefreshRunning = false;
}

async function seFetchMt5Data() {
  try {
    const r=await fetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'mt5_get'})});
    const j=await r.json();
    return j.ok ? j.data : null;
  } catch(e) { return null; }
}


