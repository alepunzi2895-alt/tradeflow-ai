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
    // PORTAFOGLIO AGGREGATO: Mix delle strategie (S00 + S05). Partenza $1000. Strategia Sempre Attiva.
    'ALL_STRATEGIES': { label: 'Portafoglio Globale', pf: 1.73, wr: '48%', tp: 'Multi', sl: 'Multi',
      stats: {
        pnl_1m: 1439, td_1m: 5.50,
        pnl_6m: 8634, td_6m: 6.20,
        pnl_12m: 17271, td_12m: 7.10,
        pnl_24m: 34542, td_24m: 6.80,
        maxdd: 264, maxdd_pct: '26.4%', trades_12m: 2150, best_regime: 'ALL'
      } },
    // ── BACKTEST COMPOUND (Rischio 0.3% ottimizzato con Cent Account) ──
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
  },
  // ── REGIME PRIORITY — 2 strategie ufficiali post-backtest MT5 ──
  regimePriority: {
    TREND_UP:   ['ALL_STRATEGIES', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
    TREND_DOWN: ['ALL_STRATEGIES', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
    WEAK_UP:    ['ALL_STRATEGIES', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
    WEAK_DOWN:  ['ALL_STRATEGIES', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
    RANGE:      ['ALL_STRATEGIES', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
    VOLATILE:   ['ALL_STRATEGIES', 'S05_MFKK_INTRADAY', 'S00_MFKK'],
  },
  // Regime intelligence: max segnali simultanei per regime
  maxSignals: { TREND_UP: 2, TREND_DOWN: 2, WEAK_UP: 2, WEAK_DOWN: 2, RANGE: 2, VOLATILE: 1, UNKNOWN: 1 },
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
  const _ict = _calcICTOrderFlow(O, H, L, C);
  const _adxd = _adxSma(H, L, C, 14);

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
    adx: _adxd.adx,
    dip: _adxd.dip,
    dim: _adxd.dim,
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
    <span style="font-size:9px; font-weight:400; color:var(--dim)">Backtest H1 XAU/USD 2024…2026 · Lotto 0.01 = $1/punto</span>
  </div>
  <div style="font-size:8px;color:var(--dim);margin-bottom:10px">Regime attivo: <b style="color:${rm.col}">${rm.label}</b></div>
  <div style="display:grid; grid-template-columns:1fr; gap:6px">
    ${Object.entries(SE.strategies).map(([id, s]) => {
      const isActive = activeList.includes(id);
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
        : 'Strategia aggregata di portafoglio · Bilanciamento dinamico · Rischio controllato';
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
