function buildSentiment(lp, sp){
  return {
    longPct: lp, shortPct: sp,
    signal: lp>60?"RETAIL_LONG_HEAVY":sp>60?"RETAIL_SHORT_HEAVY":"MIXED",
    contrarian: lp>65?"BEARISH_BIAS":sp>65?"BULLISH_BIAS":"NEUTRAL",
    note: lp>65?"⚠️ Retail "+Math.round(lp)+"% long — smart money probab. SHORT":
          sp>65?"⚠️ Retail "+Math.round(sp)+"% short — possibile squeeze":""
  };
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache");
  const { type, currency } = req.query;

  // Helper: fetch with timeout
  async function fetchWithTimeout(url, opts={}, ms=8000){
    const ctrl=new AbortController();
    const id=setTimeout(()=>ctrl.abort(),ms);
    try{ const r=await fetch(url,{...opts,signal:ctrl.signal}); clearTimeout(id); return r; }
    catch(e){ clearTimeout(id); throw e; }
  }

  // Helper: get Yahoo Finance quote
  async function yahooQuote(symbol){
    const r=await fetchWithTimeout(
      `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1m&range=1d`,
      {headers:{"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}}
    );
    if(!r.ok) throw new Error(`Yahoo ${symbol}: ${r.status}`);
    const d=await r.json();
    const meta=d?.chart?.result?.[0]?.meta;
    if(!meta) throw new Error(`No meta for ${symbol}`);
    const price=meta.regularMarketPrice;
    const prev=meta.chartPreviousClose||meta.previousClose||price;
    return {
      price: price,
      change: parseFloat(((price-prev)/prev*100).toFixed(2)),
      high: meta.regularMarketDayHigh,
      low: meta.regularMarketDayLow,
      prev,
    };
  }

  try {
    // ── FX RATE ────────────────────────────────────────────
    if (type === "fx") {
      const cur = currency || "EUR";
      // Map to Yahoo symbols
      const syms = { EUR:"EURUSD=X", GBP:"GBPUSD=X", CHF:"CHF=X", JPY:"JPY=X" };
      const sym = syms[cur] || `${cur}=X`;