// api/indicators.js — Hybrid: TV Scanner for MACD + server-side ADX(10) calculation
// CCI_S computed browser-side from /api/candles proxy
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  const tf = (req.query?.tf || '1h').toLowerCase();
  const asset = (req.query?.asset || 'XAU').toUpperCase();

  async function fetchT(url, opts = {}, ms = 8000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try { const r = await fetch(url, { ...opts, signal: ctrl.signal }); clearTimeout(tid); return r; }
    catch(e) { clearTimeout(tid); throw e; }
  }

  // Math helpers — exact Pine Script behaviour
  const sma = (src, p) => {
    const o = new Array(src.length).fill(null);
    for(let i = p-1; i < src.length; i++){
      const sl = src.slice(i-p+1, i+1);
      if(sl.some(v => v == null)){ o[i] = null; continue; }
      o[i] = sl.reduce((a,b) => a+b, 0) / p;
    }
    return o;
  };

  // ── TV Scanner: MACD(12,26,9) from OANDA:XAUUSD H1 ────────────────────────
  async function fetchTVScanner() {
    const resolution = tf === '1d' ? '' : '|60';
    const tickers = asset === 'XAG' ? ['OANDA:XAGUSD','FOREXCOM:XAGUSD','PEPPERSTONE:XAGUSD'] : ['OANDA:XAUUSD','FOREXCOM:XAUUSD','PEPPERSTONE:XAUUSD'];
    const body = {
      symbols: { tickers, query: { types: [] } },
      columns: [
        'close' + resolution,
        'MACD.macd' + resolution, 'MACD.signal' + resolution, 'MACD.hist' + resolution
      ]
    };
    try {
      const r = await fetchT('https://scanner.tradingview.com/global/scan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          'Origin': 'https://www.tradingview.com',
          'Referer': 'https://www.tradingview.com/'
        },
        body: JSON.stringify(body)
      }, 7000);
      if(!r.ok) return null;
      const d = await r.json();
      const item = d.data?.find(x => x.d && x.d[1] != null);
      if(!item) return null;
      const [close, macdLine, macdSig, macdHist] = item.d;
      console.log(`TV Scanner MACD: ${item.s} MACD=${(+macdLine).toFixed(2)} Sig=${(+macdSig).toFixed(2)}`);
      return { close: +close, macdLine: +macdLine, macdSig: +macdSig, macdHist: +macdHist, source: item.s };
    } catch(e) { console.log('TV Scanner:', e.message); return null; }
  }

  // ── Candles: fetch from our own proxy (bypasses CORS + tries multiple sources) ─
  async function fetchCandles() {
    try {
      const range = tf === '1d' ? '120d' : '60d';
      const interval = tf === '1d' ? '1d' : '1h';
      const baseUrl = req.headers?.host ? `https://${req.headers.host}` : '';
      
      // Fetch from Yahoo directly (server-side, no CORS issue)
      const symbols = asset === 'XAG' ? ['XAGUSD=X', 'SI=F'] : ['XAUUSD=X', 'GC=F'];
      for (const sym of symbols) {
        try {
          const url = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${interval}&range=${range}`;
          const r = await fetchT(url, {
            headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Accept': 'application/json' }
          }, 6000);
          if (!r.ok) continue;
          const d = await r.json();
          const rs = d?.chart?.result?.[0];
          if (!rs?.timestamp) continue;
          const q = rs.indicators?.quote?.[0] || {};
          const candles = [];
          for (let i = 0; i < rs.timestamp.length; i++) {
            if (q.close?.[i] != null && q.high?.[i] != null && q.low?.[i] != null)
              candles.push({ t: rs.timestamp[i], h: q.high[i], l: q.low[i], c: q.close[i] });
          }
          if (candles.length < 120) continue;
          console.log(`Candles OK: ${sym} ${candles.length}`);
          return { candles, source: sym };
        } catch(e) { console.log(`Yahoo ${sym}:`, e.message); }
      }

      // TradingView history fallback
      const now = Math.floor(Date.now() / 1000);
      const tvRes = tf === '1d' ? 'D' : '60';
      const from = now - 500 * (tvRes === 'D' ? 86400 : 3600);
      const tvSymbols = asset === 'XAG' ? ['OANDA:XAGUSD', 'FOREXCOM:XAGUSD'] : ['OANDA:XAUUSD', 'FOREXCOM:XAUUSD'];
      for (const sym of tvSymbols) {
        try {
          const url = `https://data.tradingview.com/history?symbol=${encodeURIComponent(sym)}&resolution=${tvRes}&from=${from}&to=${now}&countback=500`;
          const r = await fetchT(url, {
            headers: { 'User-Agent': 'Mozilla/5.0', 'Origin': 'https://www.tradingview.com', 'Referer': 'https://www.tradingview.com/' }
          }, 6000);
          if (!r.ok) continue;
          const d = await r.json();
          if (d.s !== 'ok' || !d.t?.length) continue;
          const candles = [];
          for (let i = 0; i < d.t.length; i++)
            if (d.c[i] != null && d.h[i] != null && d.l[i] != null)
              candles.push({ t: d.t[i], h: d.h[i], l: d.l[i], c: d.c[i] });
          if (candles.length < 120) continue;
          console.log(`TV history: ${sym} ${candles.length}`);
          return { candles, source: 'tv_' + sym };
        } catch(e) { console.log(`TV ${sym}:`, e.message); }
      }
      return null;
    } catch(e) { console.log('fetchCandles:', e.message); return null; }
  }

  // ── Compute ADX(10) — exact "ADX and DI for v4" Pine Script ────────────────
  function computeADX(candles) {
    const n = candles.length;
    if (n < 50) return null;
    const H = candles.map(x => x.h), L = candles.map(x => x.l), C = candles.map(x => x.c);
    const AP = 10; // Per=10 from user's TradingView settings

    const TR = new Array(n).fill(0), DMP = new Array(n).fill(0), DMM = new Array(n).fill(0);
    for (let i = 1; i < n; i++) {
      TR[i] = Math.max(H[i]-L[i], Math.abs(H[i]-C[i-1]), Math.abs(L[i]-C[i-1]));
      const upMove = H[i]-H[i-1], downMove = L[i-1]-L[i];
      DMP[i] = (upMove > downMove && upMove > 0) ? upMove : 0;
      DMM[i] = (downMove > upMove && downMove > 0) ? downMove : 0;
    }
    // Wilder smoothing: X = nz(X[1]) - nz(X[1])/len + value
    const sTR = new Array(n).fill(0), sDMP = new Array(n).fill(0), sDMM = new Array(n).fill(0);
    for (let i = 1; i < n; i++) {
      sTR[i]  = sTR[i-1]  - sTR[i-1]/AP  + TR[i];
      sDMP[i] = sDMP[i-1] - sDMP[i-1]/AP + DMP[i];
      sDMM[i] = sDMM[i-1] - sDMM[i-1]/AP + DMM[i];
    }
    const DIP = sTR.map((v,i) => v > 0 ? sDMP[i]/v*100 : 0);
    const DIM = sTR.map((v,i) => v > 0 ? sDMM[i]/v*100 : 0);
    const DX  = DIP.map((v,i) => { const s = v+DIM[i]; return s > 0 ? Math.abs(v-DIM[i])/s*100 : 0; });
    // ADX = SMA(DX, len) — Pine Script uses SMA, NOT Wilder RMA!
    const ADX = sma(DX, AP);

    return {
      adx:      +(ADX[n-1] ?? 0).toFixed(2),
      di_plus:  +DIP[n-1].toFixed(2),
      di_minus: +DIM[n-1].toFixed(2)
    };
  }

  // ── Compute CCI_S ──────────────────────────────────────────────────────────
  function computeCCIS(candles) {
    const n = candles.length;
    if (n < 120) return null;
    const C = candles.map(x => x.c);
    const CP = 50, SP = 50, SK = 8, SD = 8;
    const hi = (a,p,i) => { let m=-Infinity; for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.max(m,a[j]); return m; };
    const lo = (a,p,i) => { let m=Infinity;  for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.min(m,a[j]); return m; };

    const cci = new Array(n).fill(null);
    for(let i = CP-1; i < n; i++){
      const sl = C.slice(i-CP+1, i+1);
      const mn = sl.reduce((a,b) => a+b, 0) / CP;
      const md = sl.reduce((a,b) => a+Math.abs(b-mn), 0) / CP;
      cci[i] = md === 0 ? 0 : (C[i]-mn) / (0.015*md);
    }
    const stk = new Array(n).fill(null);
    for(let i = CP+SP-2; i < n; i++){
      if(cci[i] == null) continue;
      const lv = lo(cci,SP,i), hv = hi(cci,SP,i);
      stk[i] = (hv-lv) === 0 ? 50 : ((cci[i]-lv)/(hv-lv))*100;
    }
    const stk_k = sma(stk, SK);
    const stk_d = sma(stk_k, SD);
    const cv = stk_d[n-1] ?? 50;
    let cciSig = 'neutral';
    const cp = stk_d[n-2] ?? 50;
    if(cp >= 25 && cv < 25) cciSig = 'enter_buy';
    else if(cp <= 75 && cv > 75) cciSig = 'enter_sell';
    else if(cp > 75 && cv <= 75) cciSig = 'exit_sell';
    else if(cp < 25 && cv >= 25) cciSig = 'exit_buy';
    return { value: +cv.toFixed(2), signal: cciSig };
  }

  try {
    // Fetch TV Scanner (MACD) and candles in parallel
    const [scanner, candleResult] = await Promise.all([
      fetchTVScanner(),
      fetchCandles()
    ]);

    // Build response
    const response = { ok: true, timeframe: tf, timestamp: new Date().toISOString() };

    // MACD from TV Scanner (exact TradingView values)
    if (scanner) {
      response.last_close = scanner.close;
      response.macd_source = 'tv_scanner_' + scanner.source;
      response.macd = {
        macd:      +scanner.macdLine.toFixed(4),
        signal:    +scanner.macdSig.toFixed(4),
        histogram: +scanner.macdHist.toFixed(4),
        hist_rising: scanner.macdHist > 0,
        cross: scanner.macdLine > scanner.macdSig ? 'above' : 'below',
        diff: +(scanner.macdLine - scanner.macdSig).toFixed(4)
      };
    }

    // ADX(10) and CCI_S from candle data
    if (candleResult) {
      const { candles, source } = candleResult;
      response.candle_source = source;
      response.candle_count = candles.length;
      // Send candle_data for browser to use for live recalc
      response.candle_data = candles.slice(-500).map(x => ({ t: x.t, h: +x.h.toFixed(2), l: +x.l.toFixed(2), c: +x.c.toFixed(2) }));
      if (!response.last_close) response.last_close = candles.at(-1).c;

      // ADX(10) — exact "ADX and DI for v4" Pine Script
      const adxResult = computeADX(candles);
      if (adxResult) {
        response.adx = {
          ...adxResult,
          threshold: 10,
          trending: adxResult.adx > 10,
          strong: adxResult.adx > 25
        };
        console.log(`ADX(10): ${adxResult.adx} DI+=${adxResult.di_plus} DI-=${adxResult.di_minus}`);
      }

      // CCI_S — exact Pine Script v4
      const cciResult = computeCCIS(candles);
      if (cciResult) {
        response.cci = {
          ...cciResult,
          zone: cciResult.value > 75 ? 'overbought' : cciResult.value < 25 ? 'oversold' : 'neutral',
          ob: 75, os: 25
        };
        console.log(`CCI_S: ${cciResult.value} signal=${cciResult.signal}`);
      }
    }

    // Check that we have at least something useful
    if (!response.macd && !response.adx && !response.cci) {
      return res.status(503).json({ ok: false, error: 'No indicator data available' });
    }

    response.ok = true;
    console.log(`Indicators OK | MACD=${response.macd?.macd ?? 'N/A'} ADX=${response.adx?.adx ?? 'N/A'} CCI=${response.cci?.value ?? 'N/A'}`);
    return res.status(200).json(response);
  } catch(e) {
    console.error('Indicators:', e.message);
    return res.status(500).json({ ok: false, error: e.message });
  }
}
