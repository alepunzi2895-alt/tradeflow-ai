export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");
  if (req.method === "OPTIONS") return res.status(200).end();

  // Helper: fetch with timeout
  async function fetchT(url, opts = {}, ms = 6000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try {
      const r = await fetch(url, { ...opts, signal: ctrl.signal });
      clearTimeout(tid);
      return r;
    } catch (e) {
      clearTimeout(tid);
      throw e;
    }
  }

  // ── MULTI-ASSET LOGIC (from consolidated tvprice.js) ──
  const MULTI_TICKERS = [
    'OANDA:XAUUSD', 'FOREXCOM:XAUUSD', 'PEPPERSTONE:XAUUSD', 'CAPITALCOM:GOLD', 'EASYMARKETS:XAUUSD', 'TVC:GOLD', 'FX:XAUUSD', 'SAXO:XAUUSD', 'FPMARKETS:XAUUSD',
    'OANDA:XAGUSD', 'FOREXCOM:XAGUSD', 'PEPPERSTONE:XAGUSD', 'CAPITALCOM:SILVER', 'EASYMARKETS:XAGUSD', 'TVC:SILVER', 'FX:XAGUSD', 'SAXO:XAGUSD', 'FPMARKETS:XAGUSD',
    'TVC:DXY', 'TVC:USOIL', 'TVC:US10Y', 'OANDA:EURUSD', 'OANDA:GBPUSD', 'FPMARKETS:EURUSD', 'FPMARKETS:GBPUSD',
  ];
  const TICKER_KEY = {
    'OANDA:XAUUSD':'XAU','FOREXCOM:XAUUSD':'XAU','PEPPERSTONE:XAUUSD':'XAU','CAPITALCOM:GOLD':'XAU','EASYMARKETS:XAUUSD':'XAU','TVC:GOLD':'XAU','FX:XAUUSD':'XAU','SAXO:XAUUSD':'XAU','FPMARKETS:XAUUSD':'XAU',
    'OANDA:XAGUSD':'SILVER','FOREXCOM:XAGUSD':'SILVER','PEPPERSTONE:XAGUSD':'SILVER','CAPITALCOM:SILVER':'SILVER','EASYMARKETS:XAGUSD':'SILVER','TVC:SILVER':'SILVER','FX:XAGUSD':'SILVER','SAXO:XAGUSD':'SILVER','FPMARKETS:XAGUSD':'SILVER',
    'TVC:DXY':'DXY', 'TVC:USOIL':'OIL', 'TVC:US10Y':'US10Y', 'OANDA:EURUSD':'EURUSD', 'OANDA:GBPUSD':'GBPUSD', 'FPMARKETS:EURUSD':'EURUSD', 'FPMARKETS:GBPUSD':'GBPUSD',
  };

  let asset = (req.query.asset || "XAU").toUpperCase();
  let type = req.query.type || "price";
  if (req.url.includes("/api/candles")) type = "candles";
  else if (req.url.includes("/api/tvprice")) type = "price";

  if (type === 'candles') {
    const range = req.query.range || '60d';
    const interval = req.query.interval || '1h';
    const symbols = asset === 'XAG' ? ['XAGUSD=X', 'SI=F'] : ['XAUUSD=X', 'GC=F'];
    for (const sym of symbols) {
      try {
        const url = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${interval}&range=${range}`;
        const r = await fetchT(url, { headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' } }, 7000);
        if (!r.ok) continue;
        const d = await r.json();
        const rs = d?.chart?.result?.[0];
        if (!rs?.timestamp) continue;
        const q = rs.indicators?.quote?.[0] || {};
        const candles = [];
        for (let i = 0; i < rs.timestamp.length; i++) {
          if (q.close?.[i] != null)
            candles.push({ 
              t: rs.timestamp[i], 
              o: q.open?.[i] ? +q.open[i].toFixed(2) : +q.close[i].toFixed(2),
              h: q.high?.[i] ? +q.high[i].toFixed(2) : +q.close[i].toFixed(2), 
              l: q.low?.[i] ? +q.low[i].toFixed(2) : +q.close[i].toFixed(2), 
              c: +q.close[i].toFixed(2),
              v: q.volume?.[i] || 0
            });
        }
        if (candles.length < 30) continue;
        return res.status(200).json({ ok: true, source: sym, count: candles.length, candles });
      } catch (e) { console.log(`Price Hub Candles ${sym}:`, e.message); }
    }
    return res.status(503).json({ ok: false, error: 'No candle source available' });
  }

  if (asset === 'ALL') {
    try {
      const body = { symbols: { tickers: MULTI_TICKERS, query: { types: [] } }, columns: ['close', 'change', 'high', 'low'] };
      const r = await fetchT('https://scanner.tradingview.com/global/scan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0',
          'Origin': 'https://www.tradingview.com',
          'Referer': 'https://www.tradingview.com/'
        },
        body: JSON.stringify(body)
      }, 7000);
      if (r.ok) {
        const d = await r.json();
        const prices = {};
        for (const item of d.data) {
          const key = TICKER_KEY[item.s];
          if (!key || !item.d || prices[key]) continue;
          const [close, chgPct, high, low] = item.d;
          if (close == null || isNaN(+close)) continue;
          const dec = (key==='XAU'||key==='OIL'||key==='SILVER') ? 2 : (key==='DXY'||key==='US10Y') ? 3 : 5;
          prices[key] = { price: (+close).toFixed(dec), change: +(chgPct || 0).toFixed(2), high: high != null ? (+high).toFixed(dec) : null, low: low != null ? (+low).toFixed(dec) : null, _source: item.s };
        }
        return res.status(200).json({ ok: true, prices, source: 'tradingview', timestamp: new Date().toISOString() });
      }
    } catch (e) {
      console.log('price.js ALL failed:', e.message);
      return res.status(503).json({ ok: false, error: e.message });
    }
  }

  // ── SINGLE ASSET LOGIC (Original price.js) ──
  const isXag = asset === 'XAG' || asset === 'SILVER';
  try {
    const tickers = isXag ? [
      'OANDA:XAGUSD', 'FOREXCOM:XAGUSD', 'PEPPERSTONE:XAGUSD',
      'CAPITALCOM:SILVER', 'EASYMARKETS:XAGUSD', 'FPMARKETS:XAGUSD',
      'TVC:SILVER', 'FX:XAGUSD', 'SAXO:XAGUSD'
    ] : [
      'OANDA:XAUUSD', 'FOREXCOM:XAUUSD', 'PEPPERSTONE:XAUUSD',
      'CAPITALCOM:GOLD', 'EASYMARKETS:XAUUSD', 'FPMARKETS:XAUUSD',
      'TVC:GOLD', 'FX:XAUUSD', 'SAXO:XAUUSD'
    ];
    const body = {
      symbols: { tickers: tickers, query: { types: [] } },
      columns: ['close', 'change', 'high', 'low']
    };
    const r = await fetchT('https://scanner.tradingview.com/global/scan', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0',
        'Origin': 'https://www.tradingview.com',
        'Referer': 'https://www.tradingview.com/'
      },
      body: JSON.stringify(body)
    }, 6000);

    if (r.ok) {
      const d = await r.json();
      const item = d.data?.find(x => x.d && x.d[0] != null && !isNaN(+x.d[0]));
      if (item) {
        const [close, chgPct, high, low] = item.d;
        return res.status(200).json({
          price: (+close).toFixed(2),
          change: (chgPct != null ? (+chgPct).toFixed(2) : "0.00"),
          changePct: (chgPct != null ? (+chgPct).toFixed(2) : "0.00"),
          high: high != null ? (+high).toFixed(2) : null,
          low: low != null ? (+low).toFixed(2) : null,
          source: 'tradingview_' + item.s,
          timestamp: new Date().toISOString(),
        });
      }
    }
  } catch (e) { console.log('price.js TV Scanner failed:', e.message); }

  // Fallback to Yahoo
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${asset === 'SILVER' ? 'XAG' : asset}USD=X?interval=1m&range=1d`;
    const response = await fetchT(url, { headers: { "User-Agent": "Mozilla/5.0" } }, 5000);
    const data = await response.json();
    const quote = data?.chart?.result?.[0]?.meta;
    if (quote && quote.regularMarketPrice) {
      const price = quote.regularMarketPrice;
      const prevClose = quote.chartPreviousClose || quote.previousClose;
      const change = price - prevClose;
      return res.status(200).json({
        price: price.toFixed(2),
        change: change.toFixed(2),
        changePct: ((change / prevClose) * 100).toFixed(2),
        high: quote.regularMarketDayHigh?.toFixed(2),
        low: quote.regularMarketDayLow?.toFixed(2),
        source: 'yahoo',
        timestamp: new Date().toISOString(),
      });
    }
  } catch (e) { console.log('price.js Yahoo failed:', e.message); }

  return res.status(503).json({ error: "All price sources failed" });
}
