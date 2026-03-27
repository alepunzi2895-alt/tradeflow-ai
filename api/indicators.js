export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  const tf = (req.query?.tf || '1h').toLowerCase();
  const interval = tf === '1d' ? '1d' : '1h';
  // 3 days = ~72 H1 candles — enough for CCI(28)+MACD(26)+ADX(10) with warmup
  const range = tf === '1d' ? '60d' : '7d'; // 7d = ~168 H1 candles, enough for CCI(28)+Stoch(28)+SMA(8)+SMA(8)=72 warmup

  const SYMBOLS = ['XAUUSD=X', 'GC=F', 'GLD']; // XAUUSD spot first (closer to broker prices)

  async function fetch1(sym) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 8000);
    try {
      const r = await fetch(
        `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=${interval}&range=${range}`,
        { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }, signal: ctrl.signal }
      );
      clearTimeout(tid);
      if (!r.ok) return null;
      const d = await r.json();
      const rs = d?.chart?.result?.[0];
      if (!rs?.timestamp) return null;
      const q = rs.indicators?.quote?.[0] || {};
      const candles = [];
      for (let i = 0; i < rs.timestamp.length; i++) {
        if (q.close[i]!=null && q.high[i]!=null && q.low[i]!=null)
          candles.push({ t:rs.timestamp[i], h:q.high[i], l:q.low[i], c:q.close[i] });
      }
      if (candles.length < 30) return null;
      console.log(`${sym}: ${candles.length} candles, last=$${candles.at(-1).c.toFixed(2)}`);
      return candles;
    } catch(e) { clearTimeout(tid); return null; }
  }

  try {
    let raw = null;
    for (const sym of SYMBOLS) { raw = await fetch1(sym); if (raw) break; }
    if (!raw) return res.status(503).json({ ok:false, error:'Yahoo Finance non disponibile' });

    // Resample H1 → H4
    let candles = raw;
    if (tf === '4h') {
      const map = new Map();
      for (const c of raw) {
        const d = new Date(c.t * 1000);
        const b = Math.floor(d.getUTCHours()/4)*4;