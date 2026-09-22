import {fetchQuotes} from '../lib/market-quotes.js';
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

  let asset = (req.query.asset || "XAU").toUpperCase();
  let type = req.query.type || "price";
  if (req.url.includes("/api/candles")) type = "candles";
  else if (req.url.includes("/api/tvprice")) type = "price";

  if (type === 'candles') {
    const range = req.query.range || '60d';
    const interval = req.query.interval || '1h';

    // Helper: parse Yahoo chart response → candles[]
    function parseYahooChart(d) {
      const rs = d?.chart?.result?.[0];
      if (!rs?.timestamp) return null;
      const q = rs.indicators?.quote?.[0] || {};
      const out = [];
      for (let i = 0; i < rs.timestamp.length; i++) {
        if (q.close?.[i] != null)
          out.push({
            t: rs.timestamp[i],
            o: q.open?.[i]  ? +q.open[i].toFixed(2)  : +q.close[i].toFixed(2),
            h: q.high?.[i]  ? +q.high[i].toFixed(2)  : +q.close[i].toFixed(2),
            l: q.low?.[i]   ? +q.low[i].toFixed(2)   : +q.close[i].toFixed(2),
            c: +q.close[i].toFixed(2),
            v: q.volume?.[i] || 0
          });
      }
      return out.length >= 30 ? out : null;
    }

    // Ticker singolo verificato per i simboli macro della griglia Quotazioni (audit 2026-09-22:
    // ^TNX già in unità percentuale diretta, non serve scalare; niente equivalente pulito per
    // US02Y su Yahoo, quello resta fuori — la sua card usa lo spread 10Y-2Y dal prezzo live, non history).
    const MACRO_TICKERS = { VIX:'^VIX', SPX:'^GSPC', NDX:'^NDX', RUT:'^RUT', OIL:'CL=F', US10Y:'^TNX' };
    // GC=F / YM=F (futures) accettati come fallback SOLO per candles/indicatori tecnici
    let symbols = MACRO_TICKERS[asset] ? [MACRO_TICKERS[asset]]
                  : asset === 'XAG' ? ['XAGUSD=X', 'SI=F']
                  : (asset === 'US30' || asset === 'DJI') ? ['YM=F', '^DJI']
                  : ['XAUUSD=X', 'GC=F'];
    if(req.query.strict === '1')symbols=[asset==='XAG'?'XAGUSD=X':asset==='US30'?'^DJI':'XAUUSD=X'];
    const candleDeadline=Date.now()+7500;
    // Try query1 + query2, v8 + v7 for each symbol to maximise availability
    const yahooHosts = ['query1.finance.yahoo.com', 'query2.finance.yahoo.com'];
    const yahooVers  = ['v8', 'v7'];
    const yahooHeaders = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      'Accept': 'application/json',
      'Accept-Language': 'en-US,en;q=0.9',
    };

    for (const sym of symbols) {
      for (const host of yahooHosts) {
        for (const ver of yahooVers) {
          if(Date.now()>=candleDeadline)break;
          try {
            const url = `https://${host}/${ver}/finance/chart/${encodeURIComponent(sym)}?interval=${interval}&range=${range}`;
            const r = await fetchT(url, { headers: yahooHeaders }, Math.max(1,Math.min(2500,candleDeadline-Date.now())));
            if (!r.ok) continue;
            const d = await r.json();
            const candles = parseYahooChart(d);
            if (!candles) continue;
            return res.status(200).json({ ok: true, source: `${host}/${ver}/${sym}`, count: candles.length, candles });
          } catch (e) { console.log(`Candles ${host}/${ver}/${sym}:`, e.message); }
        }
      }
    }
    return res.status(503).json({ ok: false, error: 'No candle source available' });
  }

  res.setHeader('Cache-Control','no-store');
  const snapshot=await fetchQuotes();
  if(asset==='ALL' || req.url.includes('/api/tvprice'))return res.status(snapshot.ok?200:503).json(snapshot);
  const key=asset==='SILVER'?'XAG':asset==='DJI'?'US30':asset;
  const quote=snapshot.prices?.[key];
  if(!quote)return res.status(503).json({ok:false,error:'Quotazione non disponibile',timestamp:snapshot.timestamp});
  return res.status(200).json({ok:true,...quote,changePct:quote.change,source:quote._source,timestamp:snapshot.timestamp});
}
