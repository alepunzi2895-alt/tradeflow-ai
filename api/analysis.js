// api/analysis.js — Super-Consolidated Analysis Engine
// Combines: market.js, indicators.js, cot-update.js

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache");
  if (req.method === "OPTIONS") return res.status(200).end();

  let type = req.query.type || 'market';
  if (req.url.includes("/api/indicators")) type = "indicators";
  else if (req.url.includes("/api/cot-update")) type = "cot-update";
  
  const asset = (req.query.asset || 'XAU').toUpperCase();
  const tf = (req.query.tf || '1h').toLowerCase();

  // ── HELPERS ───────────────────────────────────────────────────────────────
  async function fetchT(url, opts = {}, ms = 8000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try { const r = await fetch(url, { ...opts, signal: ctrl.signal }); clearTimeout(tid); return r; }
    catch(e) { clearTimeout(tid); throw e; }
  }

  const sma = (src, p) => {
    const o = new Array(src.length).fill(null);
    for(let i = p-1; i < src.length; i++){
      const sl = src.slice(i-p+1, i+1);
      if(sl.some(v => v == null)){ o[i] = null; continue; }
      o[i] = sl.reduce((a,b) => a+b, 0) / p;
    }
    return o;
  };

  async function yahooQuote(symbol) {
    const r = await fetchT(`https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1m&range=1d`, { headers: { "User-Agent": "Mozilla/5.0" } });
    const d = await r.json();
    const meta = d?.chart?.result?.[0]?.meta;
    if (!meta) throw new Error("No Yahoo meta");
    return { price: meta.regularMarketPrice, change: parseFloat(((meta.regularMarketPrice - (meta.chartPreviousClose||meta.previousClose))/meta.previousClose*100).toFixed(2)), high: meta.regularMarketDayHigh, low: meta.regularMarketDayLow };
  }

  // ── BRANCH: MARKET DATA & SENTIMENT ───────────────────────────────────────
  if (type === 'market' || type === 'prices' || type === 'sentiment' || type === 'calendar' || type === 'cot') {
    // ── PRICES (from market.js) ──
    if (type === "prices") {
      const symbols = ['OANDA:XAUUSD','TVC:DXY','OANDA:EURUSD','OANDA:GBPUSD','TVC:USOIL','OANDA:XAGUSD','TVC:US10Y'];
      const body = { symbols: { tickers: symbols, query: { types: [] } }, columns: ['close', 'change', 'high', 'low'] };
      const r = await fetchT('https://scanner.tradingview.com/global/scan', { method: 'POST', body: JSON.stringify(body), headers: { 'User-Agent': 'Mozilla/5.0' } });
      const d = await r.json();
      const prices = {};
      d.data?.forEach(item => {
        const key = item.s.split(':')[1].replace('USD','').replace('GOLD','XAU').replace('SILVER','XAG');
        const k = key === 'XAG' ? 'SILVER' : key === 'OIL' ? 'OIL' : key;
        prices[k] = { price: item.d[0].toFixed(2), change: item.d[1].toFixed(2), high: item.d[2]?.toFixed(2), low: item.d[3]?.toFixed(2) };
      });
      // Contextual signals
      if (prices.US10Y) prices.US10Y_CONTEXT = { yield: +prices.US10Y.price, signal: prices.US10Y.change > 0 ? "BEARISH_GOLD" : "BULLISH_GOLD" };
      return res.status(200).json({ ok:true, prices, timestamp:new Date().toISOString() });
    }

    // ── SENTIMENT (from market.js) ──
    if (type === "sentiment") {
      const mfxSession = req.query.session || "";
      const url = mfxSession ? `https://www.myfxbook.com/api/get-community-outlook.json?session=${mfxSession}&symbols=XAUUSD` : "https://www.myfxbook.com/api/get-community-outlook.json?session=&symbols=XAUUSD";
      const r = await fetchT(url, { headers: { "User-Agent": "Mozilla/5.0" } });
      const d = await r.json();
      const sym = d.symbols?.find(s => s.name === "XAUUSD");
      if (sym) {
        const lp = parseFloat(sym.longPercentage), sp = parseFloat(sym.shortPercentage);
        return res.status(200).json({ ok:true, xauusd: { longPct: lp, shortPct: sp, signal: lp>60?"RETAIL_LONG":sp>60?"RETAIL_SHORT":"MIXED" } });
      }
      return res.status(200).json({ ok:false });
    }

    // ── CALENDAR (from market.js) ──
    if (type === "calendar") {
      const r = await fetchT("https://nfs.faireconomy.media/ff_calendar_thisweek.json", { headers:{"User-Agent":"Mozilla/5.0"} });
      const data = await r.json();
      const events = data.filter(e => ["USD","EUR"].includes(e.country) && e.impact === "High").slice(0,8);
      return res.status(200).json({ ok:true, events });
    }

    // ── COT (from market.js) ──
    if (type === "cot") {
      const r = await fetchT(`https://raw.githubusercontent.com/${process.env.GITHUB_OWNER}/${process.env.GITHUB_REPO}/main/data/cot_data.json`, { headers:{"Authorization":`Bearer ${process.env.GITHUB_TOKEN}`} });
      const d = await r.json();
      return res.status(200).json({ ok:true, ...d });
    }
  }

  // ── BRANCH: INDICATORS (from indicators.js) ───────────────────────────────
  if (type === 'indicators') {
    const tickers = asset === 'XAG' ? ['OANDA:XAGUSD'] : ['OANDA:XAUUSD'];
    const resolution = tf === '1d' ? '' : '|60';
    const body = { symbols: { tickers, query: { types: [] } }, columns: ['close'+resolution, 'MACD.macd'+resolution, 'MACD.signal'+resolution, 'MACD.hist'+resolution] };
    const r = await fetchT('https://scanner.tradingview.com/global/scan', { method: 'POST', body: JSON.stringify(body) });
    const d = await r.json();
    const item = d.data?.[0]?.d;
    if (!item) return res.status(503).json({ ok:false, error:"TV Scanner failed" });
    const [close, m, s, h] = item;
    return res.status(200).json({ ok: true, last_close: close, macd: { macd: +m.toFixed(4), signal: +s.toFixed(4), histogram: +h.toFixed(4), cross: m>s?'above':'below' } });
  }

  // ── BRANCH: COT UPDATE (from cot-update.js) ───────────────────────────────
  if (type === 'cot-update') {
    const r = await fetchT(`https://data.nasdaq.com/api/v3/datasets/CFTC/088691_FO_L_ALL.json?rows=2`);
    const d = await r.json();
    const rows = d?.dataset?.data;
    if (rows?.[0]) {
      const latest = rows[0], prev = rows[1];
      const netLong = Math.round((parseInt(latest[2]) - parseInt(latest[3]))/1000);
      const prevNet = prev ? Math.round((parseInt(prev[2]) - parseInt(prev[3]))/1000) : netLong;
      const cotData = { ok: true, reportDate: latest[0], netLong, weekChange: netLong - prevNet, interpretation: `Large spec net ${netLong}K` };
      // Save to GitHub
      if (process.env.GITHUB_TOKEN) {
        const getR = await fetchT(`https://api.github.com/repos/${process.env.GITHUB_OWNER}/${process.env.GITHUB_REPO}/contents/data/cot_data.json`, { headers: { "Authorization": `Bearer ${process.env.GITHUB_TOKEN}` } });
        const sha = getR.ok ? (await getR.json()).sha : null;
        await fetch(`https://api.github.com/repos/${process.env.GITHUB_OWNER}/${process.env.GITHUB_REPO}/contents/data/cot_data.json`, { method: "PUT", headers: { "Authorization": `Bearer ${process.env.GITHUB_TOKEN}`, "Content-Type": "application/json" }, body: JSON.stringify({ message: "COT update", content: Buffer.from(JSON.stringify(cotData, null, 2)).toString("base64"), ...(sha ? { sha } : {}) }) });
      }
      return res.status(200).json(cotData);
    }
  }

  return res.status(400).json({ error: "Unknown analysis type" });
}
