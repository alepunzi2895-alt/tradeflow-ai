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
  strategies: {
    // ── BACKTEST REGIME-AWARE (multi-TF, ATR-based TP/SL, 2026-04-15) ──
    // MFKK Score: TP=20 / SL=10. PNL=+$34k
    'S00_MFKK': { label: 'MFKK Score', pf: 1.73, wr: '47.8%', tp: '$20', sl: '$10',
      stats: {
        pnl_1m: 1433, td_1m: 5.42,
        pnl_6m: 8600, td_6m: 5.92,
        pnl_12m: 17200, td_12m: 6.82,
        pnl_24m: 34404, td_24m: 6.54,
        maxdd: 264, maxdd_pct: '26.4%', trades_12m: 2110, best_regime: 'TREND'
      } },
    // MFKK Intraday: V3 Sell Exhaustion ultra-chirurgico. DD=0%
    'S05_MFKK_INTRADAY': { label: 'MFKK Intraday', pf: 16.5, wr: '91.7%', tp: 'ATR×1.5', sl: 'ATR×1',
      stats: {
        pnl_1m: 1, td_1m: 0.08,
        pnl_6m: 2, td_6m: 0.12,
        pnl_12m: 4, td_12m: 0.16,
        pnl_24m: 4, td_24m: 0.11,
        maxdd: 0, maxdd_pct: '0.1%', trades_12m: 40, best_regime: 'TUTTI'
      } },
    // MFKK Scalping — EMA stack + FVG retest · regime-ottimale: WEAK_UP H1 + WEAK_DOWN/VOLATILE M30
    // Backtest multi-TF 2026-04-15: 163 trade/24m · WR 40% · PF 2.44 · ATR×1.5/ATR×1 TP/SL
    'S09_MFKK_SCALPING': { label: 'MFKK Scalping', pf: 2.44, wr: '40%', tp: 'ATR×1.5', sl: 'ATR×1',
      stats: {
        pnl_1m: 22, td_1m: 0.32,
        pnl_6m: 133, td_6m: 0.32,
        pnl_12m: 265, td_12m: 0.32,
        pnl_24m: 531, td_24m: 0.32,
        maxdd: 75, maxdd_pct: '14%', trades_12m: 82, best_regime: 'WEAK'
      } },
    // Sell Exhaust — OBV bear + RSI>65 + ADX≥30 + MOM< · regime: TREND_UP H1
    // Backtest TREND_UP H1: WR 60.9% · PF 3.11 · 23 trade/24m · ATR×1.5/×1
    'S05_V3_Sell_Exhaust': { label: 'Sell Exhaust', pf: 3.11, wr: '60.9%', tp: 'ATR×1.5', sl: 'ATR×1',
      stats: {
        pnl_1m: 11, td_1m: 0.05,
        pnl_6m: 68, td_6m: 0.05,
        pnl_12m: 136, td_12m: 0.05,
        pnl_24m: 272, td_24m: 0.05,
        maxdd: 48, maxdd_pct: '5.5%', trades_12m: 12, best_regime: 'TREND_UP'
      } },
    // Exhaustion — ADX/DI spread + MACD crossover · regime: TREND_DOWN (M15 sul bot)
    // Backtest TREND_DOWN M15: WR 42% · PF 1.76 · 143 trade/24m · ATR×1.5/×1
    'S01_EXHAUSTION': { label: 'Exhaustion', pf: 1.76, wr: '42%', tp: 'ATR×1.5', sl: 'ATR×1',
      stats: {
        pnl_1m: 35, td_1m: 0.29,
        pnl_6m: 211, td_6m: 0.29,
        pnl_12m: 423, td_12m: 0.29,
        pnl_24m: 845, td_24m: 0.29,
        maxdd: 474, maxdd_pct: '56%', trades_12m: 72, best_regime: 'TREND_DOWN'
      } },
    // Struc Break — breakout 40-bar high/low con retest · regime: RANGE H1
    // Backtest RANGE H1: WR 42% · PF 1.87 · 50 trade/24m · ATR×1.5/×1
    'S13_STRUC_BREAK': { label: 'Struc Break', pf: 1.87, wr: '42%', tp: 'ATR×1.5', sl: 'ATR×1',
      stats: {
        pnl_1m: 5, td_1m: 0.10,
        pnl_6m: 30, td_6m: 0.10,
        pnl_12m: 60, td_12m: 0.10,
        pnl_24m: 120, td_24m: 0.10,
        maxdd: 37, maxdd_pct: '3.7%', trades_12m: 25, best_regime: 'RANGE'
      } },
    // OB+FVG Scalp — Order Block + FVG confluence · M15 · sempre attiva
    // Stats pending: esegui backtest_ob_fvg_scalp.py --mt5 per dati reali
    'S10_OB_FVG_SCALP': { label: 'OB+FVG Scalp', pf: null, wr: 'N/A', tp: 'ATR×1.0', sl: 'ATR×0.6',
      stats: {
        pnl_1m: null, td_1m: null,
        pnl_6m: null, td_6m: null,
        pnl_12m: null, td_12m: null,
        pnl_24m: null, td_24m: null,
        maxdd: null, maxdd_pct: 'N/A', trades_12m: null, best_regime: 'ALL'
      } },
  },
  // ── REGIME PRIORITY ──
  // Allineato con regime_playbook.json (backtest multi-TF 2026-04-15)
  regimePriority: {
    TREND_UP:   ['S10_OB_FVG_SCALP', 'S05_V3_Sell_Exhaust', 'S09_MFKK_SCALPING'],
    TREND_DOWN: ['S10_OB_FVG_SCALP',    'S01_EXHAUSTION',      'S09_MFKK_SCALPING'],
    WEAK_UP:    ['S10_OB_FVG_SCALP',    'S09_MFKK_SCALPING',   'S00_MFKK'],
    WEAK_DOWN:  ['S10_OB_FVG_SCALP',    'S09_MFKK_SCALPING',   'S00_MFKK'],
    VOLATILE:   ['S09_MFKK_SCALPING',   'S10_OB_FVG_SCALP'],
    RANGE:      ['S10_OB_FVG_SCALP',    'S13_STRUC_BREAK'],
  },
  // Regime intelligence: max segnali simultanei per regime
  maxSignals: { TREND_UP: 3, TREND_DOWN: 3, WEAK_UP: 3, WEAK_DOWN: 3, RANGE: 3, VOLATILE: 1, UNKNOWN: 1 },
};

let seTimer = null;
let seInds = null;
let seRegime = 'UNKNOWN';
let _lastScorePush = 0;

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

function _roc(src, p=10) {
  // Rate of Change % — proxy momentum
  return src.map((v,i) => i<p || !src[i-p] ? null : (v-src[i-p])/src[i-p]*100);
}

function _adxSma(H, L, C, p=14) {
  // ADX con SMA(DX, p) — corrisponde all'indicatore custom usato nel backtester
  const n=C.length;
  const TR=[0], DMP=[0], DMM=[];
  DMM.push(0);
  for(let i=1;i<n;i++){
    TR.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));
    const up=H[i]-H[i-1], dn=L[i-1]-L[i];
    DMP.push(up>dn&&up>0?up:0);
    DMM.push(dn>up&&dn>0?dn:0);
  }
  const sT=[0],sP=[0],sM=[0];
  for(let i=1;i<n;i++){
    sT.push(sT[i-1]-sT[i-1]/p+TR[i]);
    sP.push(sP[i-1]-sP[i-1]/p+DMP[i]);
    sM.push(sM[i-1]-sM[i-1]/p+DMM[i]);
  }
  const DIP=sT.map((t,i)=>t>0?sP[i]/t*100:0);
  const DIM=sT.map((t,i)=>t>0?sM[i]/t*100:0);
  const DX=DIP.map((dp,i)=>{
    const s=dp+DIM[i]; return s>0?Math.abs(dp-DIM[i])/s*100:0;
  });
  return { adx:_sma(DX,p), dip:DIP, dim:DIM };
}

// ── INDICATOR HELPERS (extra) ────────────────────────────────────────────────
function _stdev(src, p) {
  const out = [];
  for(let i = 0; i < src.length; i++) {
    if(i < p-1) { out.push(null); continue; }
    let sum = 0;
    for(let j = 0; j < p; j++) sum += (src[i-j] ?? 0);
    const mn = sum / p;
    let sq = 0;
    for(let j = 0; j < p; j++) sq += ((src[i-j] ?? mn) - mn) ** 2;
    out.push(Math.sqrt(sq / p));
  }
  return out;
}

function _dema(src, len) {
  const ma1 = _ema(src, len);
  const ma2 = _ema(ma1, len);
  return ma1.map((v, i) => 2 * v - ma2[i]);
}

function _rmaTV(src, p) {
  const o = new Array(src.length).fill(null);
  const k = 1 / p;
  let sum = 0;
  let len = 0;
  for (let i = 0; i < src.length; i++) {
    if (src[i] === null) continue;
    len++;
    if (len <= p) {
      sum += src[i];
      if (len === p) o[i] = sum / p;
    } else {
      o[i] = src[i] * k + o[i-1] * (1 - k);
    }
  }
  return o;
}

/**
 * Ultimate RSI [LuxAlgo] — traduzione Pine Script
 * Applica aggiustamento direzionale alla formula base RSI tramite range massimo-minimo.
 */
function _calcUltimateRSI(C, length = 14, smooth = 14) {
  const n = C.length;
  const upper = new Array(n).fill(null);
  const lower = new Array(n).fill(null);
  
  for (let i = length - 1; i < n; i++) {
    let high = -Infinity;
    let low = Infinity;
    for (let j = 0; j < length; j++) {
      if (C[i-j] > high) high = C[i-j];
      if (C[i-j] < low) low = C[i-j];
    }
    upper[i] = high;
    lower[i] = low;
  }
  
  const diff = new Array(n).fill(null);
  for (let i = 1; i < n; i++) {
    const d = C[i] - C[i-1];
    if (upper[i] !== null && upper[i-1] !== null) {
      const r = upper[i] - lower[i];
      if (upper[i] > upper[i-1]) {
        diff[i] = r;
      } else if (lower[i] < lower[i-1]) {
        diff[i] = -r;
      } else {
        diff[i] = d;
      }
    } else {
      diff[i] = d;
    }
  }
  
  const absDiff = diff.map(x => x === null ? null : Math.abs(x));
  
  const num_rma = _rmaTV(diff, length);
  const den_rma = _rmaTV(absDiff, length);
  
  const arsi = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (num_rma[i] !== null && den_rma[i] !== null) {
      arsi[i] = den_rma[i] === 0 ? 50 : (num_rma[i] / den_rma[i]) * 50 + 50;
    }
  }
  
  const signal = new Array(n).fill(null);
  const k_ema = 2 / (smooth + 1);
  let ema_v = null;
  for (let i = 0; i < n; i++) {
    if (arsi[i] === null) continue;
    if (ema_v === null) {
      ema_v = arsi[i];
      signal[i] = ema_v;
    } else {
      ema_v = arsi[i] * k_ema + ema_v * (1 - k_ema);
      signal[i] = ema_v;
    }
  }
  
  return { arsi, signal };
}

/**
 * OBV MACD Indicator — traduzione Pine Script v4
 * 1. OBV normalizzato a price-scale
 * 2. DEMA(9) come MA veloce volume-based
 * 3. MACD = DEMA(9,out) - EMA(26,close)  → divergenza volume vs prezzo
 * 4. T-Channel sul MACD → segnale su cambio direzione (oc: 1=bull, -1=bear)
 * Nota: LinReg con len5=2 semplifica a tt1=macd[i] (identico matematicamente)
 */
function _calcOBVMACD(C, H, L, V) {
  const n = C.length;

  // 1. OBV: cum(sign(change(close)) * volume)
  const obv = [0];
  for(let i = 1; i < n; i++) {
    const s = C[i] > C[i-1] ? 1 : C[i] < C[i-1] ? -1 : 0;
    obv.push(obv[i-1] + s * (V[i] || 0));
  }

  // 2. price_spread = stdev(high-low, 28)
  const hl = H.map((h, i) => h - L[i]);
  const priceSpread = _stdev(hl, 28);

  // 3. smooth = sma(obv, 14) ; v_spread = stdev(obv-smooth, 28)
  const smooth = _sma(obv, 14);
  const vDiff  = obv.map((v, i) => smooth[i] != null ? v - smooth[i] : 0);
  const vSpread = _stdev(vDiff, 28);

  // 4. out = shadow>0 ? high+shadow : low+shadow
  const obvOut = C.map((c, i) => {
    if(smooth[i] == null || !vSpread[i] || !priceSpread[i]) return c;
    const shadow = (obv[i] - smooth[i]) / vSpread[i] * priceSpread[i];
    return shadow > 0 ? H[i] + shadow : L[i] + shadow;
  });

  // 5. DEMA(9) di obvOut — MA veloce volume-normalized
  const dema9 = _dema(obvOut, 9);

  // 6. slow_ma = EMA(close, 26) ; macd = dema9 - slow_ma
  const slowMa   = _ema(C, 26);
  const macdLine = dema9.map((v, i) => v - slowMa[i]);

  // 7. T-Channel (p=1) — alex grover
  // b5 si aggiorna solo quando macd supera b5 ± a15 (media deviazioni cumulative)
  // oc: 1=rialzista, -1=ribassista
  const b5 = new Array(n);
  const oc = new Array(n);
  b5[0] = macdLine[0]; oc[0] = 0;
  let cumDev = 0;
  for(let i = 1; i < n; i++) {
    cumDev += Math.abs(macdLine[i] - b5[i-1]);
    const a15 = cumDev / i;  // p=1, n5=i
    if(macdLine[i] > b5[i-1] + a15)      b5[i] = macdLine[i];
    else if(macdLine[i] < b5[i-1] - a15) b5[i] = macdLine[i];
    else                                   b5[i] = b5[i-1];
    oc[i] = b5[i] > b5[i-1] ? 1 : b5[i] < b5[i-1] ? -1 : oc[i-1];
  }

  return { macdLine, b5, oc };
}

/**
 * ICT Institutional Order Flow logic
 * Identifica Displacement candele (range > 2x stdev) e FVGs attivi (Bullish/Bearish).
 * Ritorna un segnale quando un FVG attivo viene mitigato (ossia quando il prezzo lo tocca).
 */
function _calcICTOrderFlow(O, H, L, C) {
  const n = C.length;
  const candleBody = new Array(n);
  for(let i=0; i<n; i++) candleBody[i] = Math.abs(O[i] - C[i]);
  // Use length 100 for stdev as in the pine script defaults
  const std = _stdev(candleBody, 100);
  
  const activeFvgs = [];
  const signals = new Array(n).fill(null);
  
  for(let i=2; i<n; i++) {
    // 1. Check mitigations of existing FVGs
    for(let j=activeFvgs.length-1; j>=0; j--) {
      let fvg = activeFvgs[j];
      let mitigated = false;
      if (fvg.type === 'bull' && L[i] <= fvg.top) {
        mitigated = true;
        signals[i] = {dir: 'buy', val: fvg.top};
      } else if (fvg.type === 'bear' && H[i] >= fvg.bottom) {
        mitigated = true;
        signals[i] = {dir: 'sell', val: fvg.bottom};
      }
      if (mitigated) {
        activeFvgs.splice(j, 1);
      }
    }
    
    if (std[i-1] == null) continue;
    
    // 2. Look for new FVGs
    const dispFactor = 2; // Fixed default factor
    const isDisplaced = candleBody[i-1] > (std[i-1] * dispFactor);
    
    const isBullFvg = L[i] > H[i-2] && C[i-1] > O[i-1];
    const isBearFvg = H[i] < L[i-2] && O[i-1] > C[i-1];
    
    if (isBullFvg && isDisplaced) {
      activeFvgs.push({ type: 'bull', top: L[i], bottom: H[i-2] });
    }
    if (isBearFvg && isDisplaced) {
      activeFvgs.push({ type: 'bear', top: L[i-2], bottom: H[i] });
    }
    
    // Safety size
    if (activeFvgs.length > 20) activeFvgs.shift();
  }
  
  return { signals, activeFvgs };
}

/**
 * Order Block Finder — traduzione Pine Script (© wugamlo, MPL 2.0)
 * Bullish OB: ultima candela ROSSA prima di `periods` candele verdi consecutive + move% >= threshold
 *   → zona: Open[OB] (high) … Low[OB] (low)
 * Bearish OB: ultima candela VERDE prima di `periods` candele rosse consecutive + move% >= threshold
 *   → zona: High[OB] (high) … Open[OB] (low)
 *
 * Il segnale di TRADING si attiva quando il PREZZO CORRENTE RITORNA nella zona OB attiva.
 * Gli OB già "mitigati" (prezzo passato oltre il limite estremo) vengono scartati.
 */
function _calcOrderBlocks(O, H, L, C, periods=5, threshold=0.0) {
  const n = C.length;
  const ob_period = periods + 1; // offset OB candle rispetto all'ultimo candle del run
  const bullOBs = [], bearOBs = [];

  // Scansione: per ogni posizione i, il potenziale OB è a obIdx = i - ob_period
  // Le candele "consecutive" sono da i-periods a i-1
  for (let i = ob_period; i < n; i++) {
    const obIdx  = i - ob_period;
    const prevIdx = i - 1;
    if (obIdx < 0) continue;

    // % move dal close dell'OB al close della candela più recente del run (= close[1] in Pine)
    const absmove = C[obIdx] !== 0 ? Math.abs((C[obIdx] - C[prevIdx]) / C[obIdx]) * 100 : 0;
    if (absmove < threshold) continue;

    // Conta candele consecutive dopo l'OB
    let upCnt = 0, dnCnt = 0;
    for (let j = i - periods; j <= prevIdx; j++) {
      if (C[j] > O[j]) upCnt++;
      if (C[j] < O[j]) dnCnt++;
    }

    // Bullish OB: candela rossa + tutte le successive verdi
    if (C[obIdx] < O[obIdx] && upCnt === periods) {
      bullOBs.push({ bar: obIdx, high: O[obIdx], low: L[obIdx], avg: (O[obIdx]+L[obIdx])/2 });
    }
    // Bearish OB: candela verde + tutte le successive rosse
    if (C[obIdx] > O[obIdx] && dnCnt === periods) {
      bearOBs.push({ bar: obIdx, high: H[obIdx], low: O[obIdx], avg: (H[obIdx]+O[obIdx])/2 });
    }
  }

  // Filtra OB già "mitigati" — il prezzo ha già violato il limite estremo
  const activeBull = bullOBs.filter(ob => {
    for (let j = ob.bar + 1; j < n; j++) if (L[j] < ob.low) return false;
    return true;
  });
  const activeBear = bearOBs.filter(ob => {
    for (let j = ob.bar + 1; j < n; j++) if (H[j] > ob.high) return false;
    return true;
  });

  const latestBull = activeBull.length ? activeBull[activeBull.length-1] : null;
  const latestBear = activeBear.length ? activeBear[activeBear.length-1] : null;
  return { bullOBs: activeBull, bearOBs: activeBear, latestBull, latestBear };
}

/**
 * ICT Institutional Order Flow — FVG + Displacement (© fadizeidan MPL 2.0, adattato)
 * Estrae i pattern tradabili dal Pine Script:
 *   - FVG Bullish:  L[i] > H[i-2]  (gap rialzista tra candela corrente e 2 fa)
 *   - FVG Bearish:  H[i] < L[i-2]  (gap ribassista)
 *   - Displacement: body[i-1] > stdev(body, stdLen) * factor (candela centrale grande)
 * Tiene traccia degli FVG attivi non ancora mitigati.
 * Segnale: prezzo entra nella zona FVG non mitigata.
 */
function _calcICTFVG(O, H, L, C, stdLen=100, displFactor=2) {
  const n = C.length;
  const body = C.map((c, i) => Math.abs(O[i] - c));
  const bodyStd = _stdev(body, stdLen);

  const activeBullFVG = [];  // {open, close, mid, bar} — open=high[i-2], close=low[i]
  const activeBearFVG = [];  // {open, close, mid, bar} — open=low[i-2], close=high[i]
  const signalsBull = new Array(n).fill(null);
  const signalsBear = new Array(n).fill(null);

  for (let i = 2; i < n; i++) {
    // Displacement: la candela centrale (i-1) è > factor * stdev
    const displaced = bodyStd[i-1] != null && body[i-1] > bodyStd[i-1] * displFactor;

    // Bullish FVG: gap tra H[i-2] e L[i]
    if (L[i] > H[i-2]) {
      activeBullFVG.push({ open: H[i-2], close: L[i], mid: (H[i-2]+L[i])/2, bar: i, displaced });
    }
    // Bearish FVG: gap tra L[i-2] e H[i]
    if (H[i] < L[i-2]) {
      activeBearFVG.push({ open: L[i-2], close: H[i], mid: (L[i-2]+H[i])/2, bar: i, displaced });
    }

    // Verifica mitigazione e genera segnale
    for (let j = activeBullFVG.length - 1; j >= 0; j--) {
      const fvg = activeBullFVG[j];
      if (fvg.bar === i) continue; // appena creato
      if (L[i] <= fvg.open) { activeBullFVG.splice(j, 1); continue; } // mitigato
      if (C[i] <= fvg.close && C[i] >= fvg.open) { // prezzo entra nella zona FVG
        signalsBull[i] = fvg;
      }
    }
    for (let j = activeBearFVG.length - 1; j >= 0; j--) {
      const fvg = activeBearFVG[j];
      if (fvg.bar === i) continue;
      if (H[i] >= fvg.open) { activeBearFVG.splice(j, 1); continue; } // mitigato
      if (C[i] >= fvg.close && C[i] <= fvg.open) { // prezzo entra nella zona FVG
        signalsBear[i] = fvg;
      }
    }
    if (activeBullFVG.length > 20) activeBullFVG.shift();
    if (activeBearFVG.length > 20) activeBearFVG.shift();
  }

  // Latest active (non-mitigated) FVGs for UI display
  const latestBullFVG = activeBullFVG.length ? activeBullFVG[activeBullFVG.length-1] : null;
  const latestBearFVG = activeBearFVG.length ? activeBearFVG[activeBearFVG.length-1] : null;
  return { signalsBull, signalsBear, latestBullFVG, latestBearFVG, activeBullFVG, activeBearFVG };
}

// ── STRATEGY LOGIC ───────────────────────────────────────────────────────────
// Solo MFKK Score e MFKK HighWR attive.
// Nuove strategie da indicatori TradingView verranno aggiunte qui come S01_*, S02_*, ecc.
const SE_STRATEGY_FNS = {
  // S00_MFKK: usa il punteggio MFKK già calcolato in mfkk.js (via dashContext.mfkk)
  // Zona ottimale 80-89 WR 58.8% · SELL da ≥75 · BUY solo ≥90 (più selettivo)
  S00_MFKK: (I,i) => {
    const m = dashContext?.mfkk;
    if(!m || !m.score) return null;
    const score = m.score;
    const dir = (m.dir||'').toUpperCase();
    if(dir==='SELL' && score>=75){
      const q = score>=90?'🔥 FORTE':score>=80?'✅ BUONO':'⚠️ MODERATO';
      return {dir:'sell', why:`MFKK ${q} ${score}/100 · SELL · ADX+MACD+CCI allineati`, score, quality: score>=80?'high':'medium'};
    }
    if(dir==='BUY' && score>=90){
      return {dir:'buy', why:`MFKK 🔥 FORTE ${score}/100 · BUY · Confluenza massima`, score, quality:'high'};
    }
    return null;
  },
  // S01_OBV_MACD: T-Channel del MACD volume-based
  // BUY: canale T cambia direzione da -1 a +1 (cambio impulso rialzista)
  // SELL: canale T cambia direzione da +1 a -1 (cambio impulso ribassista)
  S01_OBV_MACD: (I, i) => {
    if(!I.obv_oc || i < 1) return null;
    const oc = I.obv_oc;
    if(oc[i] === 1 && oc[i-1] !== 1) {
      const v = I.obv_ml?.[i];
      const str = v > 0 ? 'momentum positivo' : 'inversione da ribasso';
      return {dir:'buy',  why:`OBV MACD ↑ T-Channel rialzista · ${str} · divergenza volume-prezzo`, quality:'medium'};
    }
    if(oc[i] === -1 && oc[i-1] !== -1) {
      const v = I.obv_ml?.[i];
      const str = v < 0 ? 'momentum negativo' : 'inversione da rialzo';
      return {dir:'sell', why:`OBV MACD ↓ T-Channel ribassista · ${str} · pressione vendita OBV`, quality:'medium'};
    }
    return null;
  },

  // S02_OBV_SELL: SELL ONLY · V4 vincitore backtest H1 GC=F 730gg
  // Condizioni: OBV T-Channel ribassista (oc=-1) + RSI>55 (zona OB) + ADX≥20 (trend) + Momentum ROC<0
  // WR 42.8% · PF 2.037 · P&L $2,154 · MaxDD $486 · 285 trade · TP=2xATR / SL=1xATR
  S02_OBV_SELL: (I, i) => {
    if(!I.obv_oc || i < 1) return null;
    const oc  = I.obv_oc[i];
    const rsi = I.rsi[i];
    const adx = I.adx[i];
    const mom = I.mom10?.[i];
    if(oc == null || rsi == null || adx == null || mom == null) return null;
    if(oc === -1 && rsi > 55 && adx >= 20 && mom < 0) {
      return {
        dir: 'sell',
        why: `OBV SELL · OBV bear T-Channel · RSI ${rsi.toFixed(0)} OB · ADX ${adx.toFixed(0)} · Mom ROC↓ · WR 43% PF 2.04`,
        quality: 'medium',
      };
    }
    return null;
  },

  // S00_MFKK_HWR: HIGH WIN RATE SELL — 84.2% WR su 730gg H1 XAU
  // Condizioni hard: ADX≥35 + DI spread≥20 + MACD diff≥0.5 + CCI non OS
  // NOTA: usa dashContext.mfkk per ADX/DIM/DIP reali
  S00_MFKK_HWR: (I,i) => {
    const m = dashContext?.mfkk;
    if(!m) return null;
    const adx = m.adx ?? I.adx[i];
    const dip = m.dip ?? I.dip[i];
    const dim = m.dim ?? I.dim[i];
    const mh  = m.macd ?? I.macd[i];
    if(!adx || adx<35 || !mh) return null;
    const spread = Math.abs((dip||0)-(dim||0));
    if(spread < 20) return null;
    if((dim||0) > (dip||0) && Math.abs(mh) >= 0.5 && mh > 0){
      if(m.cciScore && m.cciScore < 65) return null;
      return {dir:'sell', why:`💎 HIGH-WR SELL · ADX ${adx?.toFixed(0)} spread ${spread?.toFixed(0)} MACD ${mh?.toFixed(2)} · WR 84% su 730gg`, score:100, quality:'elite'};
    }
    return null;
  },

  // S02_ULTIMATE_RSI: Crossover di Ultimate RSI con la sua Signal Line
  S02_ULTIMATE_RSI: (I, i) => {
    if (!I.ursi || i < 1) return null;
    const a0 = I.ursi.arsi[i-1];
    const a1 = I.ursi.arsi[i];
    const s0 = I.ursi.signal[i-1];
    const s1 = I.ursi.signal[i];

    if (a1 == null || s1 == null) return null;

    // Crossover
    const crossUp = a0 <= s0 && a1 > s1;
    const crossDn = a0 >= s0 && a1 < s1;

    // Aggiustiamo i livelli estremi per ottimizzare su XAU H1
    if (crossUp && a1 < 40) {
      return {dir:'buy', why:`Ultimate RSI ↑ Crossover Rialzista (Val = ${a1.toFixed(1)}) · Rimbalzo zona OS`, quality:'high'};
    }
    if (crossDn && a1 > 60) {
      return {dir:'sell', why:`Ultimate RSI ↓ Crossover Ribassista (Val = ${a1.toFixed(1)}) · Esaurimento zona OB`, quality:'high'};
    }
    
    return null;
  },

  // S03_MOMENTUM: Segnale su inversione e cross dello zero
  S03_MOMENTUM: (I, i) => {
    if (!I.mom || i < 1) return null;
    const m0 = I.mom[i-1];
    const m1 = I.mom[i];

    if (m0 == null || m1 == null) return null;

    // Cross positivo sopra lo zero (inversione rialzista)
    if (m0 <= 0 && m1 > 0) {
      return {dir:'buy', why:`Momentum > 0 (Inversione Positiva) · Val = ${m1.toFixed(2)}`, quality:'medium'};
    }
    // Cross negativo sotto lo zero (inversione ribassista)
    if (m0 >= 0 && m1 < 0) {
      return {dir:'sell', why:`Momentum < 0 (Inversione Negativa) · Val = ${m1.toFixed(2)}`, quality:'medium'};
    }
    
    return null;
  },

  // S04_ICT_ORDERFLOW: Mitigazione di un Fair Value Gap post Displacement
  S04_ICT_ORDERFLOW: (I, i) => {
    if (!I.ict || !I.ict.signals) return null;
    const sig = I.ict.signals[i];
    if (sig) {
       if (sig.dir === 'buy') return {dir:'buy', why:`ICT Order Flow ↑ · Mitigazione Bullish FVG area $${sig.val?.toFixed(2)}`, quality:'high'};
       if (sig.dir === 'sell') return {dir:'sell', why:`ICT Order Flow ↓ · Mitigazione Bearish FVG area $${sig.val?.toFixed(2)}`, quality:'high'};
    }
    return null;
  },

  // S05_MFKK_INTRADAY: V3 Sell Exhaustion — migliore variante da backtest MT5 GOLD H1 730gg
  // Condizioni: OBV bear + RSI>55 + ADX≥20 + Momentum negativo
  S05_MFKK_INTRADAY: (I, i) => {
    if (!I.obv_oc || i < 1) return null;
    const oc  = I.obv_oc[i];
    const rsi = I.rsi?.[i];
    const a   = I.adx?.[i];
    const m   = I.mom?.[i];
    if (rsi == null || a == null || m == null) return null;

    // V3 Sell Exhaustion
    if (oc === -1 && rsi > 55 && a >= 20 && m < 0) {
      return {dir:'sell', why:`MFKK Intraday ↓ Sell Exhaustion · OBV Bear · RSI ${rsi.toFixed(0)}>55 · ADX ${a.toFixed(0)}≥20 · Mom ROC negativo`, quality:'high'};
    }
    return null;
  },

  // S09_MFKK_SCALPING: MFKK Scalping — EMA stack H1 (20>50>100>200) + FVG M15 + OB H1
  // Logica:
  //   Filtro H1: EMA stack allineato (20>50>100>200 bull | bear)
  //   Trigger M15: Bullish/Bearish FVG attivo (prezzo in zona mitigazione)
  //   Boost: Displacement su candela FVG → qualità HIGH
  //   ELITE: FVG M15 + Displacement + OB H1 confluente (multi-TF)
  // TP: ATR×1.5 | SL: ATR×1 (gestiti da _resolveATR in seRefresh)
  S09_MFKK_SCALPING: (I, i) => {
    // ── Filtro EMA stack H1 ──────────────────────────────────────
    const e20h  = I.e20?.[i],  e50h  = I.e50?.[i];
    const e100h = I.e100?.[i], e200h = I.e200?.[i];
    if (e20h==null || e50h==null || e100h==null || e200h==null) return null;
    const bullStackH1 = e20h > e50h && e50h > e100h && e100h > e200h;
    const bearStackH1 = e20h < e50h && e50h < e100h && e100h < e200h;
    if (!bullStackH1 && !bearStackH1) return null;

    // ── FVG M15 ─────────────────────────────────────────────────
    const m15 = I.m15;
    if (!m15 || !m15.fvg) return null;
    const fvg = m15.fvg;
    const mi  = m15.n - 1;
    const bullFVG = fvg.signalsBull?.[mi];
    const bearFVG = fvg.signalsBear?.[mi];

    // ── OB H1 proximity ─────────────────────────────────────────
    const ob    = I.ob;
    const price = I.C[i];
    const nearBullOB = ob?.latestBull && price >= ob.latestBull.low && price <= ob.latestBull.high * 1.002;
    const nearBearOB = ob?.latestBear && price >= ob.latestBear.low * 0.998 && price <= ob.latestBear.high;

    // ── BUY: EMA stack H1 bull + Bullish FVG M15 ────────────────
    if (bullStackH1 && bullFVG) {
      const hasDispl = bullFVG.displaced;
      const quality  = nearBullOB ? 'elite' : hasDispl ? 'high' : 'medium';
      const obNote   = nearBullOB ? ' + OB H1 ✦' : '';
      const dNote    = hasDispl   ? ' · Displacement' : '';
      return {
        dir: 'buy',
        why: `MFKK Scalp ↑ EMA 20>50>100>200 H1 · Bullish FVG M15 $${bullFVG.open?.toFixed(0)}–$${bullFVG.close?.toFixed(0)}${dNote}${obNote}`,
        quality,
      };
    }

    // ── SELL: EMA stack H1 bear + Bearish FVG M15 ───────────────
    if (bearStackH1 && bearFVG) {
      const hasDispl = bearFVG.displaced;
      const quality  = nearBearOB ? 'elite' : hasDispl ? 'high' : 'medium';
      const obNote   = nearBearOB ? ' + OB H1 ✦' : '';
      const dNote    = hasDispl   ? ' · Displacement' : '';
      return {
        dir: 'sell',
        why: `MFKK Scalp ↓ EMA 20<50<100<200 H1 · Bearish FVG M15 $${bearFVG.close?.toFixed(0)}–$${bearFVG.open?.toFixed(0)}${dNote}${obNote}`,
        quality,
      };
    }

    return null;
  },

  // S05_V3_Sell_Exhaust — OBV T-Channel bear + RSI>65 + ADX≥30 + MOM< (TREND_UP exhaustion)
  S05_V3_Sell_Exhaust: (I, i) => {
    if (!I.obv_oc || i < 1) return null;
    const oc  = I.obv_oc[i];
    const rsi = I.rsi?.[i];
    const adx = I.adx?.[i];
    const mom = I.mom?.[i];
    if (rsi == null || adx == null || mom == null) return null;
    if (oc === -1 && rsi > 65 && adx >= 30 && mom < 0) {
      return { dir: 'sell', why: `Sell Exhaust ↓ OBV Bear · RSI ${rsi.toFixed(0)}>65 · ADX ${adx.toFixed(0)}≥30 · Mom<0`, quality: 'high' };
    }
    return null;
  },

  // S01_EXHAUSTION — ADX/DI divergenza + MACD vs signal (approssimazione H1 della strategia M15)
  S01_EXHAUSTION: (I, i) => {
    const adx = I.adx?.[i], dp = I.dip?.[i], dm = I.dim?.[i];
    const ml  = I.macd?.[i], ms = I.macd_sig?.[i] ?? I.macd_signal?.[i];
    if (adx == null || dp == null || dm == null || ml == null || ms == null) return null;
    const diff = ml - ms; const spread = Math.abs(dp - dm);
    if (adx >= 30 && dm > dp && spread >= 15 && diff >= 1.0) {
      return { dir: 'sell', why: `Exhaustion ↓ ADX ${adx.toFixed(0)}≥30 · DM>DP spread ${spread.toFixed(0)} · MACD diff +${diff.toFixed(1)}`, quality: 'medium' };
    }
    if (adx >= 28 && dp > dm && spread >= 15 && diff <= -1.0) {
      return { dir: 'buy', why: `Exhaustion ↑ ADX ${adx.toFixed(0)}≥28 · DP>DM spread ${spread.toFixed(0)} · MACD diff ${diff.toFixed(1)}`, quality: 'medium' };
    }
    return null;
  },

  // S13_STRUC_BREAK — breakout 40-bar high/low con retest immediato (RANGE)
  S13_STRUC_BREAK: (I, i) => {
    if (i < 60) return null;
    const H = I.H, L = I.L, C = I.C;
    if (!H || !L || !C) return null;
    const hh = Math.max(...H.slice(i-40, i));
    const ll  = Math.min(...L.slice(i-40, i));
    const c   = C[i], lo = L[i], hi = H[i];
    if (c > hh && lo <= hh * 1.001 && lo >= hh * 0.999) {
      return { dir: 'buy', why: `Struc Break ↑ Breakout + retest max 40 barre $${hh.toFixed(2)}`, quality: 'high' };
    }
    if (c < ll && hi >= ll * 0.999 && hi <= ll * 1.001) {
      return { dir: 'sell', why: `Struc Break ↓ Breakout + retest min 40 barre $${ll.toFixed(2)}`, quality: 'high' };
    }
    return null;
  },

  // S10_OB_FVG_SCALP — ICT Order Block + FVG Confluence Scalping · M15 always-on
  // LONG : EMA20>EMA50 + price in Bullish OB body + Bull FVG attivo + candela bullish
  // SHORT: EMA20<EMA50 + price in Bearish OB body + Bear FVG attivo + candela bearish
  S10_OB_FVG_SCALP: (I, i) => {
    const {O, H, L, C, e20, e50, fvg_bull, fvg_bear} = I;
    if (!e20?.[i] || !e50?.[i] || !C || !O) return null;

    const LB = 20;
    let ob_b = false, ob_s = false;

    // ── Bullish OB detection ────────────────────────────────────────────────
    for (let j = i - 3; j >= Math.max(i - LB - 1, 2); j--) {
      if (C[j] >= O[j]) continue;                       // deve essere bearish
      const ob_lo = Math.min(O[j], C[j]);
      const ob_hi = Math.max(O[j], C[j]);
      if (!(C[j+1] > O[j+1] && j+2 <= i && C[j+2] > O[j+2])) continue; // impulso bullish
      let mitig = false;
      for (let k = j+1; k < i; k++) { if (L[k] < ob_lo * 0.999) { mitig = true; break; } }
      if (mitig) continue;
      if (C[i] >= ob_lo * 0.999 && C[i] <= ob_hi * 1.002) { ob_b = true; break; }
    }

    // ── Bearish OB detection ────────────────────────────────────────────────
    for (let j = i - 3; j >= Math.max(i - LB - 1, 2); j--) {
      if (C[j] <= O[j]) continue;                       // deve essere bullish
      const ob_lo = Math.min(O[j], C[j]);
      const ob_hi = Math.max(O[j], C[j]);
      if (!(C[j+1] < O[j+1] && j+2 <= i && C[j+2] < O[j+2])) continue; // impulso bearish
      let mitig = false;
      for (let k = j+1; k < i; k++) { if (H[k] > ob_hi * 1.001) { mitig = true; break; } }
      if (mitig) continue;
      if (C[i] >= ob_lo * 0.998 && C[i] <= ob_hi * 1.001) { ob_s = true; break; }
    }

    const fvg_b = fvg_bull?.[i];
    const fvg_s = fvg_bear?.[i];
    const bull_c = C[i] > O[i];
    const bear_c = C[i] < O[i];

    if (e20[i] > e50[i] && ob_b && fvg_b && bull_c) {
      return { dir: 'buy', why: `OB+FVG Bull ▲ EMA20>${e20[i].toFixed(0)} prezzo in Bullish OB + Bull FVG`, quality: 'high', score: 88 };
    }
    if (e20[i] < e50[i] && ob_s && fvg_s && bear_c) {
      return { dir: 'sell', why: `OB+FVG Bear ▼ EMA20<${e20[i].toFixed(0)} prezzo in Bearish OB + Bear FVG`, quality: 'high', score: 88 };
    }
    return null;
  },
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
        const _resolveATR = (v) =>
          v==='ATR×1.5' ? Math.round(atr_val*1.5) :
          v==='ATR×1'   ? Math.round(atr_val*1.0) :
          v==='ATR'     ? Math.round(atr_val*2.0) :
          typeof v==='string' ? (parseFloat(v.replace(/[^0-9.]/g,''))||20) : v;
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
  // Bot online = sincronizzato negli ultimi 90s (sync ogni 20s, margine abbondante)
  const botOnline=syncAge!==null&&syncAge<90;
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
        Strategie attive: ${(SE.regimePriority[seRegime]||['S00_MFKK']).map(n=>`<b>${SE.strategies[n]?.label||n}</b>`).join(' › ')}
      </div>
    </div>
    <div style="text-align:right">
      <div style="font-size:9px;color:var(--dim);margin-bottom:2px">PROFITTO REALIZZATO (MT5)</div>
      <div style="font-size:18px;font-weight:800;color:${pnlOggi>0?'var(--green)':pnlOggi<0?'var(--red)':'var(--fg)'}">${pnlOggi>=0?'+':''}${pnlOggi.toFixed(2)} €</div>
      <div style="font-size:9px;color:var(--dim)">${botOnline?'ONLINE':'OFFLINE'} · ${bs.trades_today||0} trade oggi</div>
    </div>
  </div>
</div>`;

  // ── EMA ALIGNMENT (per S06_EMA_CROSS) — usa snap (già passato a seRender)
  const _e20=parseFloat(snap.e20), _e50=parseFloat(snap.e50), _e100=parseFloat(snap.e100), _e200=parseFloat(snap.e200), _pr=parseFloat(snap.price);
  const emaBullStack = _e20>_e50 && _e50>_e100 && _e100>_e200;
  const emaBearStack = _e20<_e50 && _e50<_e100 && _e100<_e200;
  const emaAlignCol  = emaBullStack?'var(--green)':emaBearStack?'var(--red)':'var(--dim)';
  // Prezzo vs ogni EMA
  const prVs = (e) => _pr>e?'▲':'▼';

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
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px;margin-bottom:3px">
    ${[['MACD',snap.macd],['EMA50',snap.e50],['EMA200',snap.e200],['VWAP',snap.vwap]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
      <span style="font-size:8px;color:var(--dim);letter-spacing:.05em">EMA STACK 20/50/100/200</span>
      <span style="font-size:9px;font-weight:800;color:${emaAlignCol}">${emaBullStack?'▲ RIALZISTA':emaBearStack?'▼ RIBASSISTA':'↔ MISTO'}</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px">
      ${[['EMA 20','#ff4757',snap.e20,_e20],['EMA 50','#ff7f50',snap.e50,_e50],['EMA 100','#00bcd4',snap.e100,_e100],['EMA 200','#2196f3',snap.e200,_e200]].map(([k,col,v,raw])=>`
      <div style="border-radius:4px;padding:4px 2px;text-align:center;border:1px solid ${col}40;background:${col}08">
        <div style="font-size:7px;color:${col};font-weight:700">${k}</div>
        <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
        <div style="font-size:8px;color:${_pr>raw?'var(--green)':'var(--red)'}">${raw?prVs(raw):''}</div>
      </div>`).join('')}
    </div>
  </div>
</div>`;

  // ── ORDER BLOCKS PANEL
  const _ob = seInds?.ob || null;
  const _price = parseFloat(snap.price);
  let obPanelHtml = '';
  if (_ob && (_ob.latestBull || _ob.latestBear)) {
    const bull = _ob.latestBull;
    const bear = _ob.latestBear;
    const inBull = bull && _price >= bull.low && _price <= bull.high;
    const inBear = bear && _price >= bear.low && _price <= bear.high;
    obPanelHtml = `
<div style="margin-bottom:8px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:4px">ORDER BLOCKS ATTIVI</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px">
    ${bull ? `<div style="background:${inBull?'#00e67618':'#00e67608'};border:1px solid ${inBull?'#00e676':'#00e67630'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--green);font-weight:700;margin-bottom:3px">▲ BULLISH OB${inBull?' 🎯 IN ZONA':''}</div>
      <div style="font-size:9px;color:var(--fg)">H: <b>$${bull.high.toFixed(1)}</b></div>
      <div style="font-size:9px;color:var(--dim)">Avg: $${bull.avg.toFixed(1)}</div>
      <div style="font-size:9px;color:var(--fg)">L: <b>$${bull.low.toFixed(1)}</b></div>
      <div style="font-size:8px;color:var(--dim);margin-top:2px">Dist: ${bull.low > _price ? '+' : ''}${((_price - bull.avg)/_price*100).toFixed(2)}%</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bull OB attivo</div>`}
    ${bear ? `<div style="background:${inBear?'#ff475718':'#ff475708'};border:1px solid ${inBear?'#ff4757':'#ff475730'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--red);font-weight:700;margin-bottom:3px">▼ BEARISH OB${inBear?' 🎯 IN ZONA':''}</div>
      <div style="font-size:9px;color:var(--fg)">H: <b>$${bear.high.toFixed(1)}</b></div>
      <div style="font-size:9px;color:var(--dim)">Avg: $${bear.avg.toFixed(1)}</div>
      <div style="font-size:9px;color:var(--fg)">L: <b>$${bear.low.toFixed(1)}</b></div>
      <div style="font-size:8px;color:var(--dim);margin-top:2px">Dist: ${bear.high < _price ? '-' : ''}${((_price - bear.avg)/_price*100).toFixed(2)}%</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bear OB attivo</div>`}
  </div>
</div>`;
  }

  // ── ICT M15 FVG PANEL
  const _m15ui = seInds?.m15 || null;
  let m15PanelHtml = '';
  if (_m15ui?.fvg) {
    const fvg    = _m15ui.fvg;
    const mi     = _m15ui.n - 1;
    const m15p   = _m15ui.C[mi];
    const bFVG   = fvg.latestBullFVG;
    const brFVG  = fvg.latestBearFVG;
    const m15e20 = _m15ui.e20?.[mi], m15e50 = _m15ui.e50?.[mi];
    const emaDir = m15e20 && m15e50 ? (m15e20>m15e50?'↑ BULL':'↓ BEAR') : '—';
    const emaDirCol = m15e20 && m15e50 ? (m15e20>m15e50?'var(--green)':'var(--red)') : 'var(--dim)';
    const inBullFVG = bFVG && m15p >= bFVG.open && m15p <= bFVG.close;
    const inBearFVG = brFVG && m15p >= brFVG.close && m15p <= brFVG.open;
    m15PanelHtml = `
<div style="margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <span style="font-size:9px;color:var(--dim);letter-spacing:.08em">ICT M15 — FVG ATTIVI</span>
    <span style="font-size:9px;font-weight:700;color:${emaDirCol}">EMA20/50 M15 ${emaDir}${m15e20?' · $'+m15e20.toFixed(0):''}</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px">
    ${bFVG ? `<div style="background:${inBullFVG?'#00e67618':'#00e67608'};border:1px solid ${inBullFVG?'#00e676':'#00e67630'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--green);font-weight:700;margin-bottom:3px">▲ Bull FVG${bFVG.displaced?' ⚡':''}${inBullFVG?' 🎯':''}</div>
      <div style="font-size:9px">$${bFVG.open.toFixed(1)} → $${bFVG.close.toFixed(1)}</div>
      <div style="font-size:8px;color:var(--dim)">Mid: $${bFVG.mid.toFixed(1)}</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bull FVG</div>`}
    ${brFVG ? `<div style="background:${inBearFVG?'#ff475718':'#ff475708'};border:1px solid ${inBearFVG?'#ff4757':'#ff475730'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--red);font-weight:700;margin-bottom:3px">▼ Bear FVG${brFVG.displaced?' ⚡':''}${inBearFVG?' 🎯':''}</div>
      <div style="font-size:9px">$${brFVG.open.toFixed(1)} → $${brFVG.close.toFixed(1)}</div>
      <div style="font-size:8px;color:var(--dim)">Mid: $${brFVG.mid.toFixed(1)}</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bear FVG</div>`}
  </div>
</div>`;
  }

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
            <div style="display:flex;align-items:center;gap:6px">
              <span style="color:${dc};font-weight:800;font-size:13px">${s.dir==='buy'?'▲ BUY':'▼ SELL'}</span>
              ${s.counterTrend?`<span style="font-size:8px;background:#b36cff18;border:1px solid #b36cff50;border-radius:3px;padding:1px 5px;color:#b36cff">⚡ CONTRO-TREND</span>`:''}
            </div>
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

  // ── AI GOLD BOT — pannello principale
  const activeList = SE.regimePriority[seRegime] || [];
  const activeSname = activeList[0] || 'S00_MFKK';
  const activeSt    = SE.strategies[activeSname] || {};
  const activeTF    = (() => {
    const pb = { TREND_UP:'H1', TREND_DOWN:'M15', WEAK_UP:'H1', WEAK_DOWN:'M30', VOLATILE:'M30', RANGE:'H1' };
    return pb[seRegime] || 'H1';
  })();
  // Stats aggregate sistema (somma backtest regime-aware 24m)
  // Aggiornato da backtest_combined.py — simulazione esatta flusso bot reale
  const BOT_STATS = { pnl_1m:57.79, pnl_6m:459.03, pnl_12m:521.93, pnl_24m:607.57, maxdd:96.34, maxdd_pct:'15.9%', trades_12m:45, pf:2.64, wr:'58.1%', n_strat:6 };
  const balStr  = acc.balance  ? `€${acc.balance.toFixed(0)}`  : '—';
  const eqStr   = acc.equity   ? `€${acc.equity.toFixed(0)}`   : '—';
  const pnlOggiStr = (bs.pnl_today||0)>=0 ? `+€${(bs.pnl_today||0).toFixed(2)}` : `€${(bs.pnl_today||0).toFixed(2)}`;
  const pnlOggiCol = (bs.pnl_today||0)>=0 ? 'var(--green)' : 'var(--red)';

  const catalogHtml = `
<div style="margin-top:18px; padding-top:15px; border-top:1px dashed var(--border)">

  <!-- ══ AI GOLD BOT ══ -->
  <div style="position:relative;background:linear-gradient(135deg,#0d0f12 60%,#1a1400 100%);border:1.5px solid #c8a96e60;border-radius:12px;padding:14px 14px 11px;margin-bottom:18px;overflow:hidden">
    <!-- sfondo decorativo -->
    <div style="position:absolute;top:-18px;right:-18px;width:90px;height:90px;background:radial-gradient(circle,#c8a96e18 0%,transparent 70%);pointer-events:none"></div>

    <!-- header -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:20px">🤖</span>
        <div>
          <div style="font-size:14px;font-weight:900;color:#c8a96e;letter-spacing:.06em">AI GOLD BOT</div>
          <div style="font-size:8px;color:var(--dim);letter-spacing:.04em">XAU/USD · Sistema Multi-Strategia</div>
        </div>
      </div>
      <div style="text-align:right">
        <div style="font-size:9px;font-weight:700;color:${botOnline?'var(--green)':'#ff4757'}">${botOnline?'● ONLINE':'● OFFLINE'}</div>
        <div style="font-size:8px;color:var(--dim);margin-top:1px">Sync ${syncLabel}</div>
      </div>
    </div>

    <!-- regime → strategia attiva -->
    <div style="background:#ffffff08;border:1px solid ${rm.col}35;border-radius:8px;padding:8px 10px;margin-bottom:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <div style="font-size:9px;color:var(--dim);letter-spacing:.06em">REGIME</div>
      <div style="font-size:11px;font-weight:800;color:${rm.col}">${rm.icon} ${rm.label}</div>
      <div style="color:var(--dim);font-size:10px">→</div>
      <div style="font-size:9px;color:var(--dim);letter-spacing:.06em">STRATEGIA</div>
      <div style="font-size:11px;font-weight:800;color:#c8a96e">${activeSt.label||activeSname}</div>
      <div style="margin-left:auto;background:${rm.col}20;border:1px solid ${rm.col}40;border-radius:4px;padding:2px 7px;font-size:8px;font-weight:700;color:${rm.col}">${activeTF}</div>
    </div>

    <!-- stats aggregate -->
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-bottom:10px;font-size:8px;text-align:center">
      ${[['1 MESE',BOT_STATS.pnl_1m,'var(--green)'],['6 MESI',BOT_STATS.pnl_6m,'var(--green)'],['12 MESI',BOT_STATS.pnl_12m,'var(--green)'],['24 MESI',BOT_STATS.pnl_24m,'var(--green)'],['MAX DD',-BOT_STATS.maxdd,'var(--red)']].map(([lbl,val,col])=>`
        <div style="background:#0d0f12;border:1px solid #c8a96e25;border-radius:5px;padding:5px 2px">
          <div style="color:var(--dim);margin-bottom:2px;font-size:7px">${lbl}</div>
          <div style="font-weight:800;color:${col};font-size:10px">${val>=0?'+':''}\$${Math.abs(val)}</div>
        </div>`).join('')}
    </div>

    <!-- footer account + metriche -->
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
      <div style="display:flex;gap:10px;font-size:9px">
        <span style="color:var(--dim)">Saldo <b style="color:var(--fg)">${balStr}</b></span>
        <span style="color:var(--dim)">Equity <b style="color:var(--fg)">${eqStr}</b></span>
        <span style="color:var(--dim)">Oggi <b style="color:${pnlOggiCol}">${pnlOggiStr}</b></span>
      </div>
      <div style="display:flex;gap:8px;font-size:9px">
        <span style="color:#c8a96e">PF <b>${BOT_STATS.pf}</b></span>
        <span style="color:var(--blue)">WR <b>${BOT_STATS.wr}</b></span>
        <span style="color:var(--dim)">${BOT_STATS.n_strat} strategie · ${BOT_STATS.trades_12m} trade/anno</span>
      </div>
    </div>
  </div>

  <!-- ══ LIBRERIA STRATEGIE ══ -->
  <div style="font-size:10px;color:var(--dim);font-weight:700;letter-spacing:.07em;margin-bottom:8px;display:flex;align-items:center;gap:6px">
    <span style="flex:1;height:1px;background:var(--border)"></span>
    <span>STRATEGIE DEL SISTEMA</span>
    <span style="flex:1;height:1px;background:var(--border)"></span>
  </div>
  <div style="display:grid; grid-template-columns:1fr; gap:6px">
    ${Object.entries(SE.strategies).map(([id, s]) => {
      const isPrimary   = activeList[0] === id;
      const isSecondary = !isPrimary && activeList.includes(id);
      const isActive    = isPrimary || isSecondary;
      const st = s.stats || {};
      const pnl1col   = (st.pnl_1m||0)>0  ?'var(--green)':'var(--red)';
      const pnl6col   = (st.pnl_6m||0)>0  ?'var(--green)':'var(--red)';
      const pnl12col  = (st.pnl_12m||0)>0 ?'var(--green)':'var(--red)';
      const pnl24col  = (st.pnl_24m||0)>0 ?'var(--green)':'var(--red)';
      const inds = id==='S00_MFKK'
        ? 'ADX 80% + MACD 10% + CCI(50) 10% · SELL≥75 · BUY≥90 · SELL 3.6x più redditizio · zona 80-89 WR 58.8%'
        : id==='S00_MFKK_HWR'
        ? 'ADX≥35 · DI spread≥20 · MACD diff≥0.5 · CCI non OS · SELL ONLY · 83 trade/anno · MaxDD -$61'
        : id==='S05_MFKK_INTRADAY'
        ? 'OBV MACD T-Channel + RSI>65 + Momentum + ADX≥30 · Setup chirurgico estremo WR 75%'
        : id==='S09_MFKK_SCALPING'
        ? 'EMA stack (20>50>100>200) + FVG retest · H1 su WEAK_UP · M30 su WEAK_DOWN/VOLATILE'
        : id==='S05_V3_Sell_Exhaust'
        ? 'OBV T-Channel bear + RSI>65 + ADX≥30 + MOM<0 · Sell exhaustion su TREND_UP H1'
        : id==='S01_EXHAUSTION'
        ? 'ADX/DI spread≥15 + MACD vs signal crossover · TREND_DOWN M15 (bot) / H1 (UI)'
        : id==='S13_STRUC_BREAK'
        ? 'Breakout max/min 40 barre + retest immediato · RANGE H1 · Setup strutturale'
        : 'Strategia aggregata di portafoglio · Bilanciamento dinamico · Rischio controllato';
      return `
      <div style="background:var(--bg2); border:1px solid ${isPrimary?rm.col+'70':isSecondary?rm.col+'30':'var(--border)'}; border-radius:8px; padding:9px 10px; position:relative; overflow:hidden">
        ${isPrimary  ? `<div style="position:absolute;top:0;right:0;background:${rm.col};color:#000;font-size:7px;font-weight:900;padding:2px 6px;border-bottom-left-radius:6px">✓ ATTIVA</div>` : ''}
        ${isSecondary? `<div style="position:absolute;top:0;right:0;background:${rm.col}30;border:1px solid ${rm.col}50;color:${rm.col};font-size:7px;font-weight:700;padding:2px 6px;border-bottom-left-radius:6px">▸ BACKUP</div>` : ''}
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
          <span style="font-size:11px;font-weight:700;color:${isPrimary?rm.col:isSecondary?rm.col+'bb':'var(--fg)'}">${s.label}</span>
          <div style="display:flex;gap:7px;font-size:10px">
            <span style="color:var(--green)">PF <b>${s.pf}</b></span>
            <span style="color:var(--blue)">WR <b>${s.wr}</b></span>
          </div>
        </div>
        <div style="font-size:8px;color:var(--dim);margin-bottom:6px;line-height:1.4">${inds}</div>
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px;font-size:8px;text-align:center;margin-bottom:3px">
          ${[['1 MESE','pnl_1m','td_1m',pnl1col],['6 MESI','pnl_6m','td_6m',pnl6col],['12 MESI','pnl_12m','td_12m',pnl12col],['24 MESI','pnl_24m','td_24m',pnl24col],['MAX DD','maxdd','maxdd_pct','var(--red)']].map(([label,pkey,tdkey,col])=>{
            const v = st[pkey];
            const displayV = pkey==='maxdd'
              ? (v!=null ? '-$'+v : '-$—')
              : (v!=null ? (v>=0?'+':'')+`$${v}` : '+$—');
            const tdVal = tdkey && st[tdkey]!=null 
              ? (tdkey==='maxdd_pct' ? `<div style="font-size:7px;color:var(--dim);margin-top:1px">${st[tdkey]} Max DD</div>` : `<div style="font-size:7px;color:var(--dim);margin-top:1px">${st[tdkey]} td/gg</div>`)
              : '';
            return `<div style="background:#0d0f12;border:1px solid var(--border2);border-radius:4px;padding:3px 2px">
              <div style="color:var(--dim);margin-bottom:1px">${label}</div>
              <div style="font-weight:700;color:${col}">${displayV}</div>
              ${tdVal}
            </div>`;
          }).join('')}
        </div>
        <div style="margin-top:4px;font-size:8px;color:var(--dim);display:flex;gap:8px">
          <span>~${st.trades_12m||'?'} trade/anno</span>
          <span>Target: TP ${s.tp} · SL ${s.sl}</span>
          <span style="margin-left:auto;color:var(--dim)">Best: ${st.best_regime||'?'}</span>
        </div>
      </div>`;
    }).join('')}
  </div>
</div>`;

  el.innerHTML=statusHtml+regimeHtml+indSnap+obPanelHtml+m15PanelHtml+pendingHtml+posHtml+histHtml+catalogHtml;
}

async function seSendTradeToMt5(s) {
  const btn = event?.target;

  // Usa i dati già fetchati dal ciclo di render (evita double-check che causa falsi offline)
  // Se seLastMt5Data è troppo vecchio, facciamo un refetch
  let mt5Live = window._seLastMt5Data || null;
  if (!mt5Live) {
    mt5Live = await seFetchMt5Data();
  }
  
  const syncAge = mt5Live?.synced_at ? Math.round((Date.now()-new Date(mt5Live.synced_at).getTime())/1000) : null;
  // Soglia più generosa: 3 minuti (il bot synca ogni 20s ma potrebbe essere in un ciclo lungo)
  const botOk = syncAge !== null && syncAge < 180;

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
          tp: typeof s.tp === 'number' ? s.tp : parseFloat(String(s.tp).replace(/[^0-9.]/g,'')),
          sl: typeof s.sl === 'number' ? s.sl : parseFloat(String(s.sl).replace(/[^0-9.]/g,'')),
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
