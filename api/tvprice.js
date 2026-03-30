// Server-side proxy for TradingView Scanner
// Avoids CORS issues — TV Scanner is called from Vercel server, not browser

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");
  if (req.method === "OPTIONS") return res.status(200).end();

  const SYMS = {
    XAU:    'FPMARKETS:XAUUSD',
    DXY:    'TVC:DXY',
    EURUSD: 'FPMARKETS:EURUSD',
    GBPUSD: 'FPMARKETS:GBPUSD',
    OIL:    'TVC:USOIL',
    US10Y:  'TVC:US10Y',
    SILVER: 'FPMARKETS:XAGUSD',
  };

  try {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 8000);

    const body = {
      symbols: { tickers: Object.values(SYMS), query: { types: [] } },
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

    // Build reverse map
    const REV = Object.fromEntries(Object.entries(SYMS).map(([k,v]) => [v, k]));
    const prices = {};
    for (const item of d.data) {
      const key = REV[item.s];
      if (!key || !item.d) continue;
      const [close, chgPct, high, low] = item.d;
      if (close == null || isNaN(+close)) continue;
      const dec = key==='XAU'||key==='OIL'||key==='SILVER' ? 2
                : key==='DXY'||key==='US10Y' ? 3 : 5;
      prices[key] = {
        price:  (+close).toFixed(dec),
        change: +(chgPct || 0).toFixed(2),
        high:   high != null ? (+high).toFixed(dec) : null,
        low:    low  != null ? (+low).toFixed(dec)  : null,
      };
    }

    if (!prices.XAU) {
      return res.status(503).json({ ok: false, error: 'No XAU in response' });
    }

    console.log('TV prices OK: XAU=' + prices.XAU.price);
    return res.status(200).json({ ok: true, prices, source: 'tradingview', timestamp: new Date().toISOString() });

  } catch (e) {
    console.log('TV Scanner error:', e.message);
    return res.status(503).json({ ok: false, error: e.message });
  }
}
