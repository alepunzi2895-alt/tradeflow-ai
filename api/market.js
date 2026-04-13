// TradeFlow AI — api/market.js
// Centralized Hub for Market Data: Prices, Sentiment, Calendar, COT

const BASE_MFX = 'https://www.myfxbook.com/api';

const TICKERS = [
  'OANDA:XAUUSD', 'FOREXCOM:XAUUSD', 'PEPPERSTONE:XAUUSD', 'CAPITALCOM:GOLD', 'TVC:GOLD', 
  'FX:XAUUSD', 'SAXO:XAUUSD', 'FPMARKETS:XAUUSD',
  'OANDA:WTICOUSD', 'TVC:USOIL', 'CAPITALCOM:OIL', 'FX:USOIL', 'SAXO:USOILUSD', 'FOREXCOM:WTIUSD',
  'TVC:US10Y', 'TVC:DXY', 
  'OANDA:EURUSD', 'OANDA:GBPUSD', 'FPMARKETS:EURUSD', 'FPMARKETS:GBPUSD',
  'OANDA:XAGUSD', 'FOREXCOM:XAGUSD', 'PEPPERSTONE:XAGUSD', 'CAPITALCOM:SILVER', 'TVC:SILVER', 
  'FX:XAGUSD', 'SAXO:XAGUSD', 'FPMARKETS:XAGUSD'
];

const TICKER_MAP = {
  'OANDA:XAUUSD':'XAU','FOREXCOM:XAUUSD':'XAU','PEPPERSTONE:XAUUSD':'XAU','CAPITALCOM:GOLD':'XAU','TVC:GOLD':'XAU','FX:XAUUSD':'XAU','SAXO:XAUUSD':'XAU','FPMARKETS:XAUUSD':'XAU',
  'OANDA:XAGUSD':'SILVER','FOREXCOM:XAGUSD':'SILVER','PEPPERSTONE:XAGUSD':'SILVER','CAPITALCOM:SILVER':'SILVER','TVC:SILVER':'SILVER','FX:XAGUSD':'SILVER','SAXO:XAGUSD':'SILVER','FPMARKETS:XAGUSD':'SILVER',
  'OANDA:EURUSD':'EURUSD', 'OANDA:GBPUSD':'GBPUSD', 'FPMARKETS:EURUSD':'EURUSD', 'FPMARKETS:GBPUSD':'GBPUSD',
  'TVC:DXY':'DXY', 'TVC:US10Y':'US10Y',
  'OANDA:WTICOUSD':'OIL', 'TVC:USOIL':'OIL', 'CAPITALCOM:OIL':'OIL', 'FX:USOIL':'OIL', 'SAXO:USOILUSD':'OIL', 'FOREXCOM:WTIUSD':'OIL'
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
    // ── 1. PRICES (TradingView Scanner + Yahoo Emergency Fallback) ──
    if (type === 'prices') {
      let prices = {};
      try {
        const body = { 
          symbols: { tickers: TICKERS, query: { types: [] } }, 
          columns: ['close', 'change', 'high', 'low'] 
        };
        const r = await fetchWithTimeout('https://scanner.tradingview.com/global/scan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0' },
          body: JSON.stringify(body)
        });
        if (r.ok) {
          const d = await r.json();
          for (const item of d.data) {
            const key = TICKER_MAP[item.s];
            if (!key || prices[key]) continue;
            const [close, chg, hi, lo] = item.d;
            if (close == null) continue;
            const dec = (key==='XAU'||key==='OIL'||key==='SILVER') ? 2 : (key==='DXY'||key==='US10Y') ? 3 : 5;
            prices[key] = {
              price: (+close).toFixed(dec),
              change: +(chg||0).toFixed(2),
              high: hi ? (+hi).toFixed(dec) : null,
              low: lo ? (+lo).toFixed(dec) : null
            };
          }
        }
      } catch(e) { console.warn('[market] TV Scanner error:', e.message); }

      // EMERGENCY FALLBACK for OIL if still missing or zero
      if (!prices.OIL || +prices.OIL.price === 0) {
        try {
          // Use crude oil futures ticker CL=F from Yahoo
          const yr = await fetchWithTimeout('https://query1.finance.yahoo.com/v8/finance/chart/CL=F?interval=1m&range=1d', { headers: { 'User-Agent': 'Mozilla/5.0' } }, 4000);
          if (yr.ok) {
            const yd = await yr.json();
            const q = yd?.chart?.result?.[0]?.meta;
            if (q && q.regularMarketPrice) {
              const pc = q.chartPreviousClose || q.previousClose || q.regularMarketPrice;
              prices.OIL = {
                price: q.regularMarketPrice.toFixed(2),
                change: +(((q.regularMarketPrice - pc)/pc)*100).toFixed(2),
                high: (q.regularMarketDayHigh || q.regularMarketPrice).toFixed(2),
                low: (q.regularMarketDayLow || q.regularMarketPrice).toFixed(2)
              };
            }
          }
        } catch(e) { console.warn('[market] Oil Yahoo fallback error:', e.message); }
      }

      // Final check for mandatory keys
      if (!prices.XAU) throw new Error('Dati Oro non disponibili');
      
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
        return res.status(200).json({ ok: true, events: [], note: 'Service temporarily unavailable' });
      }
    }

    // ── 3. SENTIMENT (MyFxBook Proxy + Mult-Asset Simulation) ──
    if (type === 'sentiment') {
      const sym = (symbol || 'XAUUSD').toUpperCase();
      try {
        const mfxUrl = `${BASE_MFX}/get-community-outlook.json?session=${session||''}&symbols=${encodeURIComponent(sym)}`;
        const r = await fetchWithTimeout(mfxUrl);
        const d = await r.json();
        
        if (d && d.symbols && d.symbols.length > 0) {
          return res.status(200).json({ ok: true, outlook: d, source: 'myfxbook' });
        }
        throw new Error('Sentiment service busy');
      } catch (e) {
        // Smart Simulation: Always return both XAU and XAG to prevent dashes in UI
        return res.status(200).json({ 
          ok: true, 
          source: 'simulation',
          outlook: {
            symbols: [
              { name: 'XAUUSD', shortPercentage: 47, longPercentage: 53, shortVolume: 470, longVolume: 530, longPositions: 1000, shortPositions: 940 },
              { name: 'XAGUSD', shortPercentage: 42, longPercentage: 58, shortVolume: 420, longVolume: 580, longPositions: 500, shortPositions: 380 }
            ]
          }
        });
      }
    }

    // ── 4. COT (CFTC Data — Placeholder) ───────────────────
    if (type === 'cot') {
      return res.status(200).json({ 
        ok: true, 
        cot: { 
          net: "+182K", 
          signal: "BULLISH", 
          labels: "Large Speculators",
          last_updated: "Venerdì, 10 Aprile 2024"
        } 
      });
    }

    return res.status(400).json({ ok: false, message: 'Type non supportato' });

  } catch (e) {
    console.error('[market] error:', e.message);
    return res.status(500).json({ ok: false, message: e.message });
  }
}
