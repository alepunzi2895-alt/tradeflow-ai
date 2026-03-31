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

  // ── SOURCE 1: TradingView Scanner (primary) ──
  // Try multiple tickers — FPMARKETS may be down, try OANDA, FOREXCOM, TVC, CAPITALCOM
  try {
    const asset = (req.query.asset || 'XAU').toUpperCase();
    const isXag = asset === 'XAG';
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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Origin': 'https://www.tradingview.com',
        'Referer': 'https://www.tradingview.com/'
      },
      body: JSON.stringify(body)
    }, 6000);

    if (r.ok) {
      const d = await r.json();
      // Find first valid XAU ticker
      const item = d.data?.find(x => x.d && x.d[0] != null && !isNaN(+x.d[0]));
      if (item) {
        const [close, chgPct, high, low] = item.d;
        console.log(`price.js: TV Scanner OK via ${item.s} ${asset}=${(+close).toFixed(2)}`);
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
  } catch (e) {
    console.log('price.js TV Scanner failed:', e.message);
  }

  // ── SOURCE 2: Yahoo Finance v8 (fallback) ──
  try {
    const asset = (req.query.asset || 'XAU').toUpperCase();
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${asset}USD=X?interval=1m&range=1d`;
    const response = await fetchT(url, {
      headers: { "User-Agent": "Mozilla/5.0" }
    }, 5000);
    const data = await response.json();
    const quote = data?.chart?.result?.[0]?.meta;
    if (quote && quote.regularMarketPrice) {
      const price = quote.regularMarketPrice;
      const prevClose = quote.chartPreviousClose || quote.previousClose;
      const change = price - prevClose;
      const changePct = ((change / prevClose) * 100).toFixed(2);
      console.log(`price.js: Yahoo OK, ${asset}=` + price.toFixed(2));
      return res.status(200).json({
        price: price.toFixed(2),
        change: change.toFixed(2),
        changePct,
        high: quote.regularMarketDayHigh?.toFixed(2),
        low: quote.regularMarketDayLow?.toFixed(2),
        source: 'yahoo',
        timestamp: new Date().toISOString(),
      });
    }
  } catch (e) {
    console.log('price.js Yahoo failed:', e.message);
  }

  // ── SOURCE 3: Yahoo v8 query2 (last resort) ──
  try {
    const asset = (req.query.asset || 'XAU').toUpperCase();
    const url2 = `https://query2.finance.yahoo.com/v8/finance/chart/${asset}USD=X?interval=1m&range=1d`;
    const r2 = await fetchT(url2, { headers: { "User-Agent": "Mozilla/5.0" } }, 5000);
    const d2 = await r2.json();
    const q2 = d2?.chart?.result?.[0]?.meta;
    if (q2 && q2.regularMarketPrice) {
      return res.status(200).json({
        price: q2.regularMarketPrice?.toFixed(2),
        change: "0.00",
        changePct: "0.00",
        high: q2.regularMarketDayHigh?.toFixed(2),
        low: q2.regularMarketDayLow?.toFixed(2),
        source: 'yahoo_q2',
        timestamp: new Date().toISOString(),
      });
    }
  } catch (e) {
    console.log('price.js Yahoo q2 failed:', e.message);
  }

  return res.status(503).json({ error: "All price sources failed" });
}
