// Server-side proxy for TradingView Scanner
// Uses multiple ticker alternatives per symbol — picks first valid one

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");
  if (req.method === "OPTIONS") return res.status(200).end();

  const MULTI_TICKERS = [
    // XAU alternatives (by priority)
    'OANDA:XAUUSD', 'FOREXCOM:XAUUSD', 'PEPPERSTONE:XAUUSD',
    'CAPITALCOM:GOLD', 'EASYMARKETS:XAUUSD', 'TVC:GOLD',
    'FX:XAUUSD', 'SAXO:XAUUSD', 'FPMARKETS:XAUUSD',
    // SILVER alternatives
    'OANDA:XAGUSD', 'FOREXCOM:XAGUSD', 'PEPPERSTONE:XAGUSD',
    'CAPITALCOM:SILVER', 'EASYMARKETS:XAGUSD', 'TVC:SILVER',
    'FX:XAGUSD', 'SAXO:XAGUSD', 'FPMARKETS:XAGUSD',
    // Other symbols (mostly stable on TVC)
    'TVC:DXY', 'TVC:USOIL', 'TVC:US10Y',
    'OANDA:EURUSD', 'OANDA:GBPUSD',
    'FPMARKETS:EURUSD', 'FPMARKETS:GBPUSD',
  ];

  // Map each ticker to a canonical key
  const TICKER_KEY = {
    'OANDA:XAUUSD':'XAU','FOREXCOM:XAUUSD':'XAU','PEPPERSTONE:XAUUSD':'XAU',
    'CAPITALCOM:GOLD':'XAU','EASYMARKETS:XAUUSD':'XAU','TVC:GOLD':'XAU',
    'FX:XAUUSD':'XAU','SAXO:XAUUSD':'XAU','FPMARKETS:XAUUSD':'XAU',
    'OANDA:XAGUSD':'SILVER','FOREXCOM:XAGUSD':'SILVER','PEPPERSTONE:XAGUSD':'SILVER',
    'CAPITALCOM:SILVER':'SILVER','EASYMARKETS:XAGUSD':'SILVER','TVC:SILVER':'SILVER',
    'FX:XAGUSD':'SILVER','SAXO:XAGUSD':'SILVER','FPMARKETS:XAGUSD':'SILVER',
    'TVC:DXY':'DXY', 'TVC:USOIL':'OIL', 'TVC:US10Y':'US10Y',
    'OANDA:EURUSD':'EURUSD', 'OANDA:GBPUSD':'GBPUSD',
    'FPMARKETS:EURUSD':'EURUSD', 'FPMARKETS:GBPUSD':'GBPUSD',
  };

  try {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 8000);

    const body = {
      symbols: { tickers: MULTI_TICKERS, query: { types: [] } },
      columns: ['close', 'change', 'high', 'low']
    };

    const r = await fetch('https://scanner.tradingview.com/global/scan', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Origin': 'https://www.tradingview.com',
        'Referer': 'https://www.tradingview.com/'
      },
      body: JSON.stringify(body),
      signal: ctrl.signal
    });
    clearTimeout(tid);

    if (!r.ok) {
      console.log('TV Scanner HTTP', r.status);
      return res.status(503).json({ ok: false, error: 'TV Scanner HTTP ' + r.status });
    }

    const d = await r.json();
    if (!d.data?.length) {
      return res.status(503).json({ ok: false, error: 'TV Scanner empty' });
    }

    const prices = {};
    for (const item of d.data) {
      const key = TICKER_KEY[item.s];
      if (!key || !item.d) continue;
      if (prices[key]) continue; // already have a valid source for this key
      const [close, chgPct, high, low] = item.d;
      if (close == null || isNaN(+close)) continue;
      const dec = key==='XAU'||key==='OIL'||key==='SILVER' ? 2
                : key==='DXY'||key==='US10Y' ? 3 : 5;
      prices[key] = {
        price:  (+close).toFixed(dec),
        change: +(chgPct || 0).toFixed(2),
        high:   high != null ? (+high).toFixed(dec) : null,
        low:    low  != null ? (+low).toFixed(dec)  : null,
        _source: item.s,
      };
    }

    if (!prices.XAU) {
      console.log('TV Scanner: no XAU found. Got keys:', Object.keys(prices).join(','));
      return res.status(503).json({ ok: false, error: 'No XAU in response', got: Object.keys(prices) });
    }

    console.log('TV prices OK: XAU=' + prices.XAU.price + ' via ' + prices.XAU._source +
                ' SILVER=' + (prices.SILVER?.price || 'missing'));
    return res.status(200).json({ ok: true, prices, source: 'tradingview', timestamp: new Date().toISOString() });

  } catch (e) {
    console.log('TV Scanner error:', e.message);
    return res.status(503).json({ ok: false, error: e.message });
  }
}
