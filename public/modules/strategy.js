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
  // AUTO-TRADING BROWSER: se true, il browser invia segnali al bot via UI.
  // SEMPRE false al caricamento — il bot trada autonomamente in background.
  // Abilita manualmente col toggle solo se vuoi doppio invio dal browser.
  autoTrade: false,
  _autoExecuted: new Set(),  // dedup: strategy_dir_5minWindow
  strategies: {
    // ── STRATEGIE ATTIVE [BACKTEST MT5 GOLD · lot 0.01 · $1/punto] ──
    // Sistema adattivo H1 (2026-04-28): 1504 trade · WR 44.3% · PF 1.584 · +$21.58/gg · DD $790 · 17/24 mesi+
    // Tutti i P&L sono riferiti a lot=0.01 su conto $1000 baseline
    'S00_MFKK': { label: 'MFKK Core [M30] V2', pf: 1.24, wr: '26.1%', tp: 'ATR×3.5', sl: 'ATR×1.0',
      stats: {
        pnl_1m: 55, td_1m: 2.4, pnl_6m: 330, td_6m: 2.4,
        pnl_12m: 660, td_12m: 2.4, pnl_24m: 1320, td_24m: 2.4,
        maxdd: 220, maxdd_pct: '2.2%', trades_12m: 637, best_regime: 'TREND/WEAK · fallback M30 (DI≥20 or ST bullish)'
      } },
    'S05_MFKK_INTRADAY': { label: 'MFKK Intraday [H1] V4', pf: 1.07, wr: '23.4%', tp: 'ATR×3.5', sl: 'ATR×1.0',
      stats: {
        pnl_1m: 3, td_1m: 0.39, pnl_6m: 18, td_6m: 0.39,
        pnl_12m: 36, td_12m: 0.39, pnl_24m: 72, td_24m: 0.39,
        maxdd: 180, maxdd_pct: '1.8%', trades_12m: 98, best_regime: 'TREND_UP/DOWN · H1 · London/NY only · ST aligned'
      } },
    'S09_MFKK_SCALPING': { label: 'MFKK Scalping [M30] V3', pf: 1.40, wr: '29.2%', tp: 'ATR×4.0', sl: 'ATR×1.0',
      stats: {
        pnl_1m: 36, td_1m: 0.38, pnl_6m: 216, td_6m: 0.38,
        pnl_12m: 432, td_12m: 0.38, pnl_24m: 864, td_24m: 0.38,
        maxdd: 150, maxdd_pct: '1.5%', trades_12m: 97, best_regime: 'VOLATILE/WEAK · M30 · 06-19h UTC · ST aligned'
      } },
    'S10_OB_FVG_SCALP': { label: 'OB+FVG Scalp [M30] V3', pf: 1.80, wr: '51.0%', tp: 'ATR×3.5', sl: 'ATR×1.2',
      stats: {
        pnl_1m: 27, td_1m: 0.09, pnl_6m: 163, td_6m: 0.09,
        pnl_12m: 325, td_12m: 0.09, pnl_24m: 651, td_24m: 0.09,
        maxdd: 120, maxdd_pct: '1.2%', trades_12m: 24, best_regime: 'WEAK/RANGE · M30 · ADX≥18 · ST aligned'
      } },
    'S16_GOLDEN_SQUEEZE': { label: 'Golden Squeeze [H1] V4', pf: 1.38, wr: '45.0%', tp: 'ATR×3.5', sl: 'ATR×2.0',
      stats: {
        pnl_1m: 46, td_1m: 0.44, pnl_6m: 276, td_6m: 0.44,
        pnl_12m: 552, td_12m: 0.44, pnl_24m: 1104, td_24m: 0.44,
        maxdd: 300, maxdd_pct: '3.0%', trades_12m: 115, best_regime: 'TREND · TF H1 · SELL countertrend only'
      } },
    'S17_CONVERGENCE_SCALP': { label: 'Convergence Scalp [H4] V2', pf: 1.75, wr: '35.3%', tp: 'ATR×4.0', sl: 'ATR×1.0',
      stats: {
        pnl_1m: 133, td_1m: 0.25, pnl_6m: 798, td_6m: 0.25,
        pnl_12m: 1596, td_12m: 0.25, pnl_24m: 3192, td_24m: 0.25,
        maxdd: 250, maxdd_pct: '2.5%', trades_12m: 62, best_regime: 'VOLATILE/TREND · TF H4 · EMA34/89 + StochRSI'
      } },
  },
  // ── REGIME PRIORITY ──
  regimePriority: {
    TREND_UP:   ['S16_GOLDEN_SQUEEZE', 'S05_MFKK_INTRADAY', 'S17_CONVERGENCE_SCALP'],
    TREND_DOWN: ['S16_GOLDEN_SQUEEZE', 'S05_MFKK_INTRADAY', 'S17_CONVERGENCE_SCALP'],
    WEAK_UP:    ['S10_OB_FVG_SCALP', 'S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK', 'S17_CONVERGENCE_SCALP'],
    WEAK_DOWN:  ['S10_OB_FVG_SCALP', 'S16_GOLDEN_SQUEEZE', 'S09_MFKK_SCALPING', 'S00_MFKK', 'S17_CONVERGENCE_SCALP'],
    VOLATILE:   ['S09_MFKK_SCALPING', 'S10_OB_FVG_SCALP', 'S17_CONVERGENCE_SCALP'],
    RANGE:      ['S10_OB_FVG_SCALP', 'S09_MFKK_SCALPING', 'S00_MFKK', 'S17_CONVERGENCE_SCALP'],
  },
  // Regime intelligence: max segnali simultanei per regime
  maxSignals: { TREND_UP: 3, TREND_DOWN: 3, WEAK_UP: 3, WEAK_DOWN: 3, RANGE: 3, VOLATILE: 1, UNKNOWN: 1 },
};

let seTimer = null;
let seInds = null;
let seRegime = 'UNKNOWN';
let _lastScorePush = 0;
// Trade history filter state (persiste attraverso i rebuild di seRender ogni 1s)
window._seTradeFilter = window._seTradeFilter || 'week';
window._seTradeFrom   = window._seTradeFrom   || '';
window._seTradeTo     = window._seTradeTo     || '';

// ── MAIN LOOP ────────────────────────────────────────────────────────────────
async function seRefresh() {
  // Non eseguire se il tab Strategy non è attivo — evita API calls e DOM churn inutili
  if(!document.getElementById('tp-strategy')?.classList.contains('on')) return;
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

  // Fetch real MT5 data and render
  const mt5Data = await seFetchMt5Data();
  window._seLastMt5Data = mt5Data; // cache per seSendTradeToMt5
  seRender(mt5Data, pending, snap, isExtreme, inSession, hour);

  // ── AUTO TRADING: esegui segnali senza click se toggle attivo ──────────
  if (SE.autoTrade && pending.length > 0 && mt5Data) {
    const syncAge = mt5Data.synced_at
      ? Math.round((Date.now() - new Date(mt5Data.synced_at).getTime()) / 1000)
      : 999;
    if (syncAge < 180) {
      const win5m = Math.floor(Date.now() / (5 * 60 * 1000));
      for (const s of pending) {
        const key = `${s.name}_${s.dir}_${win5m}`;
        if (!SE._autoExecuted.has(key)) {
          SE._autoExecuted.add(key);
          if (SE._autoExecuted.size > 100) SE._autoExecuted.clear();
          seSendTradeToMt5(s);
        }
      }
    }
  }

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
}

async function seFetchMt5Data() {
  try {
    const r=await fetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'mt5_get'})});
    const j=await r.json();
    return j.ok ? j.data : null;
  } catch(e) { return null; }
}

function seToggleAutoTrade() {
  SE.autoTrade = !SE.autoTrade;
  if (SE.autoTrade) SE._autoExecuted.clear();
  seToast(
    SE.autoTrade ? '📡 Browser auto-send ON (doppio invio — bot già trada in autonomo)' : '✅ Browser auto-send OFF — il bot trada in background',
    SE.autoTrade ? '#ffca28' : '#00e676'
  );
}
window.seToggleAutoTrade = seToggleAutoTrade;

// Nota: SE.autoTrade NON viene più letto dal DB al caricamento.
// Il bot trada autonomamente tramite live signal scan.
// Il toggle browser auto-send è per uso manuale opzionale (non necessario).

