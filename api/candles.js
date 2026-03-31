// api/candles.js — Server-side proxy for Yahoo Finance candle data
// Browsers can't fetch Yahoo Finance directly due to CORS
// Vercel serverless CAN fetch Yahoo (despite IP blocks for some endpoints, chart API works)
export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "s-maxage=60, stale-while-revalidate=30");

  const range = req.query?.range || '60d';
  const interval = req.query?.interval || '1h';

  async function fetchT(url, opts = {}, ms = 9000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try { const r = await fetch(url, { ...opts, signal: ctrl.signal }); clearTimeout(tid); return r; }
    catch(e) { clearTimeout(tid); throw e; }
  }

  // Try multiple Yahoo symbols for spot gold
  const symbols = ['XAUUSD=X', 'GC=F'];
  
  for (const sym of symbols) {
    try {
      const url = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${interval}&range=${range}`;
      console.log(`Candles: trying ${sym} range=${range} interval=${interval}`);
      
      const r = await fetchT(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
          'Accept': 'application/json'
        }
      });

      if (!r.ok) {
        console.log(`Yahoo ${sym}: HTTP ${r.status}`);
        continue;
      }

      const d = await r.json();
      const rs = d?.chart?.result?.[0];
      if (!rs?.timestamp) {
        console.log(`Yahoo ${sym}: no timestamp data`);
        continue;
      }

      const q = rs.indicators?.quote?.[0] || {};
      const candles = [];
      for (let i = 0; i < rs.timestamp.length; i++) {
        if (q.close?.[i] != null && q.high?.[i] != null && q.low?.[i] != null) {
          candles.push({
            t: rs.timestamp[i],
            h: +q.high[i].toFixed(2),
            l: +q.low[i].toFixed(2),
            c: +q.close[i].toFixed(2)
          });
        }
      }

      if (candles.length < 30) {
        console.log(`Yahoo ${sym}: too few candles (${candles.length})`);
        continue;
      }

      console.log(`Candles OK: ${sym} ${candles.length} candles, last=$${candles.at(-1).c}`);
      return res.status(200).json({
        ok: true,
        source: sym,
        count: candles.length,
        candles
      });
    } catch (e) {
      console.log(`Yahoo ${sym}: ${e.message}`);
    }
  }

  // All sources failed — try TradingView history as last resort
  try {
    const now = Math.floor(Date.now() / 1000);
    const count = 500;
    const tvRes = interval === '1d' ? 'D' : '60';
    const from = now - count * (tvRes === 'D' ? 86400 : 3600) - 86400;
    
    for (const sym of ['OANDA:XAUUSD', 'FOREXCOM:XAUUSD']) {
      try {
        const url = `https://data.tradingview.com/history?symbol=${encodeURIComponent(sym)}&resolution=${tvRes}&from=${from}&to=${now}&countback=${count}`;
        const r = await fetchT(url, {
          headers: {
            'User-Agent': 'Mozilla/5.0',
            'Origin': 'https://www.tradingview.com',
            'Referer': 'https://www.tradingview.com/'
          }
        });
        if (!r.ok) continue;
        const d = await r.json();
        if (d.s !== 'ok' || !d.t?.length) continue;
        
        const candles = [];
        for (let i = 0; i < d.t.length; i++) {
          if (d.c[i] != null && d.h[i] != null && d.l[i] != null)
            candles.push({ t: d.t[i], h: +d.h[i].toFixed(2), l: +d.l[i].toFixed(2), c: +d.c[i].toFixed(2) });
        }
        if (candles.length < 30) continue;
        
        console.log(`TV history OK: ${sym} ${candles.length} candles`);
        return res.status(200).json({ ok: true, source: 'tv_' + sym, count: candles.length, candles });
      } catch (e) { console.log(`TV ${sym}: ${e.message}`); }
    }
  } catch (e) { console.log('TV history fallback:', e.message); }

  return res.status(503).json({ ok: false, error: 'No candle source available' });
}
