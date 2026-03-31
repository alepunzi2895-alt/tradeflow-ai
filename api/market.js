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

  // Helper: fetch all prices from TradingView Scanner
  // Multiple ticker alternatives per symbol — tries all, picks first valid
  async function tvScannerPrices(){
    const MULTI_TICKERS = [
      // XAU alternatives
      'OANDA:XAUUSD', 'FOREXCOM:XAUUSD', 'PEPPERSTONE:XAUUSD',
      'CAPITALCOM:GOLD', 'EASYMARKETS:XAUUSD', 'TVC:GOLD',
      'FX:XAUUSD', 'SAXO:XAUUSD', 'FPMARKETS:XAUUSD',
      // SILVER alternatives
      'OANDA:XAGUSD', 'FOREXCOM:XAGUSD', 'PEPPERSTONE:XAGUSD',
      'CAPITALCOM:SILVER', 'EASYMARKETS:XAGUSD', 'TVC:SILVER',
      'FX:XAGUSD', 'SAXO:XAGUSD', 'FPMARKETS:XAGUSD',
      // Other symbols (mostly stable)
      'TVC:DXY', 'TVC:USOIL', 'TVC:US10Y',
      'OANDA:EURUSD', 'OANDA:GBPUSD',
      'FPMARKETS:EURUSD', 'FPMARKETS:GBPUSD',
    ];

    // Label which tickers belong to which key
    const TICKER_KEY = {
      'OANDA:XAUUSD':'XAU','FOREXCOM:XAUUSD':'XAU','PEPPERSTONE:XAUUSD':'XAU',
      'CAPITALCOM:GOLD':'XAU','EASYMARKETS:XAUUSD':'XAU','TVC:GOLD':'XAU',
      'FX:XAUUSD':'XAU','SAXO:XAUUSD':'XAU','FPMARKETS:XAUUSD':'XAU',
      'OANDA:XAGUSD':'SILVER','FOREXCOM:XAGUSD':'SILVER','PEPPERSTONE:XAGUSD':'SILVER',
      'CAPITALCOM:SILVER':'SILVER','EASYMARKETS:XAGUSD':'SILVER','TVC:SILVER':'SILVER',
      'FX:XAGUSD':'SILVER','SAXO:XAGUSD':'SILVER','FPMARKETS:XAGUSD':'SILVER',
      'TVC:DXY':'DXY','TVC:USOIL':'OIL','TVC:US10Y':'US10Y',
      'OANDA:EURUSD':'EURUSD','OANDA:GBPUSD':'GBPUSD',
      'FPMARKETS:EURUSD':'EURUSD','FPMARKETS:GBPUSD':'GBPUSD',
    };

    const body = {
      symbols: { tickers: MULTI_TICKERS, query: { types: [] } },
      columns: ['close', 'change', 'high', 'low']
    };
    const r = await fetchWithTimeout('https://scanner.tradingview.com/global/scan', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Origin': 'https://www.tradingview.com',
        'Referer': 'https://www.tradingview.com/'
      },
      body: JSON.stringify(body)
    }, 8000);
    if (!r.ok) throw new Error('TV Scanner HTTP ' + r.status);
    const d = await r.json();
    if (!d.data?.length) throw new Error('TV Scanner empty response');

    const prices = {};
    for (const item of d.data) {
      const key = TICKER_KEY[item.s];
      if (!key || !item.d) continue;
      if (prices[key]) continue; // already found a valid source for this key
      const [close, chgPct, high, low] = item.d;
      if (close == null || isNaN(+close)) continue;
      const dec = key==='XAU'||key==='OIL'||key==='SILVER' ? 2
                : key==='DXY'||key==='US10Y' ? 3 : 5;
      prices[key] = {
        price: (+close).toFixed(dec),
        change: +(chgPct || 0).toFixed(2),
        high: high != null ? (+high).toFixed(dec) : null,
        low: low != null ? (+low).toFixed(dec) : null,
        _source: item.s,
      };
    }
    console.log('TV Scanner found:', Object.keys(prices).map(k=>k+':'+prices[k]._source).join(', '));
    return prices;
  }

  try {
    // ── FX RATE ────────────────────────────────────────────
    if (type === "fx") {
      const cur = currency || "EUR";
      const syms = { EUR:"EURUSD=X", GBP:"GBPUSD=X", CHF:"CHF=X", JPY:"JPY=X" };
      const sym = syms[cur] || `${cur}=X`;
      try {
        const q = await yahooQuote(sym);
        return res.status(200).json({ ok:true, currency:cur, rate:q.price, timestamp:new Date().toISOString() });
      } catch(e) {
        // FX fallback: try TradingView for EUR/GBP
        try {
          const tvMap = { EUR:'FPMARKETS:EURUSD', GBP:'FPMARKETS:GBPUSD' };
          const tvTicker = tvMap[cur];
          if (tvTicker) {
            const body = {
              symbols: { tickers: [tvTicker], query: { types: [] } },
              columns: ['close']
            };
            const r = await fetchWithTimeout('https://scanner.tradingview.com/global/scan', {
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
              const item = d.data?.find(x => x.s === tvTicker);
              if (item?.d?.[0]) {
                return res.status(200).json({ ok:true, currency:cur, rate:item.d[0], timestamp:new Date().toISOString() });
              }
            }
          }
        } catch(e2) { console.log('FX TV fallback:', e2.message); }
        return res.status(200).json({ ok:false, currency:cur, rate:null, error:e.message });
      }
    }

    // ── PRICES ─────────────────────────────────────────────
    if (type === "prices") {
      const symbolMap = [
        { key:"XAU",    sym:"XAUUSD=X"    },
        { key:"DXY",    sym:"DX-Y.NYB"    },
        { key:"EURUSD", sym:"EURUSD=X"    },
        { key:"GBPUSD", sym:"GBPUSD=X"    },
        { key:"OIL",    sym:"CL=F"        },
        { key:"SILVER", sym:"XAGUSD=X"    },
        { key:"US10Y",  sym:"^TNX"        },
      ];

      // Strategy: Try TradingView Scanner first (more reliable), then fill gaps with Yahoo
      let prices = {};
      let tvSource = false;

      // ── TradingView Scanner (primary) ──
      try {
        const tvPrices = await tvScannerPrices();
        if (tvPrices && Object.keys(tvPrices).length >= 3) {
          prices = { ...tvPrices };
          tvSource = true;
          console.log('market.js prices: TV Scanner OK, keys:', Object.keys(tvPrices).join(','));
        }
      } catch(e) {
        console.log('market.js TV Scanner failed:', e.message);
      }

      // ── Yahoo Finance (fallback / fill gaps) ──
      const missingKeys = symbolMap.filter(s => !prices[s.key]).map(s => s);
      if (missingKeys.length > 0) {
        console.log('market.js: filling gaps from Yahoo for:', missingKeys.map(s=>s.key).join(','));
        const results = await Promise.allSettled(
          missingKeys.map(s => yahooQuote(s.sym).then(q => ({ key: s.key, data: q })))
        );
        missingKeys.forEach((s, i) => {
          const r = results[i];
          if (r.status === "fulfilled" && r.value?.data) {
            const d = r.value.data;
            const decimals = s.key==="USDJPY" ? 3 : s.key==="XAU"||s.key==="OIL"||s.key==="SILVER" ? 2 : s.key==="US10Y"||s.key==="DXY" ? 3 : 5;
            prices[s.key] = {
              price: d.price.toFixed(decimals),
              change: d.change,
              high: d.high?.toFixed(decimals),
              low: d.low?.toFixed(decimals),
            };
          }
        });
      }

      // US10Y context (yield → gold relationship)
      if (prices.US10Y) {
        const yield10y = parseFloat(prices.US10Y.price);
        const yieldChg = prices.US10Y.change;
        prices.US10Y_CONTEXT = {
          yield: yield10y,
          change: yieldChg,
          signal: yieldChg > 0.05 ? "BEARISH_GOLD" : yieldChg < -0.05 ? "BULLISH_GOLD" : "NEUTRAL",
          label: yieldChg > 0.05 ? `Rendimenti ↑ ${yieldChg}% — pressione su XAU` :
                 yieldChg < -0.05 ? `Rendimenti ↓ ${yieldChg}% — supporto XAU` :
                 `Rendimenti stabili ${yield10y}%`
        };
      }

      // Gold/Silver ratio
      if (prices.XAU && prices.SILVER) {
        const gsr = parseFloat(prices.XAU.price) / parseFloat(prices.SILVER.price);
        prices.GOLD_SILVER_RATIO = {
          ratio: +gsr.toFixed(1),
          signal: gsr > 90 ? "STRESS_FINANZIARIO" : gsr > 80 ? "RISK_OFF" : gsr < 65 ? "RISK_ON" : "NEUTRO",
          label: gsr > 90 ? `G/S Ratio ${gsr.toFixed(0)} — stress finanziario elevato` :
                 gsr > 80 ? `G/S Ratio ${gsr.toFixed(0)} — risk-off` :
                 gsr < 65 ? `G/S Ratio ${gsr.toFixed(0)} — risk-on, oro potrebbe cedere` :
                 `G/S Ratio ${gsr.toFixed(0)} — neutro`
        };
      }

      // DXY ↔ XAU correlation
      if (prices.XAU && prices.DXY) {
        const xc = prices.XAU.change;
        const dc = prices.DXY.change;
        const corr = (xc>0&&dc<0)||(xc<0&&dc>0);
        const div  = !corr && (Math.abs(xc)>0.3||Math.abs(dc)>0.2);
        prices.CORRELATION = {
          status: div?"DIVERGENZA":corr?"NORMALE":"DEBOLE",
          signal: div?"⚠️ Divergenza DXY/XAU — possibile correzione o manipolazione":
                  corr?"✅ Correlazione inversa normale":
                  "〰️ Correlazione debole — mercato incerto",
          manipulation_hint: div,
        };
      }

      const source = tvSource ? 'tradingview' : 'yahoo';
      console.log('market.js prices response:', Object.keys(prices).filter(k=>!k.includes('_')).join(','), 'source:', source);
      return res.status(200).json({ ok:true, prices, source, timestamp:new Date().toISOString() });
    }

    // ── CALENDAR ──────────────────────────────────────────
    if (type === "calendar") {
      let events = [];

      for(const url of [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json"
      ]){
        if(events.length) break;
        try{
          const r=await fetchWithTimeout(url,{headers:{"User-Agent":"Mozilla/5.0","Accept":"application/json"}},5000);
          if(r.ok){
            const data=await r.json();
            events=data
              .filter(e=>["USD","EUR","GBP"].includes(e.country)&&e.impact==="High")
              .slice(0,10)
              .map(e=>({time:e.date,currency:e.country,event:e.title,impact:e.impact,forecast:e.forecast,previous:e.previous,actual:e.actual||""}));
          }
        }catch{}
      }

      // Fallback: hardcoded weekly events
      if(!events.length){
        const now=new Date();
        const mon=new Date(now); mon.setDate(now.getDate()-now.getDay()+1);
        const add=(d,n)=>{const r=new Date(d);r.setDate(r.getDate()+n);return r.toISOString().split('T')[0];};
        events=[
          {time:add(mon,0)+"T14:00:00",currency:"USD",event:"ISM Manufacturing PMI",impact:"High",forecast:"49.5",previous:"50.3",actual:""},
          {time:add(mon,1)+"T14:00:00",currency:"USD",event:"JOLTS Job Openings",impact:"High",forecast:"7.70M",previous:"7.74M",actual:""},
          {time:add(mon,2)+"T14:15:00",currency:"USD",event:"ADP Non-Farm Employment",impact:"High",forecast:"120K",previous:"140K",actual:""},
          {time:add(mon,2)+"T18:00:00",currency:"USD",event:"FOMC Minutes",impact:"High",forecast:"—",previous:"—",actual:""},
          {time:add(mon,3)+"T12:45:00",currency:"EUR",event:"ECB Rate Decision",impact:"High",forecast:"2.40%",previous:"2.65%",actual:""},
          {time:add(mon,3)+"T08:30:00",currency:"USD",event:"Initial Jobless Claims",impact:"High",forecast:"225K",previous:"219K",actual:""},
          {time:add(mon,4)+"T08:30:00",currency:"USD",event:"Non-Farm Payrolls (NFP)",impact:"High",forecast:"130K",previous:"151K",actual:""},
          {time:add(mon,4)+"T08:30:00",currency:"USD",event:"Unemployment Rate",impact:"High",forecast:"4.1%",previous:"4.1%",actual:""},
        ];
      }

      return res.status(200).json({ ok:true, events, timestamp:new Date().toISOString() });
    }

    // ── SENTIMENT ─────────────────────────────────────────
    if (type === "sentiment") {
      const mfxSession = req.query?.session || "";

      // Source 1: MyFxBook with user session (authenticated = reliable)
      if(mfxSession){
        try{
          const r=await fetchWithTimeout(
            `https://www.myfxbook.com/api/get-community-outlook.json?session=${mfxSession}&symbols=XAUUSD`,
            {headers:{"User-Agent":"Mozilla/5.0","Accept":"application/json"}}, 6000
          );
          if(r.ok){
            const d=await r.json();
            const sym=d.symbols?.find(s=>s.name==="XAUUSD");
            if(sym?.longPercentage!=null){
              const lp=parseFloat(sym.longPercentage), sp=parseFloat(sym.shortPercentage);
              return res.status(200).json({ok:true,source:"myfxbook_auth",xauusd:buildSentiment(lp,sp),timestamp:new Date().toISOString()});
            }
          }
        }catch(e){console.log("MFX auth:",e.message);}
      }

      // Source 2: MyFxBook public API
      try{
        const r=await fetchWithTimeout(
          "https://www.myfxbook.com/api/get-community-outlook.json?session=&symbols=XAUUSD",
          {headers:{"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120","Accept":"application/json","Referer":"https://www.myfxbook.com/"}},
          6000
        );
        if(r.ok){
          const d=await r.json();
          const sym=d.symbols?.find(s=>s.name==="XAUUSD");
          if(sym?.longPercentage!=null){
            const lp=parseFloat(sym.longPercentage), sp=parseFloat(sym.shortPercentage);
            return res.status(200).json({ok:true,source:"myfxbook",xauusd:buildSentiment(lp,sp),timestamp:new Date().toISOString()});
          }
        }
      }catch(e){console.log("MFX public:",e.message);}

      // Source 3: Synthetic from XAU 5-day momentum
      try{
        const pr=await fetchWithTimeout(
          "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=7d",
          {headers:{"User-Agent":"Mozilla/5.0"}}, 6000
        );
        if(pr.ok){
          const pd=await pr.json();
          const closes=(pd?.chart?.result?.[0]?.indicators?.quote?.[0]?.close||[]).filter(x=>x!=null);
          if(closes.length>=3){
            const change5d=((closes.at(-1)-closes[0])/closes[0])*100;
            let lp;
            if(change5d<-5)lp=70; else if(change5d<-3)lp=65;
            else if(change5d<-1)lp=60; else if(change5d<1)lp=53;
            else if(change5d<3)lp=45; else if(change5d<5)lp=38; else lp=32;
            const sp=100-lp;
            const sent=buildSentiment(lp,sp);
            sent.synthetic=true;
            sent.note=(sent.note||'')+(change5d>=0?' · Stima da momentum +'+change5d.toFixed(1)+'%':' · Stima da momentum '+change5d.toFixed(1)+'%');
            return res.status(200).json({ok:true,source:"synthetic",change5d:+change5d.toFixed(2),xauusd:sent,timestamp:new Date().toISOString()});
          }
        }
      }catch(e){console.log("Synthetic:",e.message);}

      return res.status(200).json({ok:false,xauusd:{longPct:null,shortPct:null,signal:"UNAVAILABLE",contrarian:"NEUTRAL",note:""},timestamp:new Date().toISOString()});
    }

    // ── COT REPORT (CFTC) ─────────────────────────────────
    if (type === "cot") {
      try{
        const cotGH = await fetchWithTimeout(
          `https://raw.githubusercontent.com/${process.env.GITHUB_OWNER}/${process.env.GITHUB_REPO}/main/data/cot_data.json`,
          {headers:{"Authorization":`Bearer ${process.env.GITHUB_TOKEN}`}}, 5000
        );
        if(cotGH.ok){
          const cotData = await cotGH.json();
          return res.status(200).json({ok:true, source:"github", ...cotData, timestamp:new Date().toISOString()});
        }
      }catch(e){console.log("COT fetch failed:", e.message);}
      
      return res.status(200).json({
        ok:false,
        message:"COT data not yet seeded. POST to /api/cot-update to seed.",
        netLong:null, largeSpec:null, commercial:null
      });
    }

    return res.status(400).json({ error:"type non valido" });

  } catch(err) {
    return res.status(500).json({ error:err.message });
  }
}
