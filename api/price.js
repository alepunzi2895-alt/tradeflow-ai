export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  try {
    // Yahoo Finance - no API key needed
    const url = "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=1m&range=1d";
    const response = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0" }
    });
    const data = await response.json();
    const quote = data?.chart?.result?.[0]?.meta;
    if (!quote) throw new Error("No data");

    const price = quote.regularMarketPrice;
    const prevClose = quote.chartPreviousClose || quote.previousClose;
    const change = price - prevClose;
    const changePct = ((change / prevClose) * 100).toFixed(2);
    const high = quote.regularMarketDayHigh;
    const low = quote.regularMarketDayLow;

    return res.status(200).json({
      price: price.toFixed(2),
      change: change.toFixed(2),
      changePct,
      high: high?.toFixed(2),
      low: low?.toFixed(2),
      timestamp: new Date().toISOString(),
    });
  } catch (err) {
    // Fallback: try alternative endpoint
    try {
      const url2 = "https://query2.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=1m&range=1d";
      const r2 = await fetch(url2, { headers: { "User-Agent": "Mozilla/5.0" } });
      const d2 = await r2.json();
      const q2 = d2?.chart?.result?.[0]?.meta;
      if (!q2) throw new Error("No fallback data");
      return res.status(200).json({
        price: q2.regularMarketPrice?.toFixed(2),
        change: "0.00",
        changePct: "0.00",
        high: q2.regularMarketDayHigh?.toFixed(2),
        low: q2.regularMarketDayLow?.toFixed(2),
        timestamp: new Date().toISOString(),
      });
    } catch {
      return res.status(500).json({ error: err.message });
    }
  }
}
