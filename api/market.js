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
      try {
        const q = await yahooQuote(sym);
        return res.status(200).json({ ok:true, currency:cur, rate:q.price, timestamp:new Date().toISOString() });
      } catch(e) {
        return res.status(200).json({ ok:false, currency:cur, rate:null, error:e.message });
      }
    }

    // ── PRICES ─────────────────────────────────────────────
    if (type === "prices") {
      // Symbols: XAU, DXY, EURUSD, GBPUSD, USDJPY, OIL
      const symbolMap = [
        { key:"XAU",    sym:"XAUUSD=X"    }, // spot gold
        { key:"DXY",    sym:"DX-Y.NYB"    },
        { key:"EURUSD", sym:"EURUSD=X"    },
        { key:"GBPUSD", sym:"GBPUSD=X"    },
        { key:"OIL",    sym:"CL=F"        },
        { key:"SILVER", sym:"XAGUSD=X"    }, // Silver spot for Gold/Silver Ratio
        { key:"US10Y",  sym:"^TNX"        }, // US 10Y Treasury Yield
      ];

      const results = await Promise.allSettled(
        symbolMap.map(s => yahooQuote(s.sym).then(q => ({ key:s.sym, data:q })))
      );

      const prices = {};
      symbolMap.forEach((s, i) => {
        const r = results[i];
        if (r.status === "fulfilled" && r.value?.data) {
          const d = r.value.data;
          const decimals = s.key==="USDJPY" ? 3 : s.key==="XAU"||s.key==="OIL"||s.key==="SILVER" ? 2 : s.key==="US10Y" ? 3 : 5;
          prices[s.key] = {
            price: d.price.toFixed(decimals),
            change: d.change,
            high: d.high?.toFixed(decimals),
            low: d.low?.toFixed(decimals),
          };
        }
      });

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

      return res.status(200).json({ ok:true, prices, timestamp:new Date().toISOString() });
    }

    // ── CALENDAR ──────────────────────────────────────────
    if (type === "calendar") {
      let events = [];

      // Try ForexFactory this week
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
      // Retail traders typically chase: they buy dips and sell rallies
      // So: XAU down 5d → retail likely over-long (contrarian = bullish signal)
      //     XAU up 5d   → retail likely over-short (contrarian = bearish signal)
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
    // Latest Commitment of Traders: Large Speculators net position on Gold
    if (type === "cot") {
      try{
        // CFTC publishes weekly CSV — Gold COMEX code: 088691
        // Alternative: use a proxy that parses COT (quandl deprecated, use cotdata)
        // We use a parsed version from barchart or investing.com approach
        // Primary: fetch from CFTC legacy CSV
        const cotUrl = "https://www.cftc.gov/dea/futures/other_sf.htm";
        // The CSV is at: https://www.cftc.gov/sites/default/files/files/dea/history/fut_disagg_txt_2025.zip
        // Too complex to parse in serverless — use Yahoo Finance TNX + calculated signal instead
        
        // Practical approach: derive COT signal from price action + open interest
        // Real COT: fetch from cached GitHub file updated weekly
        const cotGH = await fetchWithTimeout(
          `https://raw.githubusercontent.com/${process.env.GITHUB_OWNER}/${process.env.GITHUB_REPO}/main/data/cot_data.json`,
          {headers:{"Authorization":`Bearer ${process.env.GITHUB_TOKEN}`}}, 5000
        );
        if(cotGH.ok){
          const cotData = await cotGH.json();
          return res.status(200).json({ok:true, source:"github", ...cotData, timestamp:new Date().toISOString()});
        }
      }catch(e){console.log("COT fetch failed:", e.message);}
      
      // Fallback: return null with instructions
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
