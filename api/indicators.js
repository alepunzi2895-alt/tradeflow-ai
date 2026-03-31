// indicators.js -- SIMPLIFIED: TV Scanner only for MACD/ADX (no candle fetch on server)
// CCI_S candle data is fetched client-side in mfkk.js (browser bypasses Vercel IP blocking)
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  async function fetchT(url, opts = {}, ms = 8000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try { const r = await fetch(url, { ...opts, signal: ctrl.signal }); clearTimeout(tid); return r; }
    catch(e) { clearTimeout(tid); throw e; }
  }

  // TV Scanner: exact MACD(12,26,9) and ADX(10) values from OANDA:XAUUSD H1
  const tickers = ['OANDA:XAUUSD','FOREXCOM:XAUUSD','PEPPERSTONE:XAUUSD'];
  const body = {
    symbols: { tickers, query: { types: [] } },
    columns: [
      'close|60', 'change|60',
      'MACD.macd|60', 'MACD.signal|60', 'MACD.hist|60',
      'ADX[10]|60', 'plus_di[10]|60', 'minus_di[10]|60'
    ]
  };

  try {
    const r = await fetchT('https://scanner.tradingview.com/global/scan', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Origin': 'https://www.tradingview.com',
        'Referer': 'https://www.tradingview.com/'
      },
      body: JSON.stringify(body)
    }, 8000);

    if(!r.ok) return res.status(502).json({ ok: false, error: `TV Scanner HTTP ${r.status}` });
    const d = await r.json();
    const item = d.data?.find(x => x.d && x.d[2] != null && !isNaN(+x.d[2]));
    if(!item) return res.status(503).json({ ok: false, error: 'TV Scanner no valid data' });

    const [close, change, macdLine, macdSig, macdHist, adx, diPlus, diMinus] = item.d;

    console.log(`TV Scanner OK: ${item.s} MACD=${(+macdLine).toFixed(2)} Signal=${(+macdSig).toFixed(2)} ADX=${(+adx).toFixed(2)} DI+=${(+diPlus).toFixed(2)} DI-=${(+diMinus).toFixed(2)}`);

    return res.status(200).json({
      ok: true,
      source: 'tv_scanner_' + item.s,
      timestamp: new Date().toISOString(),
      last_close: +(+close).toFixed(2),
      // MACD(12,26,9) exact values from TradingView OANDA:XAUUSD H1
      macd: {
        macd:      +(+macdLine).toFixed(4),
        signal:    +(+macdSig).toFixed(4),
        histogram: +(+macdHist).toFixed(4),
        hist_rising: (+macdHist) > 0,
        cross: (+macdLine) > (+macdSig) ? 'above' : 'below',
        diff: +((+macdLine)-(+macdSig)).toFixed(4)
      },
      // ADX(10) exact values from TradingView OANDA:XAUUSD H1
      adx: {
        adx:      +(+adx).toFixed(2),
        di_plus:  +(+diPlus).toFixed(2),
        di_minus: +(+diMinus).toFixed(2),
        threshold: 10,
        trending: (+adx) > 10,
        strong:   (+adx) > 25
      }
      // NOTE: cci is not returned here — computed client-side from browser-fetched candles
    });
  } catch(e) {
    console.error('TV Scanner error:', e.message);
    return res.status(503).json({ ok: false, error: e.message });
  }
}
