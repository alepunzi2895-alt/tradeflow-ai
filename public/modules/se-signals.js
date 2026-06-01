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

  // S05_MFKK_INTRADAY: V2 Triple MACD H1 — 3.3 trade/gg · WR 36.9% · PF 1.23 · P&L $4776/24m
  // OBV T-Channel direzione + RSI sopra/sotto 50 + MACD line + Momentum + ADX≥20
  // Identico a signal_mfkk_intraday() in mt5-bot.py
  S05_MFKK_INTRADAY: (I, i) => {
    if (!I.obv_oc || i < 2) return null;
    const oc  = I.obv_oc[i];
    const rsi = I.rsi?.[i];
    const adx = I.adx?.[i];
    const mom = I.mom?.[i];
    const mc  = I.macd?.[i];
    if (rsi == null || adx == null || mom == null || mc == null) return null;
    if (adx < 20) return null;

    if (oc === 1 && rsi > 50 && mom > 0 && mc > 0) {
      return {dir:'buy',  why:`MFKK Intraday ↑ V2 · OBV Bull · RSI ${rsi.toFixed(0)}>50 · MACD+ · Mom+`, quality:'high'};
    }
    if (oc === -1 && rsi < 50 && mom < 0 && mc < 0) {
      return {dir:'sell', why:`MFKK Intraday ↓ V2 · OBV Bear · RSI ${rsi.toFixed(0)}<50 · MACD- · Mom-`, quality:'high'};
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

  // S05_V3_Sell_Exhaust — OBV T-Channel bear + RSI>60 + ADX≥25 + MOM< (TREND_UP exhaustion)
  S05_V3_Sell_Exhaust: (I, i) => {
    if (!I.obv_oc || i < 1) return null;
    const oc  = I.obv_oc[i];
    const rsi = I.rsi?.[i];
    const adx = I.adx?.[i];
    const mom = I.mom?.[i];
    if (rsi == null || adx == null || mom == null) return null;
    if (oc === -1 && rsi > 60 && adx >= 25 && mom < 0) {
      return { dir: 'sell', why: `Sell Exhaust ↓ OBV Bear · RSI ${rsi.toFixed(0)}>60 · ADX ${adx.toFixed(0)}≥25 · Mom<0`, quality: 'high' };
    }
    return null;
  },

  // S01_EXHAUSTION — ADX/DI divergenza + MACD vs signal (approssimazione H1 della strategia M15)
  S01_EXHAUSTION: (I, i) => {
    const adx = I.adx?.[i], dp = I.dip?.[i], dm = I.dim?.[i];
    const ml  = I.macd?.[i], ms = I.macd_sig?.[i] ?? I.macd_signal?.[i];
    if (adx == null || dp == null || dm == null || ml == null || ms == null) return null;
    const diff = ml - ms; const spread = Math.abs(dp - dm);
    if (adx >= 25 && dm > dp && spread >= 15 && diff >= 0.7) {
      return { dir: 'sell', why: `Exhaustion ↓ ADX ${adx.toFixed(0)}≥25 · DM>DP spread ${spread.toFixed(0)} · MACD diff +${diff.toFixed(1)}`, quality: 'medium' };
    }
    if (adx >= 25 && dp > dm && spread >= 15 && diff <= -0.7) {
      return { dir: 'buy', why: `Exhaustion ↑ ADX ${adx.toFixed(0)}≥25 · DP>DM spread ${spread.toFixed(0)} · MACD diff ${diff.toFixed(1)}`, quality: 'medium' };
    }
    return null;
  },

  // S13_STRUC_BREAK — breakout 30-bar high/low con retest (RANGE)
  S13_STRUC_BREAK: (I, i) => {
    if (i < 60) return null;
    const H = I.H, L = I.L, C = I.C;
    if (!H || !L || !C) return null;
    const hh = Math.max(...H.slice(i-30, i));
    const ll  = Math.min(...L.slice(i-30, i));
    const c   = C[i], lo = L[i], hi = H[i];
    if (c > hh && lo <= hh * 1.002 && lo >= hh * 0.998) {
      return { dir: 'buy', why: `Struc Break ↑ Breakout + retest 30 barre $${hh.toFixed(2)}`, quality: 'high' };
    }
    if (c < ll && hi >= ll * 0.998 && hi <= ll * 1.002) {
      return { dir: 'sell', why: `Struc Break ↓ Breakout + retest 30 barre $${ll.toFixed(2)}`, quality: 'high' };
    }
    return null;
  },

  // S10_OB_FVG_SCALP — ICT Order Block + FVG Confluence Scalping · M15 always-on
  // LONG : Bullish OB body + Bull FVG attivo + candela bullish
  // SHORT: Bearish OB body + Bear FVG attivo + candela bearish
  // NOTA: Filtro EMA20/50 rilassato (facoltativo) per massimizzare frequenza
  S10_OB_FVG_SCALP: (I, i) => {
    const {O, H, L, C, e20, e50, fvg_bull, fvg_bear} = I;
    if (!C || !O) return null;

    const LB = 30; // Aumentato lookback OB a 30
    let ob_b = false, ob_s = false;

    // ── Bullish OB detection ────────────────────────────────────────────────
    for (let j = i - 2; j >= Math.max(i - LB - 1, 2); j--) {
      if (C[j] >= O[j]) continue;
      const ob_lo = Math.min(O[j], C[j]);
      const ob_hi = Math.max(O[j], C[j]);
      if (!(C[j+1] > O[j+1])) continue; // almeno una candela impulsiva
      let mitig = false;
      for (let k = j+1; k < i; k++) { if (L[k] < ob_lo * 0.998) { mitig = true; break; } }
      if (mitig) continue;
      if (C[i] >= ob_lo * 0.998 && C[i] <= ob_hi * 1.003) { ob_b = true; break; }
    }

    // ── Bearish OB detection ────────────────────────────────────────────────
    for (let j = i - 2; j >= Math.max(i - LB - 1, 2); j--) {
      if (C[j] <= O[j]) continue;
      const ob_lo = Math.min(O[j], C[j]);
      const ob_hi = Math.max(O[j], C[j]);
      if (!(C[j+1] < O[j+1])) continue;
      let mitig = false;
      for (let k = j+1; k < i; k++) { if (H[k] > ob_hi * 1.002) { mitig = true; break; } }
      if (mitig) continue;
      if (C[i] >= ob_lo * 0.997 && C[i] <= ob_hi * 1.002) { ob_s = true; break; }
    }

    const fvg_b = fvg_bull?.[i];
    const fvg_s = fvg_bear?.[i];
    const bull_c = C[i] > O[i];
    const bear_c = C[i] < O[i];

    if (ob_b && fvg_b && bull_c) {
      return { dir: 'buy', why: `OB+FVG Bull ▲ Prezzo in Bullish OB + Bull FVG M15`, quality: 'high', score: 88 };
    }
    if (ob_s && fvg_s && bear_c) {
      return { dir: 'sell', why: `OB+FVG Bear ▼ Prezzo in Bearish OB + Bear FVG M15`, quality: 'high', score: 88 };
    }
    return null;
  },

  // S16_GOLDEN_SQUEEZE: versione browser-side — multi-confluenza istituzionale
  // EMA200 bias + ADX≥20 + DI dominance + MACD histogram + OBV T-Channel
  // Corrisponde alla logica del bot (signal_golden_squeeze) adattata agli indicatori H1 disponibili
  S16_GOLDEN_SQUEEZE: (I, i) => {
    if (i < 2) return null;
    const adx = I.adx?.[i];
    const dip = I.dip?.[i];
    const dim = I.dim?.[i];
    const mc  = I.macd?.[i];
    const ms  = I.macd_sig?.[i];
    const oc  = I.obv_oc?.[i];   // OBV T-Channel: 1=bull, -1=bear
    const e200= I.e200?.[i];
    const c   = I.C?.[i];
    if (adx==null||dip==null||dim==null||mc==null||ms==null||e200==null||c==null) return null;
    if (adx < 20) return null;
    const mh = mc - ms;  // MACD histogram
    const bullTrend = c > e200 && dip > dim;
    const bearTrend = c < e200 && dim > dip;
    if (bullTrend && mc > 0 && mh > 0 && oc !== -1) {
      return { dir:'buy',  why:`Golden Squeeze ↑ · ADX ${adx.toFixed(0)} · DI+${dip.toFixed(0)}>DI-${dim.toFixed(0)} · MACD+ · >EMA200`, quality:'high', score:82 };
    }
    if (bearTrend && mc < 0 && mh < 0 && oc !== 1) {
      return { dir:'sell', why:`Golden Squeeze ↓ · ADX ${adx.toFixed(0)} · DI-${dim.toFixed(0)}>DI+${dip.toFixed(0)} · MACD- · <EMA200`, quality:'high', score:82 };
    }
    return null;
  },
  // S17_CONVERGENCE_SCALP: Crossover EMA 13/34 + StochRSI + BB%B + EMA50
  S17_CONVERGENCE_SCALP: (I, i) => {
    if (i < 2) return null;
    const e13 = I.e13?.[i], e34 = I.e34?.[i];
    const sk  = I.srsi_k?.[i], sd = I.srsi_d?.[i];
    const bu  = I.bb_up?.[i], bl = I.bb_dn?.[i];
    const c   = I.C?.[i], e50 = I.e50?.[i];
    if (e13==null || e34==null || sk==null || sd==null || bu==null || bl==null || c==null || e50==null) return null;
    
    const bbRange = bu - bl;
    const bbPct = bbRange > 0 ? (c - bl) / bbRange : 0.5;

    const e13p = I.e13?.[i-1], e34p = I.e34?.[i-1];
    const skp  = I.srsi_k?.[i-1], sdp = I.srsi_d?.[i-1];
    if (e13p==null || e34p==null || skp==null || sdp==null) return null;

    const bullPrev = e13p > e34p && skp > sdp;
    const bearPrev = e13p < e34p && skp < sdp;

    const bull = e13 > e34 && sk > sd && bbPct > 0.5 && c > e50 && !bullPrev;
    const bear = e13 < e34 && sk < sd && bbPct < 0.5 && c < e50 && !bearPrev;

    if (bull) return { dir: 'buy', why: `Convergence Scalp ↑ crossover EMA13/34 · StochRSI K>D · BB%B > 0.5 · >EMA50`, quality: 'high', score: 85 };
    if (bear) return { dir: 'sell', why: `Convergence Scalp ↓ crossover EMA13/34 · StochRSI K<D · BB%B < 0.5 · <EMA50`, quality: 'high', score: 85 };
    return null;
  },
};


function seDetectRegime(I, i) {
  const adx = I.adx[i] || 25;
  const dip = I.dip[i] || 20;
  const dim = I.dim[i] || 20;
  const atr = I.atr[i];
  const a30 = I.atr30[i];

  // Soglie identiche a mt5-bot.py detect_regime() e backtest_combined.py regime()
  if(adx >= 30) return (dip > dim) ? 'TREND_UP' : 'TREND_DOWN';
  if(adx >= 22) return (dip > dim) ? 'WEAK_UP' : 'WEAK_DOWN';
  if(atr && a30 && atr > 1.4 * a30) return 'VOLATILE';
  return 'RANGE';
}

