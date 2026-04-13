// TradeFlow AI — api/market.js
// Centralized Hub for Market Data: Prices, Sentiment, Calendar, COT

const BASE_MFX = 'https://www.myfxbook.com/api';

const TICKERS = [
  'OANDA:XAUUSD', 'FOREXCOM:XAUUSD', 'PEPPERSTONE:XAUUSD', 'CAPITALCOM:GOLD', 'TVC:GOLD', 
  'FX:XAUUSD', 'SAXO:XAUUSD', 'FPMARKETS:XAUUSD', 'TVC:USOIL', 'CAPITALCOM:OIL', 'OANDA:WTICOUSD', 'TVC:US10Y', 'TVC:DXY', 
  'OANDA:EURUSD', 'OANDA:GBPUSD', 'FPMARKETS:EURUSD', 'FPMARKETS:GBPUSD',
  'OANDA:XAGUSD', 'FOREXCOM:XAGUSD', 'PEPPERSTONE:XAGUSD', 'CAPITALCOM:SILVER', 'TVC:SILVER', 
  'FX:XAGUSD', 'SAXO:XAGUSD', 'FPMARKETS:XAGUSD'
];

const TICKER_MAP = {
  'OANDA:XAUUSD':'XAU','FOREXCOM:XAUUSD':'XAU','PEPPERSTONE:XAUUSD':'XAU','CAPITALCOM:GOLD':'XAU','TVC:GOLD':'XAU','FX:XAUUSD':'XAU','SAXO:XAUUSD':'XAU','FPMARKETS:XAUUSD':'XAU',
  'OANDA:XAGUSD':'SILVER','FOREXCOM:XAGUSD':'SILVER','PEPPERSTONE:XAGUSD':'SILVER','CAPITALCOM:SILVER':'SILVER','TVC:SILVER':'SILVER','FX:XAGUSD':'SILVER','SAXO:XAGUSD':'SILVER','FPMARKETS:XAGUSD':'SILVER',
  'OANDA:EURUSD':'EURUSD', 'OANDA:GBPUSD':'GBPUSD', 'FPMARKETS:EURUSD':'EURUSD', 'FPMARKETS:GBPUSD':'GBPUSD',
  'TVC:DXY':'DXY', 'TVC:USOIL':'OIL', 'CAPITALCOM:OIL':'OIL', 'OANDA:WTICOUSD':'OIL', 'TVC:US10Y':'US10Y'
};

async function fetchWithTimeout(url, opts={}, ms=7000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal });
    clearTimeout(tid);
    return r;
  } catch(e) {
    clearTimeout(tid);
    throw e;
  }
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  const { type, symbol, session } = req.query;

  try {
    // ── 1. PRICES (TradingView Scanner) ────────────────────
    if (type === 'prices') {
      const body = { 
        symbols: { tickers: TICKERS, query: { types: [] } }, 
        columns: ['close', 'change', 'high', 'low'] 
      };
      const r = await fetchWithTimeout('https://scanner.tradingview.com/global/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0' },
        body: JSON.stringify(body)
      });
      if (!r.ok) throw new Error('TV Scanner failed');
      const d = await r.json();
      const prices = {};
      for (const item of d.data) {
        const key = TICKER_MAP[item.s];
        if (!key || prices[key]) continue;
        const [close, chg, hi, lo] = item.d;
        const dec = (key==='XAU'||key==='OIL'||key==='SILVER') ? 2 : (key==='DXY'||key==='US10Y') ? 3 : 5;
        prices[key] = {
          price: (+close).toFixed(dec),
          change: +(chg||0).toFixed(2),
          high: hi ? (+hi).toFixed(dec) : null,
          low: lo ? (+lo).toFixed(dec) : null
        };
      }
      return res.status(200).json({ ok: true, prices });
    }

    // ── 2. CALENDAR (ForexFactory) ─────────────────────────
    if (type === 'calendar') {
      try {
        const r = await fetchWithTimeout('https://nfs.faireconomy.media/ff_calendar_thisweek.json');
        if(!r.ok) throw new Error('ForexFactory offline');
        const data = await r.json();
        const CountryList = ["USD", "EUR", "GBP", "JPY", "AUD"];
        const events = data.filter(e => {
          const c = (e.currency || e.country || "").toUpperCase();
          const i = (e.impact || "").toLowerCase();
          return CountryList.includes(c) && (i === "high" || i === "medium");
        }).slice(0, 15).map(e => ({
          id: e.id || Math.random(),
          time: e.date || e.time,
          currency: (e.currency || e.country || "USD").toUpperCase(),
          event: e.event || e.title,
          impact: e.impact || "High"
        }));
        return res.status(200).json({ ok: true, events });
      } catch(e) {
        // Fallback or empty
        return res.status(200).json({ ok: true, events: [], note: 'Service temporarily unavailable' });
      }
    }

    // ── 3. SENTIMENT (MyFxBook Proxy) ──────────────────────
    if (type === 'sentiment') {
      const sym = symbol || 'XAUUSD';
      const mfxUrl = `${BASE_MFX}/get-community-outlook.json?session=${session||''}&symbols=${encodeURIComponent(sym)}`;
      const r = await fetchWithTimeout(mfxUrl);
      const d = await r.json();
      return res.status(200).json({ ok: true, outlook: d });
    }

    // ── 4. COT (CFTC Data — can be derived or mocked) ──────
    if (type === 'cot') {
      // Per ora restituiamo dati statici placeholder o derivati
      // Idealmente qui interroghiamo un DB o un'altra API COT
      return res.status(200).json({ 
        ok: true, 
        cot: { net: "+182K", signal: "BULLISH", labels: "Large Speculators" } 
      });
    }

    return res.status(400).json({ ok: false, message: 'Type non supportato' });

  } catch (e) {
    console.error('[market] error:', e.message);
    return res.status(500).json({ ok: false, message: e.message });
  }
}
