import {fetchQuotes} from '../lib/market-quotes.js';
import {instrument} from '../lib/instruments.js';
// api/analysis.js — Super-Consolidated Analysis Engine (Restored & Robust)
// Handles: Market Data (Prices, Correlation, G/S Ratio), Sentiment, Economic Calendar, COT, Indicators (MACD, ADX, CCI)

// Cache in-memory (best-effort, sopravvive solo tra invocazioni Vercel "warm" —
// stesso pattern di api/webhook.js::memCache). Riduce le chiamate ripetute verso
// nfs.faireconomy.media, l'unica fonte calendario ancora viva e rate-limited
// (429 verificato 2026-07-09) — senza cache, refresh frequenti della dashboard
// da più utenti/tab possono da soli far scattare il rate limit.
let calCache = null;
let calCacheTs = 0;
const CAL_CACHE_TTL_MS = 5 * 60 * 1000; // 5 min

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

  async function yahooQuote(symbol) {
    try {
      const r = await fetchT(`https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1m&range=1d`, { headers: { "User-Agent": "Mozilla/5.0" } }, 3500);
      const d = await r.json();
      const meta = d?.chart?.result?.[0]?.meta;
      if (!meta) return null;
      const price = meta.regularMarketPrice;
      const prev = meta.chartPreviousClose || meta.previousClose || price;
      return { price, change: parseFloat(((price - prev) / prev * 100).toFixed(2)), high: meta.regularMarketDayHigh, low: meta.regularMarketDayLow };
    } catch(e) { return null; }
  }


  if(type==='fx'){
    const symbols={EUR:'EURUSD=X',GBP:'GBPUSD=X',CHF:'CHF=X',JPY:'JPY=X'};
    const currency=String(req.query.currency||'USD').toUpperCase();
    if(currency==='USD')return res.status(200).json({ok:true,rate:1});
    if(!symbols[currency])return res.status(400).json({ok:false,error:'Valuta non supportata'});
    const q=await yahooQuote(symbols[currency]);
    return res.status(q?.price?200:502).json(q?.price?{ok:true,rate:q.price,source:'yahoo'}:{ok:false,error:'Cambio non disponibile'});
  }

  // ── BRANCH: MARKET DATA & SENTIMENT ───────────────────────────────────────
  if (type === 'market' || type === 'prices' || type === 'sentiment' || type === 'calendar' || type === 'cot') {
    
    // ── PRICES ──
    if (type === "prices") {
      res.setHeader('Cache-Control','no-store');
      const snapshot=await fetchQuotes();
      return res.status(snapshot.ok?200:503).json(snapshot);
    }

    // ── SENTIMENT ── spostato in api/myfxbook.js (action 'sentiment', 2026-09-24): la sessione
    // MyFxBook vive sul server per utente con rinnovo automatico, e non passa più nell'URL.
    if (type === "sentiment") {
      return res.status(410).json({ok:false, error:'Usa /api/myfxbook action sentiment'});
    }

    // ── CALENDAR ──
    if (type === "calendar") {
      res.setHeader("Cache-Control", "public, s-maxage=300, stale-while-revalidate=600");
      // Cache-hit: risparmia la fetch esterna (vedi CAL_CACHE_TTL_MS in cima al file).
      if (calCache && (Date.now() - calCacheTs) < CAL_CACHE_TTL_MS) {
        return res.status(200).json({ ok:true, events: calCache, cached: true, timestamp: new Date().toISOString() });
      }

      // Verificato in diretta 2026-07-09: cdn-nfs.faireconomy.media non risolve più (DNS
      // morto), forexfactory.com/ff_calendar_thisweek.json blocca con 403 (bot detection),
      // nfs.faireconomy.media/ff_calendar_nextweek.json risponde 404 (endpoint ritirato).
      // L'UNICA fonte ancora viva è nfs.faireconomy.media/ff_calendar_thisweek.json — ma va
      // rispettata: bombardarla con richieste concorrenti (incluso il suo stesso "nextweek")
      // fa scattare un 429 anche su questa. Niente raffica parallela: un solo URL, con un
      // retry breve per assorbire i 429/blip transitori (motivo originale per cui la card
      // restava vuota — vedi directives/07_self_learning_log.md 2026-07-09).
      const CAL_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json";
      let raw = null;
      for (let attempt = 0; attempt < 1 && !raw; attempt++) {
        if (attempt > 0) await new Promise(r => setTimeout(r, 900));
        try {
          const r = await fetchT(CAL_URL, { headers:{"User-Agent":"Mozilla/5.0"} }, 5000);
          if (r.ok) raw = await r.json();
        } catch(e) {}
      }

      let events = [];
      if (Array.isArray(raw)) {
        const important = raw.filter(e => {
          const country = (e.currency || e.country || "").toUpperCase();
          // + CHF/CAD/NZD per le coppie major del registro strumenti (2026-09-24)
          return ["USD","EUR","GBP","JPY","AUD","CHF","CAD","NZD"].includes(country) && (e.impact === "High" || e.impact === "Medium");
        });
        events = important.map(e => ({
          id: e.id || Math.random().toString(36).substr(2, 9),
          time: String(e.date || e.time || '').replace(/^(\d{2})-(\d{2})-(\d{4})(T.*)$/, '$3-$1-$2$4'),
          currency: e.currency || e.country || "USD",
          event: e.event || e.title || "Economic Event",
          impact: e.impact || "High", forecast:e.forecast ?? "", previous:e.previous ?? "", actual:e.actual ?? ""
        }));
      }

      if (!Array.isArray(raw)) {
        if(calCache) return res.status(200).json({ok:true,events:calCache,stale:true,timestamp:new Date(calCacheTs).toISOString()});
        res.setHeader('Cache-Control','no-store');
        return res.status(503).json({ok:false,error:'Calendario temporaneamente non disponibile'});
      }
      events=events.filter(e=>Number.isFinite(Date.parse(e.time))).sort((a,b)=>Date.parse(a.time)-Date.parse(b.time));
      // Cache sempre il risultato — anche vuoto, ma solo per pochi secondi (non i 5 min
      // pieni) così un blip transitorio non "congela" la card vuota a lungo, mentre un
      // fetch riuscito viene servito dalla cache per la TTL intera.
      calCache = events;
      calCacheTs = events.length ? Date.now() : (Date.now() - CAL_CACHE_TTL_MS + 20000);

      // If fetch fails, do not provide fake mock events, just an empty list.
      return res.status(200).json({ ok:true, events, timestamp: new Date().toISOString() });
    }

    // ── COT ──
    if (type === "cot") {
      try {
        const r = await fetchT(`https://raw.githubusercontent.com/${process.env.GITHUB_OWNER}/${process.env.GITHUB_REPO}/main/data/cot_data.json`, { headers:{"Authorization":`Bearer ${process.env.GITHUB_TOKEN}`} });
        const d = await r.json();
        return res.status(200).json({ ok:true, ...d });
      } catch(e) { return res.status(200).json({ ok:false, error: "COT unavailable" }); }
    }
  }

  // ── BRANCH: INDICATORS ────────────────────────────────────────────────────
  if (type === 'indicators') {
    // Ticker dal registro strumenti (public/instruments.json). Prima un asset sconosciuto
    // ricadeva in silenzio sui ticker dell'oro (dati XAU mostrati sotto un altro nome).
    const inst = instrument(asset);
    if (!inst) return res.status(400).json({ ok:false, error:`Strumento non supportato: ${asset}` });
    const tvTicker = inst.quotes[0];
    const resolution = tf === '1d' ? '' : '|60';
    
    // Initialize defaults to prevent frontend display issues (invisible headers)
    const response = { 
      ok: true, timeframe: tf, timestamp: new Date().toISOString(),
      adx: null, cci: null, macd: null
    };

    // 1. MACD from TV Scanner
    try {
      const body = { symbols: { tickers: [tvTicker], query: { types: [] } }, columns: ['close'+resolution, 'MACD.macd'+resolution, 'MACD.signal'+resolution] };
      const r = await fetchT('https://scanner.tradingview.com/global/scan', { method: 'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) }, 3500);
      const d = await r.json();
      const item = d.data?.[0]?.d;
      if (item && Number.isFinite(item[1]) && Number.isFinite(item[2])) {
        response.last_close = item[0];
        // toPrecision: sul forex MACD e istogramma sono dell'ordine di 1e-4 (toFixed(4) li azzerava)
        response.macd = { macd: +item[1].toPrecision(6), signal: +item[2].toPrecision(6), histogram: +(item[1]-item[2]).toPrecision(6), cross: item[1] > item[2] ? 'above':'below' };
      }
    } catch(e) {}

    // 2. Fetch candles for custom ADX/CCI calculation
    let candles = [];
    try {
      // Use GC=F/SI=F for better H1 coverage on Yahoo
      const yahooSym = ({ XAU:'GC=F', XAG:'SI=F', US30:'^DJI' })[inst.id] || inst.yahoo[0];
      response.candle_source='Yahoo · '+yahooSym;
      const url = `https://query2.finance.yahoo.com/v8/finance/chart/${yahooSym}?interval=${tf==='1d'?'1d':'1h'}&range=60d`;
      const cr = await fetchT(url, { headers: { "User-Agent": "Mozilla/5.0" } }, 3500);
      const cd = await cr.json();
      const rs = cd?.chart?.result?.[0];
      if (rs?.timestamp) {
        const q = rs.indicators?.quote?.[0];
        rs.timestamp.forEach((t, i) => {
          if (q.close[i] != null && q.high[i] != null && q.low[i] != null) 
            candles.push({ t, h: q.high[i], l: q.low[i], c: q.close[i] });
        });
      }
    } catch(e) {}

    if (candles.length > 50) {
      const H = candles.map(x => x.h), L = candles.map(x => x.l), C = candles.map(x => x.c);
      
      // ── ADX(10) Exact (from ADX and DI for v4) ──
      const ADX_P = 10;
      let adx = 20, diP = 20, diM = 20;
      try {
        const n = C.length;
        if (n > ADX_P) {
          const TR=new Array(n).fill(0),DMP=new Array(n).fill(0),DMM=new Array(n).fill(0);
          for(let i=1;i<n;i++){
            TR[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));
            const upMove=H[i]-H[i-1], downMove=L[i-1]-L[i];
            DMP[i]=(upMove>downMove&&upMove>0)?upMove:0;
            DMM[i]=(downMove>upMove&&downMove>0)?downMove:0;
          }
          const sTR=new Array(n).fill(0),sDMP=new Array(n).fill(0),sDMM=new Array(n).fill(0);
          for(let i=1;i<n;i++){
            sTR[i]=sTR[i-1]-sTR[i-1]/ADX_P+TR[i];
            sDMP[i]=sDMP[i-1]-sDMP[i-1]/ADX_P+DMP[i];
            sDMM[i]=sDMM[i-1]-sDMM[i-1]/ADX_P+DMM[i];
          }
          const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
          const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
          const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
          
          const ADX=new Array(n).fill(null);
          for(let i=ADX_P-1;i<n;i++){
            let sum=0;for(let j=0;j<ADX_P;j++)sum+=(DX[i-j]||0);
            ADX[i]=sum/ADX_P;
          }
          adx = ADX[n-1] ?? 0;
          diP = DIP[n-1] ?? 0;
          diM = DIM[n-1] ?? 0;
        }
      } catch(e) {}
      response.adx = { adx: +adx.toFixed(2), di_plus: +diP.toFixed(1), di_minus: +diM.toFixed(1), trending: adx > 20 };

      // ── CCI_S Exact ──
      try {
        const n = C.length;
        if (n > 120) {
          const CCI_P=50, STOCH_P=50, SK=8, SD=8;
          const cci=new Array(n).fill(null);
          for(let i=CCI_P-1;i<n;i++){
            const sl=C.slice(i-CCI_P+1,i+1);
            const mn=sl.reduce((a,b)=>a+b,0)/CCI_P;
            const md=sl.reduce((a,b)=>a+Math.abs(b-mn),0)/CCI_P;
            cci[i]=md===0?0:(C[i]-mn)/(0.015*md);
          }
          const stk=new Array(n).fill(null);
          for(let i=CCI_P+STOCH_P-2;i<n;i++){
            if(cci[i]==null)continue;
            let lv=Infinity, hv=-Infinity;
            for(let j=i-STOCH_P+1;j<=i;j++){if(cci[j]!=null){lv=Math.min(lv,cci[j]);hv=Math.max(hv,cci[j]);}}
            stk[i]=(hv-lv)===0?50:((cci[i]-lv)/(hv-lv))*100;
          }
          const stk_k=new Array(n).fill(null);
          for(let i=SK-1;i<n;i++){
            const sl=stk.slice(i-SK+1,i+1);
            if(!sl.some(v=>v==null)) stk_k[i]=sl.reduce((a,b)=>a+b,0)/SK;
          }
          const stk_d=new Array(n).fill(null);
          for(let i=SD-1;i<n;i++){
            const sl=stk_k.slice(i-SD+1,i+1);
            if(!sl.some(v=>v==null)) stk_d[i]=sl.reduce((a,b)=>a+b,0)/SD;
          }
          const cci_s = stk_d[n-1] ?? 50;
          response.cci = { value: +cci_s.toFixed(2), zone: cci_s > 75 ? 'overbought' : cci_s < 25 ? 'oversold' : 'neutral' };
        } else {
          // fallback to simple if not enough candles
          const last50 = C.slice(-50);
          const mean = last50.reduce((a, b) => a + b, 0) / 50;
          const mdev = last50.reduce((a, b) => a + Math.abs(b - mean), 0) / 50;
          const cci = mdev === 0 ? 0 : (C.at(-1) - mean) / (0.015 * mdev);
          const cci_s = ( (cci + 200) / 400 ) * 100;
          response.cci = { value: +cci_s.toFixed(2), zone: cci_s > 75 ? 'overbought' : cci_s < 25 ? 'oversold' : 'neutral' };
        }
      } catch(e) {}
    }

    response.ok=Boolean(response.macd||response.adx||response.cci);
    return res.status(200).json(response);
  }

  // ── BRANCH: COT UPDATE ────────────────────────────────────────────────────
  if (type === 'cot-update') {
    return res.status(200).json({ ok:true, message: "COT logic active" });
  }

  return res.status(400).json({ error: "Unknown analysis type" });
}
