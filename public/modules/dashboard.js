// TradeFlow AI — modules/dashboard.js

// ── DASHBOARD ──────────────────────────────────────────
// Fast refresh: prices only (called every 2s)
// Fetch with timeout helper
async function fetchJSON(url, timeoutMs=6000){
  const ctrl=new AbortController();
  const tid=setTimeout(()=>ctrl.abort(), timeoutMs);
  try{
    const r=await fetch(url,{signal:ctrl.signal});
    clearTimeout(tid);
    const txt=await r.text();
    if(!txt||!txt.trim()||txt.trim()[0]==='<'||txt.trim()[0]==='!')return null;
    return JSON.parse(txt);
  }catch(e){
    clearTimeout(tid);
    return null;
  }
}

// IMMEDIATE render with placeholder prices to unblock UI
function renderPlaceholders(){
  ['p-xau','p-dxy','p-eur','p-gbp','p-oil'].forEach(id=>{
    const el=document.getElementById(id);
    if(el&&el.textContent==='—')el.textContent='...';
  });
}

// ── TradingView Scanner — real-time prices from browser ──
// FP Markets for XAU (exact broker match), TVC for indices
const TV_SYMS = {
  XAU:    'FPMARKETS:XAUUSD',  // FP Markets XAU — same as your chart
  DXY:    'TVC:DXY',
  EURUSD: 'FPMARKETS:EURUSD',
  GBPUSD: 'FPMARKETS:GBPUSD',
  OIL:    'TVC:USOIL',
  US10Y:  'TVC:US10Y',
  SILVER: 'FPMARKETS:XAGUSD',
};
// Reverse lookup: full TV symbol → our key
const TV_REV = Object.fromEntries(Object.entries(TV_SYMS).map(([k,v])=>[v,k]));

async function fetchTVPrices(){
  const body = {
    symbols: { tickers: Object.values(TV_SYMS), query: { types: [] } },
    columns: ['close','change','high','low']
  };
  const ctrl = new AbortController();
  const tid = setTimeout(()=>ctrl.abort(), 6000);
  const r = await fetch('https://scanner.tradingview.com/global/scan', {
    method: 'POST',
    // No Content-Type header to avoid CORS preflight
    body: JSON.stringify(body),
    signal: ctrl.signal
  });
  clearTimeout(tid);
  if(!r.ok) throw new Error('TV Scanner HTTP ' + r.status);
  const d = await r.json();
  if(!d.data?.length) throw new Error('TV Scanner empty');
  const prices = {};
  for(const item of d.data){
    const key = TV_REV[item.s];
    if(!key || !item.d) continue;
    const [close, chgPct, high, low] = item.d;
    if(close == null || isNaN(+close)) continue;
    const dec = key==='XAU'||key==='OIL'||key==='SILVER' ? 2
              : key==='DXY'||key==='US10Y' ? 3 : 5;
    prices[key] = {
      price:  (+close).toFixed(dec),
      change: +(chgPct || 0).toFixed(2),
      high:   high != null ? (+high).toFixed(dec)  : null,
      low:    low  != null ? (+low).toFixed(dec)   : null,
    };
  }
  return prices;
}

function buildDerivedPrices(prices){
  // DXY ↔ XAU correlation
  if(prices.XAU && prices.DXY){
    const xc = prices.XAU.change, dc = prices.DXY.change;
    const corr = (xc>0&&dc<0)||(xc<0&&dc>0);
    const div  = !corr && (Math.abs(xc)>0.3 || Math.abs(dc)>0.2);
    prices.CORRELATION = {
      status: div?'DIVERGENZA':corr?'NORMALE':'DEBOLE',
      signal: div?'⚠️ Divergenza DXY/XAU':corr?'✅ Correlazione inversa normale':'〰️ Correlazione debole',
      manipulation_hint: div
    };
  }
  // US10Y context
  if(prices.US10Y){
    const yc = prices.US10Y.change;
    prices.US10Y_CONTEXT = {
      yield: prices.US10Y.price, change: yc,
      signal: yc>0.05?'BEARISH_GOLD':yc<-0.05?'BULLISH_GOLD':'NEUTRAL',
      label:  yc>0.05 ? `Rendimenti ↑${yc}% — pressione XAU`
            : yc<-0.05? `Rendimenti ↓${yc}% — supporto XAU`
            : `Rendimenti stabili ${prices.US10Y.price}%`
    };
  }
  // Gold/Silver ratio
  if(prices.XAU && prices.SILVER){
    const gsr = parseFloat(prices.XAU.price) / parseFloat(prices.SILVER.price);
    prices.GOLD_SILVER_RATIO = {
      ratio: +gsr.toFixed(1),
      signal: gsr>90?'STRESS_FINANZIARIO':gsr>80?'RISK_OFF':gsr<65?'RISK_ON':'NEUTRO',
      label:  gsr>90 ? `G/S ${gsr.toFixed(0)} — stress finanziario`
            : gsr>80 ? `G/S ${gsr.toFixed(0)} — risk-off`
            : gsr<65 ? `G/S ${gsr.toFixed(0)} — risk-on`
            : `G/S ${gsr.toFixed(0)} — neutro`
    };
  }
  return prices;
}

function applyPrices(prices, source){
  if(!prices || !prices.XAU) return;
  if(!document.getElementById('p-xau')) return; // DOM not ready yet
  marketData = prices;
  dashContext.prices = prices;
  updatePriceStrip(prices);
  updateCorrelation(prices);
  updateMacroCards(prices);
  updateConfidence(prices, dashContext.sentiment || null);
  updateHeader(prices);
  const sb = document.getElementById('price-source');
  if(sb){
    if(source==='tv'){sb.textContent='📡 FP Markets live';sb.style.color='var(--green)';}
    else if(source==='tv+yahoo'){sb.textContent='📡 TV + Yahoo';sb.style.color='var(--green)';}
    else{sb.textContent='☁ Yahoo';sb.style.color='var(--dim)';}
  }
}

// Track consecutive TV failures to avoid hammering
let _tvFails = 0;

async function loadPrices(){
  try{
    // Try price.js first (dedicated, faster)
    const pd=await fetchJSON('/api/price', 5000);
    if(pd?.price){
      // We have XAU — build minimal prices object
      const xauPrice=parseFloat(pd.price);
      const xauChg=parseFloat(pd.changePct)||0;
      if(!marketData)marketData={};
      marketData.XAU={price:pd.price, change:xauChg, high:pd.high, low:pd.low};
      dashContext.prices=marketData;
      // Update just XAU immediately
      const conv=convertPrice(pd.price);
      const pxau=document.getElementById('p-xau');
      if(pxau)pxau.textContent=conv.sym+conv.val;
      const cxau=document.getElementById('c-xau');
      if(cxau){cxau.textContent=(xauChg>=0?'+':'')+xauChg+'%';cxau.style.color=xauChg>=0?'var(--green)':'var(--red)';}
      const bxau=document.getElementById('bxau');
      if(bxau){bxau.style.display='';bxau.textContent='XAU '+conv.sym+conv.val;bxau.className='hbadge '+(xauChg>=0?'hg':'hr');}
    }
    // Then try full market data in background
    fetchJSON('/api/market?type=prices', 7000).then(full=>{
      if(full?.ok&&full.prices&&Object.keys(full.prices).length>2){
        const prices = buildDerivedPrices(full.prices);
        marketData = prices;
        dashContext.prices = prices;
        updatePriceStrip(prices);
        updateCorrelation(prices);
        updateMacroCards(prices);
        updateConfidence(prices, dashContext.sentiment||null);
        updateHeader(prices);
      }
    });
  }catch(e){console.log('Prices:',e.message);}
}

// Slow refresh: sentiment + calendar (called every 30s)
// Sentiment-only refresh (called every 3s)
async function loadSentimentOnly(){
  // Server proxy avoids CORS — MFX blocks direct browser requests too
  try{
    const mfxSess = typeof mfxSession !== 'undefined' && mfxSession?.session
      ? '&session=' + encodeURIComponent(mfxSession.session) : '';
    const sd = await fetchJSON('/api/market?type=sentiment'+mfxSess, 5000);
    if(sd?.ok && sd.xauusd && sd.xauusd.longPct != null){
      dashContext.sentiment = sd.xauusd;
      updateSentiment(sd.xauusd, sd.source);
      if(marketData) updateConfidence(marketData, sd.xauusd);
    }
  } catch(e) { console.log('Sentiment:', e.message); }
}

async function loadSlowData(){
  // Run in parallel, don't await each other
  const mfxSess = mfxSession?.session ? '&session='+encodeURIComponent(mfxSession.session) : '';
  fetchJSON('/api/market?type=sentiment'+mfxSess, 6000).then(async sd=>{
    if(sd?.ok&&sd.xauusd){
      dashContext.sentiment=sd.xauusd;
      updateSentiment(sd.xauusd, sd.source);
      if(marketData)updateConfidence(marketData,sd.xauusd);
    } else {
      // Server blocked — fetch MyFxBook directly from browser (no CORS issue)
      try{
        const r=await fetch('https://www.myfxbook.com/api/get-community-outlook.json?session=&symbols=XAUUSD',{
          headers:{'Accept':'application/json'}
        });
        if(r.ok){
          const d=await r.json();
          const sym=d.symbols?.find(s=>s.name==='XAUUSD')||d.symbols?.[0];
          if(sym?.longPercentage!=null){
            const lp=parseFloat(sym.longPercentage), sp=parseFloat(sym.shortPercentage);
            const sent={
              longPct:lp, shortPct:sp,
              signal:lp>60?'RETAIL_LONG_HEAVY':sp>60?'RETAIL_SHORT_HEAVY':'MIXED',
              contrarian:lp>65?'BEARISH_BIAS':sp>65?'BULLISH_BIAS':'NEUTRAL',
              note:lp>65?'⚠️ Retail '+Math.round(lp)+'% long — smart money SHORT':
                   sp>65?'⚠️ Retail '+Math.round(sp)+'% short — squeeze possibile':''
            };
            dashContext.sentiment=sent;
            updateSentiment(sent,'myfxbook_direct');
            if(marketData)updateConfidence(marketData,sent);
          }
        }
      }catch(e){console.log('Direct sentiment failed:',e.message);}
    }
  });
  loadCotData();
  fetchJSON('/api/market?type=calendar', 7000).then(cd=>{
    if(cd?.ok){dashContext.calendar=cd.events;updateCalendar(cd.events);}
    else updateCalendar([]);
  });
}

function updatePriceStrip(prices){
  if(!prices) return;
  const map={XAU:'xau',DXY:'dxy',EURUSD:'eur',GBPUSD:'gbp',OIL:'oil'};
  Object.entries(map).forEach(([key,id])=>{
    const d=prices[key];if(!d)return;
    const chg=d.change;
    // Convert price for non-DXY symbols
    let displayPrice;
    if(key==='DXY'||key==='EURUSD'||key==='GBPUSD'){
      displayPrice=`$${d.price}`;
    }else{
      const conv=convertPrice(d.price);
      displayPrice=`${conv.sym}${conv.val}`;
    }
    document.getElementById(`p-${id}`).textContent=displayPrice;
    const ce=document.getElementById(`c-${id}`);
    ce.textContent=`${chg>=0?'+':''}${chg}%`;
    ce.style.color=chg>=0?'var(--green)':'var(--red)';
  });
  const x=prices.XAU;
  if(x){
    const b=document.getElementById('bxau');
    b.style.display='';
    const conv=convertPrice(x.price);
    b.textContent=`XAU ${conv.sym}${conv.val}`;
    b.className='hbadge '+(x.change>=0?'hg':'hr');
  }
}

function updateMacroCards(prices){
  if(!prices) return;
  // US10Y Yield
  const u = prices.US10Y_CONTEXT;
  if(u){
    const el=document.getElementById('us10y-val');
    const sig=document.getElementById('us10y-signal');
    const lbl=document.getElementById('us10y-label');
    if(el) el.textContent=u.yield+'%';
    if(sig){
      const isUp=u.change>0.05, isDown=u.change<-0.05;
      sig.textContent=isUp?'↑ XAU ↓':isDown?'↓ XAU ↑':'→';
      sig.style.color=isUp?'var(--red)':isDown?'var(--green)':'var(--dim)';
    }
    if(lbl) lbl.textContent=u.label;
  }
  // Gold/Silver Ratio
  const g = prices.GOLD_SILVER_RATIO;
  if(g){
    const el=document.getElementById('gsr-val');
    const sig=document.getElementById('gsr-signal');
    const lbl=document.getElementById('gsr-label');
    if(el) el.textContent=g.ratio;
    if(sig){
      const col=g.signal==='STRESS_FINANZIARIO'?'var(--red)':g.signal==='RISK_OFF'?'var(--yellow)':g.signal==='RISK_ON'?'var(--green)':'var(--dim)';
      sig.textContent=g.signal.replace('_',' ');
      sig.style.color=col;
    }
    if(lbl) lbl.textContent=g.label;
  }
}

// Load COT data separately (weekly, cached)
async function loadCotData(){
  try{
    const d=await fetchJSON('/api/market?type=cot', 5000);
    if(d?.ok&&d.netLong!=null){
      const el=document.getElementById('cot-net');
      const sig=document.getElementById('cot-signal');
      const lbl=document.getElementById('cot-label');
      if(el){
        const net=parseInt(d.netLong);
        el.textContent=(net>0?'+':'')+net.toLocaleString()+'K';
        el.style.color=net>200?'var(--red)':net<50?'var(--green)':'var(--dim)';
      }
      if(sig){
        const extremeLong=d.netLong>200, extremeShort=d.netLong<50;
        sig.textContent=extremeLong?'TOP RISK':extremeShort?'BOTTOM?':'NEUTRO';
        sig.style.color=extremeLong?'var(--red)':extremeShort?'var(--green)':'var(--dim)';
      }
      if(lbl&&d.reportDate) lbl.textContent='Report: '+d.reportDate+(d.netLong>200?' · Speculatori eccessivi':'');
    }
  }catch(e){console.log('COT:',e.message);}
}

function updateCorrelation(prices){
  if(!prices) return;
  const c=prices.CORRELATION;if(!c)return;
  // Store globally so confidence score uses same value
  dashContext.correlation=c;
  // Update correlation card elements (if present — card may be hidden)
  const el=document.getElementById('corr-status');
  const sig=document.getElementById('corr-signal');
  const col=c.status==='DIVERGENZA'?'var(--red)':c.status==='NORMALE'?'var(--green)':'var(--yellow)';
  if(el){el.textContent=c.status;el.style.color=col;}
  if(sig){sig.textContent=c.signal;sig.style.color=col;}
  const xcEl=document.getElementById('corr-xau-chg');
  const dcEl=document.getElementById('corr-dxy-chg');
  if(prices.XAU&&xcEl) xcEl.textContent=`${prices.XAU.change>=0?'+':''}${prices.XAU.change}%`;
  if(prices.DXY&&dcEl) dcEl.textContent=`DXY ${prices.DXY.change>=0?'+':''}${prices.DXY.change}%`;
}

