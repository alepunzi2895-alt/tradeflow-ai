/**
 * MFKK Strategy Backtester
 * =========================
 * Simulates the MFKK scoring system on historical H1 XAU/USD candles.
 * 
 * Indicators (matching TradingView settings):
 *   CCI_S: CCI(50) → Stochastic(50, K=8, D=8), OB=75, OS=25
 *   MACD:  EMA(12,26,9), default
 *   ADX:   Period 10, "ADX and DI for v4" (SMA-based DX)
 * 
 * Output: JSON report with trade list, stats, and scoring analysis.
 * 
 * Usage: node scripts/backtest-mfkk.mjs [--period 365] [--tp 15] [--sl 10]
 */

const TP_DEFAULT = 15;   // default take profit in USD
const SL_DEFAULT = 10;   // default stop loss in USD
const PERIOD_DEFAULT = 365; // days of history

// Parse CLI args
const args = process.argv.slice(2);
function getArg(name, def) {
  const i = args.indexOf('--' + name);
  return i >= 0 && args[i + 1] ? Number(args[i + 1]) : def;
}
const TP = getArg('tp', TP_DEFAULT);
const SL = getArg('sl', SL_DEFAULT);
const PERIOD = getArg('period', PERIOD_DEFAULT);

console.log(`\n╔══════════════════════════════════════════╗`);
console.log(`║  MFKK Strategy Backtester v1.0           ║`);
console.log(`║  XAU/USD H1 · TP=$${TP} SL=$${SL} · ${PERIOD}d   ║`);
console.log(`╚══════════════════════════════════════════╝\n`);

// ─── DATA FETCH ──────────────────────────────────────────────────────────────
async function fetchCandles(days) {
  // Yahoo Finance: max 730 days for 1h candles, fetched in 60d chunks
  const allCandles = [];
  const now = Math.floor(Date.now() / 1000);
  const start = now - days * 86400;
  
  // Fetch in 60-day chunks (Yahoo limit for 1h interval)
  for (let from = start; from < now; from += 59 * 86400) {
    const to = Math.min(from + 59 * 86400, now);
    const url = `https://query2.finance.yahoo.com/v8/finance/chart/GC%3DF?interval=1h&period1=${from}&period2=${to}`;
    try {
      const r = await fetch(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          'Accept': 'application/json'
        }
      });
      if (!r.ok) { console.log(`  Chunk ${new Date(from * 1000).toISOString().slice(0, 10)}: HTTP ${r.status}`); continue; }
      const d = await r.json();
      const rs = d?.chart?.result?.[0];
      if (!rs?.timestamp) continue;
      const q = rs.indicators?.quote?.[0] || {};
      for (let i = 0; i < rs.timestamp.length; i++) {
        if (q.close?.[i] != null && q.high?.[i] != null && q.low?.[i] != null && q.open?.[i] != null)
          allCandles.push({ t: rs.timestamp[i], o: q.open[i], h: q.high[i], l: q.low[i], c: q.close[i] });
      }
    } catch (e) { console.log(`  Chunk error: ${e.message}`); }
  }
  
  // Deduplicate by timestamp
  const seen = new Set();
  const unique = [];
  for (const c of allCandles) {
    if (!seen.has(c.t)) { seen.add(c.t); unique.push(c); }
  }
  unique.sort((a, b) => a.t - b.t);
  console.log(`📊 Fetched ${unique.length} unique H1 candles (${days} days requested)`);
  if (unique.length > 0) {
    console.log(`   From: ${new Date(unique[0].t * 1000).toISOString().slice(0, 16)}`);
    console.log(`   To:   ${new Date(unique.at(-1).t * 1000).toISOString().slice(0, 16)}\n`);
  }
  return unique;
}

// ─── INDICATOR CALCULATIONS ──────────────────────────────────────────────────
function ema(src, p) {
  const k = 2 / (p + 1);
  let v = src[0];
  const o = [v];
  for (let i = 1; i < src.length; i++) { v = src[i] * k + v * (1 - k); o.push(v); }
  return o;
}

function sma(src, p) {
  const o = new Array(src.length).fill(null);
  for (let i = p - 1; i < src.length; i++) {
    const sl = src.slice(i - p + 1, i + 1);
    if (sl.some(v => v == null)) { o[i] = null; continue; }
    o[i] = sl.reduce((a, b) => a + b, 0) / p;
  }
  return o;
}

function highest(arr, p, i) {
  let m = -Infinity;
  for (let j = Math.max(0, i - p + 1); j <= i; j++) if (arr[j] != null) m = Math.max(m, arr[j]);
  return m;
}
function lowest(arr, p, i) {
  let m = Infinity;
  for (let j = Math.max(0, i - p + 1); j <= i; j++) if (arr[j] != null) m = Math.min(m, arr[j]);
  return m;
}

function calcIndicators(candles) {
  const n = candles.length;
  const H = candles.map(x => x.h), L = candles.map(x => x.l), C = candles.map(x => x.c);

  // ── CCI_S ────────────────────────────────────────────────────────────────
  const CCI_P = 50, STOCH_P = 50, SK = 8, SD = 8;
  const cci = new Array(n).fill(null);
  for (let i = CCI_P - 1; i < n; i++) {
    const sl = C.slice(i - CCI_P + 1, i + 1);
    const mn = sl.reduce((a, b) => a + b, 0) / CCI_P;
    const md = sl.reduce((a, b) => a + Math.abs(b - mn), 0) / CCI_P;
    cci[i] = md === 0 ? 0 : (C[i] - mn) / (0.015 * md);
  }
  const stk = new Array(n).fill(null);
  for (let i = CCI_P + STOCH_P - 2; i < n; i++) {
    if (cci[i] == null) continue;
    const lv = lowest(cci, STOCH_P, i), hv = highest(cci, STOCH_P, i);
    stk[i] = (hv - lv) === 0 ? 50 : ((cci[i] - lv) / (hv - lv)) * 100;
  }
  const stk_k = new Array(n).fill(null);
  for (let i = SK - 1; i < n; i++) {
    const sl = stk.slice(i - SK + 1, i + 1);
    if (sl.some(v => v == null)) continue;
    stk_k[i] = sl.reduce((a, b) => a + b, 0) / SK;
  }
  const stk_d = new Array(n).fill(null);
  for (let i = SD - 1; i < n; i++) {
    const sl = stk_k.slice(i - SD + 1, i + 1);
    if (sl.some(v => v == null)) continue;
    stk_d[i] = sl.reduce((a, b) => a + b, 0) / SD;
  }

  // ── MACD(12,26,9) ────────────────────────────────────────────────────────
  const macdLine = ema(C, 12).map((v, i) => v - ema(C, 26)[i]);
  const ema26 = ema(C, 26);
  const ema12 = ema(C, 12);
  const macd = ema12.map((v, i) => v - ema26[i]);
  const signal = ema(macd, 9);
  const histogram = macd.map((v, i) => v - signal[i]);

  // ── ADX(10) — "ADX and DI for v4" ────────────────────────────────────────
  const AP = 10;
  const TR = new Array(n).fill(0), DMP = new Array(n).fill(0), DMM = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    TR[i] = Math.max(H[i] - L[i], Math.abs(H[i] - C[i - 1]), Math.abs(L[i] - C[i - 1]));
    const up = H[i] - H[i - 1], dn = L[i - 1] - L[i];
    DMP[i] = (up > dn && up > 0) ? up : 0;
    DMM[i] = (dn > up && dn > 0) ? dn : 0;
  }
  const sTR = new Array(n).fill(0), sDMP = new Array(n).fill(0), sDMM = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    sTR[i] = sTR[i - 1] - sTR[i - 1] / AP + TR[i];
    sDMP[i] = sDMP[i - 1] - sDMP[i - 1] / AP + DMP[i];
    sDMM[i] = sDMM[i - 1] - sDMM[i - 1] / AP + DMM[i];
  }
  const DIP = sTR.map((v, i) => v > 0 ? sDMP[i] / v * 100 : 0);
  const DIM = sTR.map((v, i) => v > 0 ? sDMM[i] / v * 100 : 0);
  const DX = DIP.map((v, i) => { const s = v + DIM[i]; return s > 0 ? Math.abs(v - DIM[i]) / s * 100 : 0; });
  const ADX = sma(DX, AP);

  return { stk_d, macd, signal, histogram, ADX, DIP, DIM, C };
}

// ─── SCORING ENGINE (matches calcMfkk in mfkk.js) ───────────────────────────
function scoreMfkk(cciVal, macdLine, macdSignal, macdHist, adxVal, diPlus, diMinus, dir) {
  const isBuy = dir === 'buy';

  // CCI Score — calibrato su 2 anni H1 backtest (trend-continuation, non mean-reversion)
  // BUY: alto CCI = uptrend in corso = favorevole. SELL: basso CCI = downtrend = favorevole.
  let cciScore = 50;
  if (cciVal != null) {
    if (isBuy) {
      if (cciVal >= 75)      cciScore = 60;  // OB_DEEP: uptrend forte (WR storico migl. per BUY)
      else if (cciVal >= 65) cciScore = 52;
      else if (cciVal >= 50) cciScore = 45;
      else if (cciVal >= 35) cciScore = 38;
      else if (cciVal >= 25) cciScore = 28;
      else                   cciScore = 18;  // OS_DEEP: downtrend dominante (WR 31%)
    } else {
      if (cciVal <= 25)      cciScore = 65;  // OS_DEEP: downtrend forte (WR 48% storico SELL)
      else if (cciVal <= 35) cciScore = 58;
      else if (cciVal <= 50) cciScore = 50;
      else if (cciVal <= 65) cciScore = 44;
      else if (cciVal < 75)  cciScore = 40;
      else                   cciScore = 40;  // OB_DEEP: esaurimento SELL se ADX forte (82%+ WR)
    }
  }

  // MACD Score — aggiunto pattern esaurimento (backtest: MACD opposto + ADX forte = WR 82-88%)
  let macdScore = 50;
  if (macdLine != null && macdSignal != null) {
    const diff = macdLine - macdSignal;
    const str = Math.min(Math.abs(diff) / 3, 1);
    const histBonus = macdHist != null ? ((isBuy && macdHist > 0) || (!isBuy && macdHist < 0) ? 10 : 0) : 0;
    if (isBuy) {
      if (diff > 0.5)       macdScore = Math.round(65 + str * 25) + histBonus;
      else if (diff > 0)    macdScore = 60 + histBonus;
      else if (diff > -1)   macdScore = 30;
      else if (diff > -3)   macdScore = 40;  // Esaurimento bearish: ADX DI+ ribalta
      else                  macdScore = 15;
    } else {
      if (diff < -0.5)      macdScore = Math.round(65 + str * 25) + histBonus;
      else if (diff < 0)    macdScore = 60 + histBonus;
      else if (diff < 1)    macdScore = 30;
      else if (diff < 3)    macdScore = 45;  // Esaurimento bullish: ADX DI- + MACD alto = 82%+ WR
      else                  macdScore = 48;  // MACD super-esteso rialzista = esaurimento massimo
    }
    macdScore = Math.max(0, Math.min(100, macdScore));
  }

  // ADX Score (weight 30%)
  let adxScore = 50;
  if (adxVal != null && diPlus != null && diMinus != null) {
    const diDiff = diPlus - diMinus;
    const diSpread = Math.abs(diDiff);
    const spreadBonus = Math.min(diSpread / 20, 1);
    let adxStr = adxVal >= 35 ? 1.0 : adxVal >= 27 ? 0.85 : adxVal >= 20 ? 0.65 : adxVal >= 14 ? 0.4 : adxVal >= 10 ? 0.2 : 0.05;
    if (isBuy) {
      if (diDiff > 0 && adxVal >= 25) adxScore = Math.round(60 + adxStr * 25 + spreadBonus * 15);
      else if (diDiff > 0 && adxVal >= 10) adxScore = 50;
      else if (diDiff > 0) adxScore = 30;
      else adxScore = 5;
    } else {
      if (diDiff < 0 && adxVal >= 25) adxScore = Math.round(60 + adxStr * 25 + spreadBonus * 15);
      else if (diDiff < 0 && adxVal >= 10) adxScore = 50;
      else if (diDiff < 0) adxScore = 30;
      else adxScore = 5;
    }
    adxScore = Math.max(0, Math.min(100, adxScore));
  }

  // Weighted total — ottimizzato su 2272 combinazioni, 730gg H1 XAU/USD
  // CCI 10%, MACD 10%, ADX 80% → PF 1.802, WR 51.9%, P&L $6648
  const tot = cciScore * 0.10 + macdScore * 0.10 + adxScore * 0.80;
  const score = Math.round(tot);

  return { score, cciScore, macdScore, adxScore };
}

// ─── BACKTEST ENGINE ─────────────────────────────────────────────────────────
function runBacktest(candles, indicators, config = {}) {
  const { tp = TP, sl = SL, minScore = 70, minScoreForte = 80 } = config;
  const buyThr  = config.buyThr  ?? minScore;
  const sellThr = config.sellThr ?? minScore;
  const { stk_d, macd, signal, histogram, ADX, DIP, DIM, C } = indicators;
  const n = C.length;
  
  // Warmup: need at least 120 candles for indicators
  const START = 120;
  
  const trades = [];
  let openTrade = null;
  
  for (let i = START; i < n; i++) {
    const cciVal = stk_d[i];
    const macdVal = macd[i];
    const sigVal = signal[i];
    const histVal = histogram[i];
    const adxVal = ADX[i];
    const diP = DIP[i];
    const diM = DIM[i];
    const price = C[i];
    const time = candles[i].t;
    
    if (cciVal == null || adxVal == null) continue;
    
    // Check if we have an open trade
    if (openTrade) {
      const high = candles[i].h;
      const low = candles[i].l;
      
      if (openTrade.dir === 'buy') {
        // Check SL first (worst case)
        if (low <= openTrade.entry - sl) {
          openTrade.exit = openTrade.entry - sl;
          openTrade.exitTime = time;
          openTrade.result = 'SL';
          openTrade.pnl = -sl;
          openTrade.bars = i - openTrade.barIndex;
          trades.push({ ...openTrade });
          openTrade = null;
        }
        // Check TP
        else if (high >= openTrade.entry + tp) {
          openTrade.exit = openTrade.entry + tp;
          openTrade.exitTime = time;
          openTrade.result = 'TP';
          openTrade.pnl = tp;
          openTrade.bars = i - openTrade.barIndex;
          trades.push({ ...openTrade });
          openTrade = null;
        }
      } else {
        // SELL trade
        if (high >= openTrade.entry + sl) {
          openTrade.exit = openTrade.entry + sl;
          openTrade.exitTime = time;
          openTrade.result = 'SL';
          openTrade.pnl = -sl;
          openTrade.bars = i - openTrade.barIndex;
          trades.push({ ...openTrade });
          openTrade = null;
        }
        else if (low <= openTrade.entry - tp) {
          openTrade.exit = openTrade.entry - tp;
          openTrade.exitTime = time;
          openTrade.result = 'TP';
          openTrade.pnl = tp;
          openTrade.bars = i - openTrade.barIndex;
          trades.push({ ...openTrade });
          openTrade = null;
        }
      }
      continue; // Don't open new trade while one is open
    }
    
    // Evaluate both directions
    const buyScore = scoreMfkk(cciVal, macdVal, sigVal, histVal, adxVal, diP, diM, 'buy');
    const sellScore = scoreMfkk(cciVal, macdVal, sigVal, histVal, adxVal, diP, diM, 'sell');
    
    // Choose best direction con soglie separate BUY/SELL
    let dir = null, bestScore = null;
    if (buyScore.score >= buyThr && buyScore.score > sellScore.score) {
      dir = 'buy'; bestScore = buyScore;
    } else if (sellScore.score >= sellThr && sellScore.score > buyScore.score) {
      dir = 'sell'; bestScore = sellScore;
    }
    
    if (dir && bestScore) {
      // Forte: alta convinzione ADX (score >= minScoreForte + ADX forte)
      // OPPURE pattern esaurimento (ADX forte con MACD opposto alla direzione)
      const macdDiffVal = macdVal - sigVal;
      const isExhaustion = (dir === 'sell' && macdDiffVal > 1.0 && bestScore.adxScore >= 75) ||
                           (dir === 'buy'  && macdDiffVal < -1.0 && bestScore.adxScore >= 75);
      const isFort = (bestScore.score >= minScoreForte && bestScore.adxScore >= 75) || isExhaustion;
      openTrade = {
        dir,
        entry: price,
        entryTime: time,
        barIndex: i,
        score: bestScore.score,
        cciScore: bestScore.cciScore,
        macdScore: bestScore.macdScore,
        adxScore: bestScore.adxScore,
        forte: isFort,
        cciVal: +cciVal.toFixed(2),
        macdDiff: +(macdVal - sigVal).toFixed(2),
        adxVal: +adxVal.toFixed(2)
      };
    }
  }
  
  // Close any remaining open trade at last price
  if (openTrade) {
    const lastPrice = C[n - 1];
    const pnl = openTrade.dir === 'buy' ? lastPrice - openTrade.entry : openTrade.entry - lastPrice;
    openTrade.exit = lastPrice;
    openTrade.exitTime = candles[n - 1].t;
    openTrade.result = 'OPEN';
    openTrade.pnl = +pnl.toFixed(2);
    openTrade.bars = n - 1 - openTrade.barIndex;
    trades.push({ ...openTrade });
  }

  return trades;
}

// ─── STATISTICS ──────────────────────────────────────────────────────────────
function analyzeResults(trades, label) {
  const closed = trades.filter(t => t.result !== 'OPEN');
  const wins = closed.filter(t => t.pnl > 0);
  const losses = closed.filter(t => t.pnl < 0);
  const forte = closed.filter(t => t.forte);
  const forteWins = forte.filter(t => t.pnl > 0);
  
  const totalPnL = closed.reduce((a, t) => a + t.pnl, 0);
  const avgPnL = closed.length > 0 ? totalPnL / closed.length : 0;
  const winRate = closed.length > 0 ? (wins.length / closed.length * 100) : 0;
  const forteWinRate = forte.length > 0 ? (forteWins.length / forte.length * 100) : 0;
  
  // Max drawdown
  let peak = 0, dd = 0, maxDD = 0, equity = 0;
  for (const t of closed) {
    equity += t.pnl;
    peak = Math.max(peak, equity);
    dd = peak - equity;
    maxDD = Math.max(maxDD, dd);
  }
  
  // Average bars in trade
  const avgBars = closed.length > 0 ? (closed.reduce((a, t) => a + (t.bars || 0), 0) / closed.length) : 0;
  
  // Profit factor
  const grossProfit = wins.reduce((a, t) => a + t.pnl, 0);
  const grossLoss = Math.abs(losses.reduce((a, t) => a + t.pnl, 0));
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;
  
  // Consecutive wins/losses
  let maxConsWins = 0, maxConsLosses = 0, consW = 0, consL = 0;
  for (const t of closed) {
    if (t.pnl > 0) { consW++; consL = 0; maxConsWins = Math.max(maxConsWins, consW); }
    else { consL++; consW = 0; maxConsLosses = Math.max(maxConsLosses, consL); }
  }
  
  // Buy vs Sell breakdown
  const buys = closed.filter(t => t.dir === 'buy');
  const sells = closed.filter(t => t.dir === 'sell');
  const buyWR = buys.length > 0 ? (buys.filter(t => t.pnl > 0).length / buys.length * 100) : 0;
  const sellWR = sells.length > 0 ? (sells.filter(t => t.pnl > 0).length / sells.length * 100) : 0;
  
  return {
    label,
    total: closed.length,
    wins: wins.length,
    losses: losses.length,
    winRate: +winRate.toFixed(1),
    totalPnL: +totalPnL.toFixed(2),
    avgPnL: +avgPnL.toFixed(2),
    profitFactor: +profitFactor.toFixed(2),
    maxDrawdown: +maxDD.toFixed(2),
    avgBars: +avgBars.toFixed(1),
    maxConsWins,
    maxConsLosses,
    forte: {
      total: forte.length,
      wins: forteWins.length,
      winRate: +forteWinRate.toFixed(1),
      pnl: +forte.reduce((a, t) => a + t.pnl, 0).toFixed(2)
    },
    buys: { count: buys.length, winRate: +buyWR.toFixed(1), pnl: +buys.reduce((a, t) => a + t.pnl, 0).toFixed(2) },
    sells: { count: sells.length, winRate: +sellWR.toFixed(1), pnl: +sells.reduce((a, t) => a + t.pnl, 0).toFixed(2) },
    equity: +equity.toFixed(2)
  };
}

function printResults(stats) {
  console.log(`\n┌──────────────────────────────────────────┐`);
  console.log(`│  ${stats.label.padEnd(40)}│`);
  console.log(`├──────────────────────────────────────────┤`);
  console.log(`│  Trades:        ${String(stats.total).padStart(6)}                   │`);
  console.log(`│  Win Rate:      ${(stats.winRate + '%').padStart(6)}  (${stats.wins}W / ${stats.losses}L)      │`);
  console.log(`│  Total P&L:    $${String(stats.totalPnL).padStart(8)}                │`);
  console.log(`│  Avg P&L:      $${String(stats.avgPnL).padStart(8)}                │`);
  console.log(`│  Profit Factor: ${String(stats.profitFactor).padStart(6)}                   │`);
  console.log(`│  Max Drawdown: $${String(stats.maxDrawdown).padStart(8)}                │`);
  console.log(`│  Avg Bars:      ${String(stats.avgBars).padStart(6)} H1 candles        │`);
  console.log(`│  Max Cons. W/L: ${String(stats.maxConsWins).padStart(3)}W / ${String(stats.maxConsLosses).padStart(3)}L              │`);
  console.log(`├──── FORTE signals ────────────────────────┤`);
  console.log(`│  Forte Trades:  ${String(stats.forte.total).padStart(6)}                   │`);
  console.log(`│  Forte WinRate: ${(stats.forte.winRate + '%').padStart(6)}                   │`);
  console.log(`│  Forte P&L:    $${String(stats.forte.pnl).padStart(8)}                │`);
  console.log(`├──── Direction ────────────────────────────┤`);
  console.log(`│  BUY:  ${String(stats.buys.count).padStart(4)} trades ${(stats.buys.winRate + '%').padStart(6)} WR $${String(stats.buys.pnl).padStart(8)}│`);
  console.log(`│  SELL: ${String(stats.sells.count).padStart(4)} trades ${(stats.sells.winRate + '%').padStart(6)} WR $${String(stats.sells.pnl).padStart(8)}│`);
  console.log(`└──────────────────────────────────────────┘`);
}

// ─── MAIN ────────────────────────────────────────────────────────────────────
async function main() {
  console.log('Downloading XAU/USD H1 candles...\n');

  const candles = await fetchCandles(PERIOD);
  if (candles.length < 200) {
    console.error('❌ Not enough candle data. Got:', candles.length);
    process.exit(1);
  }

  console.log('Computing indicators...\n');
  const indicators = calcIndicators(candles);
  
  // Run multiple configurations
  const configs = [
    // Soglie calibrate: BUY>=90, SELL>=68 (ottimizzate su 2272 combinazioni 730gg)
    { label: `OTTIMALE: BUY≥90/SELL≥68, TP=$20, SL=$12`, tp: 20, sl: 12, minScore: 68, minScoreForte: 80, buyThr: 90, sellThr: 68 },
    { label: `BASE: Score≥70, TP=$${TP}, SL=$${SL}`, tp: TP, sl: SL, minScore: 70, minScoreForte: 80 },
    { label: `STRICT: Score≥80, TP=$${TP}, SL=$${SL}`, tp: TP, sl: SL, minScore: 80, minScoreForte: 85 },
    { label: `SELL ONLY ≥68, TP=$20, SL=$12`, tp: 20, sl: 12, minScore: 68, minScoreForte: 80, buyThr: 999, sellThr: 68 },
    { label: `WIDE: Score≥68, TP=$25, SL=$15`, tp: 25, sl: 15, minScore: 68, minScoreForte: 80 },
    { label: `FORTE ONLY: Score≥85, TP=$20, SL=$12`, tp: 20, sl: 12, minScore: 85, minScoreForte: 85 },
  ];
  
  const allResults = [];
  
  for (const cfg of configs) {
    const trades = runBacktest(candles, indicators, cfg);
    const stats = analyzeResults(trades, cfg.label);
    allResults.push({ config: cfg, stats, trades });
    printResults(stats);
  }
  
  // Find best configuration
  const best = allResults.reduce((a, b) => {
    const aScore = a.stats.winRate * 0.4 + a.stats.profitFactor * 15 + (a.stats.forte.winRate || 0) * 0.2;
    const bScore = b.stats.winRate * 0.4 + b.stats.profitFactor * 15 + (b.stats.forte.winRate || 0) * 0.2;
    return aScore > bScore ? a : b;
  });
  
  console.log(`\n🏆 BEST CONFIG: ${best.config.label}`);
  console.log(`   Win Rate: ${best.stats.winRate}%  |  Profit Factor: ${best.stats.profitFactor}  |  P&L: $${best.stats.totalPnL}`);
  
  // Score distribution analysis
  console.log('\n📊 SCORE DISTRIBUTION (all trades from BASE config):');
  const baseTrades = allResults[0].trades;
  const scoreRanges = [
    { range: '90-100', min: 90, max: 100 },
    { range: '80-89', min: 80, max: 89 },
    { range: '70-79', min: 70, max: 79 },
    { range: '60-69', min: 60, max: 69 },
  ];
  for (const r of scoreRanges) {
    const matches = baseTrades.filter(t => t.score >= r.min && t.score <= r.max && t.result !== 'OPEN');
    const wr = matches.length > 0 ? (matches.filter(t => t.pnl > 0).length / matches.length * 100).toFixed(1) : 'N/A';
    const pnl = matches.reduce((a, t) => a + t.pnl, 0).toFixed(2);
    console.log(`   Score ${r.range}: ${String(matches.length).padStart(4)} trades, WR ${String(wr).padStart(5)}%, P&L $${pnl}`);
  }
  
  // Monthly breakdown
  console.log('\n📅 MONTHLY BREAKDOWN (BASE config):');
  const monthMap = new Map();
  for (const t of baseTrades) {
    if (t.result === 'OPEN') continue;
    const d = new Date(t.entryTime * 1000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    if (!monthMap.has(key)) monthMap.set(key, { trades: 0, wins: 0, pnl: 0 });
    const m = monthMap.get(key);
    m.trades++;
    if (t.pnl > 0) m.wins++;
    m.pnl += t.pnl;
  }
  for (const [month, m] of [...monthMap.entries()].sort()) {
    const wr = m.trades > 0 ? (m.wins / m.trades * 100).toFixed(0) : 0;
    console.log(`   ${month}: ${String(m.trades).padStart(3)} trades, WR ${String(wr).padStart(3)}%, P&L $${m.pnl.toFixed(2)}`);
  }
  
  // Sample trade log (last 10)
  console.log('\n📋 LAST 10 TRADES (BASE config):');
  const last10 = baseTrades.slice(-10);
  for (const t of last10) {
    const entry = new Date(t.entryTime * 1000).toISOString().slice(0, 16);
    console.log(`   ${entry} ${t.dir.toUpperCase().padEnd(4)} $${t.entry.toFixed(2)} → $${t.exit?.toFixed(2)} ${t.result.padEnd(4)} P&L $${t.pnl?.toFixed(2) ?? '?'} [Score:${t.score} CCI:${t.cciScore} MACD:${t.macdScore} ADX:${t.adxScore}]${t.forte ? ' ⭐' : ''}`);
  }
  
  // Save detailed results to file
  const reportPath = new URL('../backtest_report.json', import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1');
  const report = {
    generated: new Date().toISOString(),
    period: PERIOD + ' days',
    candles: candles.length,
    configs: allResults.map(r => ({
      ...r.config,
      stats: r.stats,
      tradeCount: r.trades.length,
      sampleTrades: r.trades.slice(-20)
    })),
    best: best.config.label,
    scoreDistribution: scoreRanges.map(r => {
      const m = baseTrades.filter(t => t.score >= r.min && t.score <= r.max && t.result !== 'OPEN');
      return {
        range: r.range,
        trades: m.length,
        winRate: m.length > 0 ? +(m.filter(t => t.pnl > 0).length / m.length * 100).toFixed(1) : null,
        pnl: +m.reduce((a, t) => a + t.pnl, 0).toFixed(2)
      };
    })
  };
  
  const { writeFileSync } = await import('fs');
  writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`\n📁 Full report saved: ${reportPath}`);
  
  console.log('\n✅ Backtest complete!');
}

main().catch(e => { console.error('Fatal:', e.message); process.exit(1); });
