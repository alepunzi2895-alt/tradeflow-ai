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

async function loadPrices(){
  try{
    // Try price.js first (dedicated, faster)
    const active = window.activeAsset || 'XAU';
    const pd=await fetchJSON(`/api/price?asset=${active}`, 5000);
    if(pd?.price){
      // We have asset price — build minimal prices object
      const assetPrice=parseFloat(pd.price);
      const assetChg=parseFloat(pd.changePct)||0;
      if(!marketData)marketData={};
      marketData[active]={price:pd.price, change:assetChg, high:pd.high, low:pd.low};
      dashContext.prices=marketData;
      // Update just main asset immediately
      const conv=convertPrice(pd.price);
      const pxau=document.getElementById('p-xau');
      if(pxau)pxau.textContent=conv.sym+conv.val;
      const cxau=document.getElementById('c-xau');
      if(cxau){cxau.textContent=(assetChg>=0?'+':'')+assetChg+'%';cxau.style.color=assetChg>=0?'var(--green)':'var(--red)';}
      const bxau=document.getElementById('bxau');
      if(bxau){bxau.style.display='';bxau.textContent=`${active} `+conv.sym+conv.val;bxau.className='hbadge '+(assetChg>=0?'hg':'hr');}
      
      // Update labels dynamically
      const lblAsset=document.getElementById('lbl-asset');
      if(lblAsset)lblAsset.textContent = `${active}/USD`;
      const lblSent=document.getElementById('lbl-sent-title');
      if(lblSent)lblSent.textContent = `RETAIL SENTIMENT · ${active}/USD`;
      const lblMfkk=document.getElementById('lbl-mfkk-title');
      if(lblMfkk)lblMfkk.textContent = `MFKK STRATEGY SCORE · ${active}/USD H1`;
    } else {
      // price.js failed — try tvprice as XAU quick fallback
      const tv=await fetchJSON('/api/tvprice', 6000);
      if(tv?.ok&&tv.prices?.XAU){
        const xd=tv.prices.XAU;
        if(!marketData)marketData={};
        marketData.XAU=xd;
        dashContext.prices=marketData;
        const conv=convertPrice(xd.price);
        const pxau=document.getElementById('p-xau');
        if(pxau)pxau.textContent=conv.sym+conv.val;
        const cxau=document.getElementById('c-xau');
        const xauChg=xd.change||0;
        if(cxau){cxau.textContent=(xauChg>=0?'+':'')+xauChg+'%';cxau.style.color=xauChg>=0?'var(--green)':'var(--red)';}
        const bxau=document.getElementById('bxau');
        if(bxau){bxau.style.display='';bxau.textContent='XAU '+conv.sym+conv.val;bxau.className='hbadge '+(xauChg>=0?'hg':'hr');}
        // TV Scanner returns all symbols — use them for full update too
        if(Object.keys(tv.prices).length>2){
          const prices=buildDerivedPrices(tv.prices);
          marketData=prices; dashContext.prices=prices;
          updatePriceStrip(prices);
          updateCorrelation(prices);
          updateMacroCards(prices);
          updateConfidence(prices, dashContext.sentiment||null);
          updateHeader(prices);
          return; // Already have full data from tvprice
        }
      }
    }
    // Then try full market data in background (Centralized Market API)
    fetchJSON('/api/market?type=prices', 7000).then(full=>{
      if(full?.ok && full.prices){
        const prices=buildDerivedPrices(full.prices);
        marketData=prices; dashContext.prices=prices;
        updatePriceStrip(prices);
        updateCorrelation(prices);
        updateMacroCards(prices);
        updateConfidence(prices, dashContext.sentiment||null);
        updateHeader(prices);
      }
    });
  }catch(e){console.log('Prices:',e.message);}
}

// Sentiment-only refresh — uses server-side proxy to avoid CORS
async function loadSentimentOnly(){
  try{
    const assetStr = `${window.activeAsset||'XAU'}USD`;
    const res = await fetch('/api/myfxbook', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'outlook', symbol: assetStr })
    });
    
    if(!res.ok) return;
    const json = await res.json();
    if(json.ok && json.outlook){
      const d = json.outlook;
      const sym = d.symbols?.find(s=>s.name===assetStr) || d.symbols?.[0];
      if(sym?.longPercentage != null){
        const lp = parseFloat(sym.longPercentage), sp = parseFloat(sym.shortPercentage);
        const sent = {
          longPct: lp, shortPct: sp,
          signal: lp > 60 ? 'RETAIL_LONG_HEAVY' : sp > 60 ? 'RETAIL_SHORT_HEAVY' : 'MIXED',
          contrarian: lp > 65 ? 'BEARISH_BIAS' : sp > 65 ? 'BULLISH_BIAS' : 'NEUTRAL',
          note: lp > 65 ? '⚠️ Retail '+Math.round(lp)+'% long — smart money SHORT' :
                sp > 65 ? '⚠️ Retail '+Math.round(sp)+'% short — squeeze possibile' : ''
        };
        dashContext.sentiment = sent;
        updateSentiment(sent, 'myfxbook_proxy');
        if(marketData) updateConfidence(marketData, sent);
      }
    }
  }catch(e){console.log('Sentiment Proxy Error:', e.message);}
}

// Slow refresh: sentiment + calendar (called every 30s)
async function loadSlowData(){
  const assetStr = `${window.activeAsset || 'XAU'}USD`;
  const mfxSess = mfxSession?.session ? '&session='+encodeURIComponent(mfxSession.session) : '';
  fetchJSON('/api/market?type=sentiment&symbol=' + assetStr + mfxSess, 6000).then(async sd => {
    if(sd?.ok && sd.outlook && sd.outlook.symbols){
      // Support dual-asset simulation response
      const sym = sd.outlook.symbols.find(s => s.name === assetStr) || sd.outlook.symbols[0];
      if(sym && sym.longPercentage != null){
        const lp = parseFloat(sym.longPercentage), sp = parseFloat(sym.shortPercentage);
        const sent = {
          longPct: lp, shortPct: sp,
          synthetic: sd.source === 'simulation',
          signal: lp > 60 ? 'RETAIL_LONG_HEAVY' : sp > 60 ? 'RETAIL_SHORT_HEAVY' : 'MIXED',
          contrarian: lp > 65 ? 'BEARISH_BIAS' : sp > 65 ? 'BULLISH_BIAS' : 'NEUTRAL',
          note: lp > 65 ? '⚠️ Retail ' + Math.round(lp) + '% long — smart money SHORT' :
                sp > 65 ? '⚠️ Retail ' + Math.round(sp) + '% short — squeeze possibile' : ''
        };
        dashContext.sentiment = sent;
        updateSentiment(sent, sd.source || 'myfxbook_proxy');
        if(marketData) updateConfidence(marketData, sent);
      }
    } else {
      // Server blocked — fetch MyFxBook directly from browser (no CORS issue)
      try{
        const assetStr = `${window.activeAsset||'XAU'}USD`;
        const r=await fetch(`https://www.myfxbook.com/api/get-community-outlook.json?session=&symbols=${assetStr}`,{
          headers:{'Accept':'application/json'}
        });
        if(r.ok){
          const d=await r.json();
          const sym=d.symbols?.find(s=>s.name===assetStr)||d.symbols?.[0];
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
  // Economic Calendar — uses robust server-side proxy
  fetchJSON('/api/market?type=calendar', 7000).then(cd => {
    if(cd?.ok && cd.events){
      dashContext.calendar = cd.events;
      updateCalendar(cd.events);
    } else {
      updateCalendar([]);
    }
  }).catch(e => {
    console.log('Calendar Error:', e.message);
    updateCalendar([]);
  });
}

function updatePriceStrip(prices){
  const active = window.activeAsset || 'XAU';
  const assetKey = active === 'XAG' ? 'SILVER' : 'XAU';
  const map={[assetKey]:'xau',DXY:'dxy',EURUSD:'eur',GBPUSD:'gbp',OIL:'oil'};
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
  const b1=document.getElementById('bxau');
  if(prices.XAU && b1){
    b1.style.display='';
    const conv=convertPrice(prices.XAU.price);
    b1.textContent=`XAU ${conv.sym}${conv.val}`;
    b1.className='hbadge '+(prices.XAU.change>=0?'hg':'hr')+(active==='XAU'?' active-badge':'');
  }
  const b2=document.getElementById('bxag');
  if(prices.SILVER && b2){
    b2.style.display='';
    const conv=convertPrice(prices.SILVER.price);
    b2.textContent=`XAG ${conv.sym}${conv.val}`;
    b2.className='hbadge '+(prices.SILVER.change>=0?'hg':'hr')+(active==='XAG'?' active-badge':'');
  }
}


// ── DERIVED PRICES (Correlation, US10Y context, Gold/Silver Ratio) ──────
function buildDerivedPrices(prices){
  const active = window.activeAsset || 'XAU';
  const assetKey = active === 'XAG' ? 'SILVER' : 'XAU';
  
  if(prices[assetKey] && prices.DXY){
    const xc=prices[assetKey].change, dc=prices.DXY.change;
    const corr=(xc>0&&dc<0)||(xc<0&&dc>0);
    const volTh = active === 'XAG' ? 0.45 : 0.3; // XAG is more volatile, requires larger divergence
    const div=!corr&&(Math.abs(xc)>volTh||Math.abs(dc)>0.2);
    prices.CORRELATION={
      status:div?'DIVERGENZA':corr?'NORMALE':'DEBOLE',
      signal:div?`⚠️ Divergenza DXY/${active}`:corr?'✅ Correlazione inversa normale':'〰️ Correlazione debole',
      manipulation_hint:div
    };
  }
  if(prices.US10Y){
    const yc=prices.US10Y.change;
    prices.US10Y_CONTEXT={
      yield:prices.US10Y.price, change:yc,
      signal:yc>0.05?`BEARISH_${active}`:yc<-0.05?`BULLISH_${active}`:'NEUTRAL',
      label:yc>0.05?`Rendimenti ↑${yc}% — pressione ${active}`:
            yc<-0.05?`Rendimenti ↓${yc}% — supporto ${active}`:
            `Rendimenti stabili ${prices.US10Y.price}%`
    };
  }
  if(prices.XAU && prices.SILVER){
    const gsr=parseFloat(prices.XAU.price)/parseFloat(prices.SILVER.price);
    prices.GOLD_SILVER_RATIO={
      ratio:+gsr.toFixed(1),
      signal:gsr>90?'STRESS_FINANZIARIO':gsr>80?'RISK_OFF':gsr<65?'RISK_ON':'NEUTRO',
      label:gsr>90?`G/S ${gsr.toFixed(0)} — stress finanziario`:
            gsr>80?`G/S ${gsr.toFixed(0)} — risk-off`:
            gsr<65?`G/S ${gsr.toFixed(0)} — risk-on`:
            `G/S ${gsr.toFixed(0)} — neutro`
    };
  }
  return prices;
}

function updateMacroCards(prices){
  if(!prices) return;
  const active = window.activeAsset || 'XAU';
  const u=prices.US10Y_CONTEXT;
  if(u){
    const el=document.getElementById('us10y-val');
    const sig=document.getElementById('us10y-signal');
    const lbl=document.getElementById('us10y-label');
    if(el) el.textContent=u.yield+'%';
    if(sig){
      const isUp=u.change>0.05, isDown=u.change<-0.05;
      sig.textContent=isUp?`↑ ${active} ↓`:isDown?`↓ ${active} ↑`:'→';
      sig.style.color=isUp?'var(--red)':isDown?'var(--green)':'var(--dim)';
    }
    if(lbl) lbl.textContent=u.label;
  }
  const g=prices.GOLD_SILVER_RATIO;
  if(g){
    const el=document.getElementById('gsr-val');
    const sig=document.getElementById('gsr-signal');
    const lbl=document.getElementById('gsr-label');
    if(el) el.textContent=g.ratio;
    if(sig){
      const col=g.signal==='STRESS_FINANZIARIO'?'var(--red)':g.signal==='RISK_OFF'?'var(--yellow)':g.signal==='RISK_ON'?'var(--green)':'var(--dim)';
      sig.textContent=g.signal.replace('_',' ');sig.style.color=col;
    }
    if(lbl) lbl.textContent=g.label;
  }
  // COT is updated directly by loadCotData — no need to repeat here
}

function updateCorrelation(prices){
  const c=prices.CORRELATION;if(!c)return;
  // Store globally so confidence score uses same value
  dashContext.correlation=c;
  const el=document.getElementById('corr-status');
  const sig=document.getElementById('corr-signal');
  const col=c.status==='DIVERGENZA'?'var(--red)':c.status==='NORMALE'?'var(--green)':'var(--yellow)';
  if(el){el.textContent=c.status;el.style.color=col;}
  if(sig){sig.textContent=c.signal;sig.style.color=col;}
  const xcEl=document.getElementById('corr-xau-chg');
  if(prices.XAU&&xcEl) xcEl.textContent=`${prices.XAU.change>=0?'+':''}${prices.XAU.change}%`;
  const dcEl=document.getElementById('corr-dxy-chg');
  if(prices.DXY&&dcEl) dcEl.textContent=`${prices.DXY.change>=0?'+':''}${prices.DXY.change}%`;
}

function updateConfidence(prices, sentimentData){
  const active = window.activeAsset || 'XAU';
  const xRaw=prices?.[active], d=prices?.DXY||dashContext.prices?.DXY, e=prices?.EURUSD||dashContext.prices?.EURUSD, g=prices?.GBPUSD||dashContext.prices?.GBPUSD;
  const x=xRaw||dashContext.prices?.[active]; // always use latest asset
  const now=new Date();
  const hour=now.getUTCHours();
  const min=now.getUTCMinutes();
  const totalMins=hour*60+min;

  // ── FACTOR 1: DXY Correlation (peso 20%) — usa stesso valore della correlation card ──
  let dxyScore=50, dxyLabel='DXY neutro', dxySub='', dxyCol='var(--dim)';
  // Prefer stored correlation (same as top card) to avoid inconsistency
  const corrData = prices?.CORRELATION || dashContext.correlation; // prefer fresh prices
  if(corrData){
    const status=corrData.status;
    const xc=x?.change||0;
    if(status==='NORMALE'&&xc>0){dxyScore=80;dxyLabel='DXY ↓ XAU ↑';dxySub='Correlazione inversa bullish';dxyCol='var(--green)';}
    else if(status==='NORMALE'&&xc<0){dxyScore=20;dxyLabel='DXY ↑ XAU ↓';dxySub='Correlazione inversa bearish';dxyCol='var(--red)';}
    else if(status==='DIVERGENZA'){dxyScore=35;dxyLabel='Divergenza DXY/XAU';dxySub='⚠ Possibile manipolazione';dxyCol='var(--yellow)';}
    else{dxyScore=50;dxyLabel='Correlazione debole';dxySub='Mercato indeciso';dxyCol='var(--dim)';}
  } else if(x&&(d||dashContext.prices?.DXY)){
    const d2=d||dashContext.prices?.DXY;
    const xc=parseFloat(x.change||0), dc=parseFloat((d2||d)?.change||0);
    const corr=(xc>0&&dc<0)||(xc<0&&dc>0);
    const div=!corr&&(Math.abs(xc)>0.3||Math.abs(dc)>0.2);
    if(corr&&xc>0){dxyScore=80;dxyLabel='DXY ↓ XAU ↑';dxySub='Correlazione inversa bullish';dxyCol='var(--green)';}
    else if(corr&&xc<0){dxyScore=20;dxyLabel='DXY ↑ XAU ↓';dxySub='Correlazione inversa bearish';dxyCol='var(--red)';}
    else if(div){dxyScore=35;dxyLabel='Divergenza DXY/XAU';dxySub='⚠ Possibile manipolazione';dxyCol='var(--yellow)';}
    else{dxyScore=50;dxyLabel='Correlazione debole';dxySub='Mercato indeciso';dxyCol='var(--dim)';}
  }

  // ── FACTOR 2: Momentum XAU (peso 25%) ─────────────────
  let momScore=50, momLabel='Momentum laterale', momSub='', momCol='var(--dim)';
  if(x){
    const chg=parseFloat(x.change)||0;
    const price=parseFloat(x.price);
    const spread=x.high&&x.low?(parseFloat(x.high)-parseFloat(x.low)):0;
    if(chg>0.8){momScore=85;momLabel=`Momentum forte ↑ +${chg}%`;momSub='Trend intraday bullish';momCol='var(--green)';}
    else if(chg>0.3){momScore=68;momLabel=`Momentum moderato ↑ +${chg}%`;momSub='Bias bullish';momCol='var(--green)';}
    else if(chg<-0.8){momScore=15;momLabel=`Momentum forte ↓ ${chg}%`;momSub='Trend intraday bearish';momCol='var(--red)';}
    else if(chg<-0.3){momScore=32;momLabel=`Momentum moderato ↓ ${chg}%`;momSub='Bias bearish';momCol='var(--red)';}
    else{momScore=50;momLabel=`Laterale (${chg}%)`;momSub='Nessun bias chiaro';momCol='var(--dim)';}
  }

  // ── FACTOR 3: Kill Zone Timing (peso 18%) ─────────────
  // Istituzionali operano nelle Kill Zone — finestre di massima probabilità
  // London Open KZ:  08:00-10:00 UTC (480-600 min)
  // NY Open KZ:      13:30-16:00 UTC (810-960 min) ← il più potente
  let sessScore=50, sessLabel='', sessSub='', sessCol='var(--dim)', sessName='';
  if(totalMins>=810&&totalMins<=960){
    const minsIn=totalMins-810;
    sessScore=95;sessLabel='NY Kill Zone 🎯';
    sessSub=minsIn<=60?'Prima ora — setup istituzionali attivi':'Seconda ora — attenzione fake-out';
    sessCol='var(--green)';sessName='NY KZ';
  } else if(totalMins>=480&&totalMins<=600){
    const minsIn=totalMins-480;
    sessScore=88;sessLabel='London Kill Zone 🎯';
    sessSub=minsIn<=60?'Prima ora — massima liquidità europea':'Seconda ora LO';
    sessCol='var(--green)';sessName='LON KZ';
  } else if(totalMins>=600&&totalMins<=720){
    sessScore=65;sessLabel='Londra (post-KZ)';sessSub='Buona liquidità, meno direzionale';sessCol='var(--yellow)';sessName='LONDRA';
  } else if(totalMins>=960&&totalMins<=1020){
    sessScore=55;sessLabel='NY (post-KZ)';sessSub='Liquidità in calo';sessCol='var(--yellow)';sessName='NEW YORK';
  } else if(totalMins>=720&&totalMins<=810){
    sessScore=40;sessLabel='Pre-NY KZ';sessSub='Attendi NY Kill Zone (13:30 UTC)';sessCol='var(--dim)';sessName='PRE-NY';
  } else if(totalMins>=120&&totalMins<=480){
    sessScore=30;sessLabel='Asia Range';sessSub='Stop hunt possibile — no entry';sessCol='var(--red)';sessName='ASIA';
  } else {
    sessScore=20;sessLabel='Fuori Kill Zone';sessSub='Attendere LON KZ (08:00) o NY KZ (13:30)';sessCol='var(--dim)';sessName='OFF';
  }
  // Countdown to next Kill Zone
  let nextKZName='', nextKZMins=0;
  if(totalMins<480){nextKZName='LON KZ';nextKZMins=480-totalMins;}
  else if(totalMins<810){nextKZName='NY KZ';nextKZMins=810-totalMins;}
  else{nextKZName='LON KZ';nextKZMins=(1440-totalMins)+480;}
  const kzCD=sessScore>=85?'':(' · '+nextKZName+' tra '+Math.floor(nextKZMins/60)+'h'+(nextKZMins%60?nextKZMins%60+'m':''));
  const sessEl=document.getElementById('conf-session');
  if(sessEl) sessEl.textContent=sessName+kzCD;

  // ── FACTOR 4: Sentiment Contrarian (peso 12%) ──────────
  let sentScore=50, sentLabel='Long 50% / Short 50%', sentSub='', sentCol='var(--dim)';
  const sd2=dashContext.sentiment||sentimentData;
  if(sd2&&sd2.longPct!=null){
    const lp=sd2.longPct,sp=sd2.shortPct;
    sentLabel='Long '+Math.round(lp)+'% / Short '+Math.round(sp)+'%';
    if(lp>65){sentScore=30;sentSub='Retail over-long — contrarian BEARISH';sentCol='var(--red)';}
    else if(sp>65){sentScore=80;sentSub='Retail over-short — contrarian BULLISH';sentCol='var(--green)';}
    else if(lp>55){sentScore=45;sentSub='Leggera bias long retail';sentCol='var(--yellow)';}
    else if(sp>55){sentScore=60;sentSub='Leggera bias short retail';sentCol='var(--yellow)';}
    else{sentScore=50;sentSub='Sentiment bilanciato';sentCol='var(--dim)';}
  }

  // ── FACTOR 5: Multi-pair Confluence (peso 12%) ──────────
  let multiScore=50, multiLabel='Segnali misti', multiSub='Nessuna confluenza chiara', multiCol='var(--dim)';
  if(prices.EURUSD&&prices.GBPUSD){
    const ec=parseFloat(prices.EURUSD.change), gc2=parseFloat(prices.GBPUSD.change);
    const xc=x?parseFloat(x.change):0;
    const eurBull=ec>0.08, gbpBull=gc2>0.08, xauBull=xc>0.2;
    const eurBear=ec<-0.08, gbpBear=gc2<-0.08, xauBear=xc<-0.2;
    if(xauBull&&eurBull&&gbpBull){multiScore=80;multiLabel='Confluenza BUY';multiSub='EUR+GBP+XAU bullish';multiCol='var(--green)';}
    else if(xauBear&&eurBear&&gbpBear){multiScore=20;multiLabel='Confluenza SELL';multiSub='EUR+GBP+XAU bearish';multiCol='var(--red)';}
    else if(xauBull&&(eurBull||gbpBull)){multiScore=65;multiLabel='Parziale BUY';multiSub='XAU bullish, conferma parziale';multiCol='var(--yellow)';}
    else if(xauBear&&(eurBear||gbpBear)){multiScore=35;multiLabel='Parziale SELL';multiSub='XAU bearish, conferma parziale';multiCol='var(--yellow)';}
  }

  // ── FACTOR 6: Volatilità (peso 8%) ──────────────────────
  let volScore=50, volLabel='Volatilità nella norma', volSub='', volCol='var(--dim)';
  const xVol=x||dashContext.prices?.XAU;
  if(xVol&&xVol.high&&xVol.low){
    const range=parseFloat(xVol.high)-parseFloat(xVol.low);
    const rangePct=xVol.price?(range/parseFloat(xVol.price)*100):0;
    if(rangePct>1.5){volScore=25;volLabel=`Range ampio $${range.toFixed(0)}`;volSub='Alta volatilità — rischio elevato';volCol='var(--yellow)';}
    else if(rangePct>0.8){volScore=60;volLabel=`Range normale $${range.toFixed(0)}`;volSub='Volatilità nella norma';volCol='var(--green)';}
    else{volScore=75;volLabel=`Range stretto $${range.toFixed(0)}`;volSub='Bassa volatilità — setup puliti possibili';volCol='var(--green)';}
  }

  // ── FACTOR 7: News Impact (peso 13%) ────────────────────
  let newsScore=60, newsLabel='Nessun evento imminente', newsSub='', newsCol='var(--green)';
  if(dashContext.calendar?.length){
    const now2=new Date();
    const upcoming=dashContext.calendar
      .filter(ev=>ev.impact==='High')
      .map(ev=>({...ev,minsLeft:(new Date(ev.time)-now2)/60000}))
      .filter(ev=>ev.minsLeft>-60&&ev.minsLeft<480)
      .sort((a,b)=>Math.abs(a.minsLeft)-Math.abs(b.minsLeft));
    if(upcoming.length>0){
      const next=upcoming[0];
      const ml=next.minsLeft;
      const isXau=['NFP','CPI','FOMC','Federal','Fed','PCE','GDP','Payroll','Powell','Employment','Inflation'].some(k=>(next.event||'').includes(k));
      const xm=isXau?1.3:1.0;
      if(ml>=-60&&ml<=0){newsScore=Math.round(20*xm);newsLabel='📊 '+(next.event||'').split(' ').slice(0,3).join(' ')+' IN CORSO';newsSub='Volatilità estrema — no entry';newsCol='var(--red)';}
      else if(ml>0&&ml<=30){newsScore=Math.round(15*xm);newsLabel='⚠️ '+(next.event||'').split(' ').slice(0,3).join(' ')+' tra '+Math.round(ml)+'min';newsSub='ZONA ROSSA — chiudi size';newsCol='var(--red)';}
      else if(ml>30&&ml<=120){newsScore=Math.round(35*xm);newsLabel='⚡ '+(next.event||'').split(' ').slice(0,3).join(' ')+' tra '+Math.round(ml)+'min';newsSub='Pre-news — size ridotta';newsCol='var(--yellow)';}
      else if(ml>120&&ml<=240){newsScore=55;newsLabel=(next.event||'').split(' ').slice(0,3).join(' ')+' tra '+Math.round(ml/60)+'h';newsSub='News in arrivo — monitora';newsCol='var(--yellow)';}
      else{newsScore=65;newsLabel=(next.event||'').split(' ').slice(0,3).join(' ')+' tra '+Math.round(ml/60)+'h+';newsSub='Pianifica exits pre-news';newsCol='var(--dim)';}
    }
  }
  newsScore=Math.max(0,Math.min(100,newsScore));

  // ── FACTOR 8: US 10Y Yield (New - peso 10%) ─────────────
  let yieldScore=50, yieldLabel='Rendimenti stabili', yieldSub='', yieldCol='var(--dim)';
  if(prices.US10Y){
    const yc=parseFloat(prices.US10Y.change);
    const yVal=prices.US10Y.price;
    if(yc>0.2){yieldScore=30;yieldLabel=`US10Y ${yVal}% ↑ XAU ↓`;yieldSub=`Rendimenti ↑${yc}% — pressione bearish`;yieldCol='var(--red)';}
    else if(yc<-0.2){yieldScore=80;yieldLabel=`US10Y ${yVal}% ↓ XAU ↑`;yieldSub=`Rendimenti ↓${yc}% — sostegno bullish`;yieldCol='var(--green)';}
    else{yieldScore=55;yieldLabel=`US10Y ${yVal}% (Stabile)`;yieldSub='Nessuna pressione macro';yieldCol='var(--dim)';}
  }

  // ── FACTOR 9: Gold/Silver Ratio (New - peso 10%) ───────
  let gsrScore=50, gsrLabel='G/S Ratio neutro', gsrSub='', gsrCol='var(--dim)';
  if(prices.XAU && prices.SILVER){
    const ratio=parseFloat(parseFloat(prices.XAU.price)/parseFloat(prices.SILVER.price)).toFixed(1);
    // User context: 63.6 is RISK ON. High ratio (>80) = Gold expensive.
    if(ratio > 78){gsrScore=75;gsrLabel=`G/S Ratio ${ratio} · RISK OFF`;gsrSub='Domanda Oro superiore (difensiva)';gsrCol='var(--green)';}
    else if(ratio < 68){gsrScore=40;gsrLabel=`G/S Ratio ${ratio} · RISK ON`;gsrSub='Preferenza Silver (propensione rischio)';gsrCol='var(--yellow)';}
    else{gsrScore=60;gsrLabel=`G/S Ratio ${ratio} · NEUTRO`;gsrSub='Regime normale';gsrCol='var(--green)';}
  }

  // ── FACTOR 10: COT Positioning (New - peso 10%) ───────
  let cotScore=50, cotLabel='Dati COT neutri', cotSub='', cotCol='var(--dim)';
  const cot=window._cotData;
  if(cot){
    if(cot.signal==='BULLISH'){cotScore=85;cotLabel='COT Bullish';cotSub='Istituzionali Long';cotCol='var(--green)';}
    else if(cot.signal==='BEARISH'){cotScore=25;cotLabel='COT Bearish';cotSub='Istituzionali Short';cotCol='var(--red)';}
    else{cotScore=50;cotLabel='COT Neutro';cotSub='Posizionamento misto';cotCol='var(--dim)';}
  }

  // ── WEIGHTED SCORE 10 fattori (10% cad.) ──────────────────
  const weights=[
    {score:isNaN(momScore)?50:momScore,  w:0.10},
    {score:isNaN(dxyScore)?50:dxyScore,  w:0.10},
    {score:isNaN(sessScore)?50:sessScore,w:0.10},
    {score:isNaN(sentScore)?50:sentScore,w:0.10},
    {score:isNaN(multiScore)?50:multiScore,w:0.10},
    {score:isNaN(volScore)?50:volScore,  w:0.10},
    {score:isNaN(newsScore)?60:newsScore,w:0.10},
    {score:isNaN(yieldScore)?50:yieldScore,w:0.10},
    {score:isNaN(gsrScore)?50:gsrScore,  w:0.10},
    {score:isNaN(cotScore)?50:cotScore,  w:0.10},
  ];
  const total=Math.round(weights.reduce((s,f)=>s+f.score*f.w,0));
  let bias='NEUTRO', summary='';
  if(total>=75){bias='FORTE BUY';summary='Setup istituzionale confermato — alta probabilità';}
  else if(total>=60){bias='BUY VALIDO';summary='Confluenza positiva — setup operabile';}
  else if(total>=50){bias='BUY PARZIALE';summary='Segnale parziale — attendi ulteriori conferme';}
  else if(total>=40){bias='NEUTRO';summary='Indicatori misti — evita entries adesso';}
  else if(total>=30){bias='SELL PARZIALE';summary='Segnale parziale — attendi ulteriori conferme';}
  else if(total>=20){bias='SELL VALIDO';summary='Confluenza negativa — setup operabile';}
  else{bias='FORTE SELL';summary='Setup istituzionale bearish — alta probabilità';}

  // Adjust bias for current mfkkDir if available
  if(dashContext.mfkk?.score>70&&dashContext.mfkk?.dir){
    const mfkkBias=dashContext.mfkk.dir.toUpperCase();
    if(bias.includes('NEUTRO')&&mfkkBias==='SELL') bias='NEUTRO–SELL';
    if(bias.includes('NEUTRO')&&mfkkBias==='BUY') bias='NEUTRO–BUY';
  }

  // Update UI
  const nb2=document.getElementById('conf-num');
  if(nb2){nb2.textContent=total;nb2.style.color=total>=60?'var(--green)':total>=40?'var(--yellow)':'var(--red)';}
  const bb2=document.getElementById('conf-bias');
  if(bb2){bb2.textContent=bias;bb2.style.color=total>=60?'var(--green)':total>=40?'var(--yellow)':'var(--red)';}
  const sb2=document.getElementById('conf-sub');
  if(sb2) sb2.textContent=summary;
  // Circle
  const circ=document.getElementById('conf-circle');
  if(circ){
    const circumference=138.2; // 2 * PI * r (r=22)
    const offset=circumference-(total/100)*circumference;
    circ.style.strokeDashoffset=offset;
    circ.style.stroke=total>=60?'var(--green)':total>=40?'var(--yellow)':'var(--red)';
    circ.style.transition='stroke-dashoffset 0.5s ease, stroke 0.3s ease';
  }

  dashContext.confidence={score:total,bias,summary,factors:{
    momentum:{score:momScore,label:momLabel},dxy:{score:dxyScore,label:dxyLabel},
    session:{score:sessScore,label:sessLabel},sentiment:{score:sentScore,label:sentLabel},
    multi:{score:multiScore,label:multiLabel},vol:{score:volScore,label:volLabel},
    news:{score:newsScore,label:newsLabel},
    yield:{score:yieldScore,label:yieldLabel},gsr:{score:gsrScore,label:gsrLabel},
    cot:{score:cotScore,label:cotLabel}
  }};

    // Render factors safely
    const factorsList = [
      {id:'momentum', ico:'📊', label:momLabel, sub:momSub||'', score:momScore, col:momCol, w:'10%'},
      {id:'dxy', ico:'🔗', label:dxyLabel, sub:dxySub||'', score:dxyScore, col:dxyCol, w:'10%'},
      {id:'session', ico:'⏰', label:sessLabel, sub:sessSub||'', score:sessScore, col:sessCol, w:'10%'},
      {id:'sentiment', ico:'👥', label:sentLabel, sub:sentSub||'', score:sentScore, col:sentCol, w:'10%'},
      {id:'multi', ico:'🌍', label:multiLabel, sub:multiSub||'', score:multiScore, col:multiCol, w:'10%'},
      {id:'yield', ico:'📈', label:yieldLabel, sub:yieldSub||'', score:yieldScore, col:yieldCol, w:'10%'},
      {id:'gsr', ico:'⚖️', label:gsrLabel, sub:gsrSub||'', score:gsrScore, col:gsrCol, w:'10%'},
      {id:'cot', ico:'🏛️', label:cotLabel, sub:cotSub||'', score:cotScore, col:cotCol, w:'10%'},
      {id:'vol', ico:'📉', label:volLabel, sub:volSub||'', score:volScore, col:volCol, w:'10%'},
      {id:'news', ico:'📰', label:newsLabel, sub:newsSub||'', score:newsScore, col:newsCol, w:'10%'},
    ];
    const fl = document.getElementById('conf-factors');
    if(fl){
      fl.innerHTML = '';
      factorsList.forEach(f => {
        const pct = Math.max(0, Math.min(100, isNaN(f.score) ? 50 : f.score));
        const div = document.createElement('div');
        div.className = 'cf';
        div.style.cursor = 'pointer';
        div.onclick = () => showIndicatorInfo(f.id, f);
        div.innerHTML =
          '<div class="cf-ico">'+f.ico+'</div>'+
          '<div class="cf-info">'+
            '<div class="cf-label" style="color:'+f.col+'">'+f.label+'</div>'+
            '<div class="cf-sub">'+f.sub+' <span style="color:#3a3d44">peso '+f.w+'</span></div>'+
          '</div>'+
          '<div class="cf-score-bar">'+
            '<div class="cf-track"><div class="cf-fill" style="width:'+pct+'%;background:'+f.col+'"></div></div>'+
            '<div class="cf-pct" style="color:'+f.col+'">'+pct+'</div>'+
          '</div>';
        fl.appendChild(div);
      });
    }
    const qel = document.getElementById('conf-quality');
    if(qel){
      let quality = '', qualityBg = '', qualityCol = '';
      if(total >= 80){ quality = '💎 Setup di ALTA QUALITÀ: Confluenza macro e tecnica eccellente.'; qualityBg = '#00e67615'; qualityCol = 'var(--green)'; }
      else if(total >= 65){ quality = '✅ Setup BUONO: Condizioni favorevoli per entry a basso rischio.'; qualityBg = '#4fc3f715'; qualityCol = 'var(--blue)'; }
      else if(total >= 50){ quality = '⚠️ Setup MEDIO: Confluenza parziale, gestisci il rischio con attenzione.'; qualityBg = '#ffd70010'; qualityCol = 'var(--yellow)'; }
      else if(total > 0) { quality = '❌ Bassa Qualità: Segnali contrastanti. Evita operazioni aggressive.'; qualityBg = '#ff475710'; qualityCol = 'var(--red)'; }

      if(quality){
        qel.style.display = 'block';
        qel.style.background = qualityBg;
        qel.style.borderRadius = '7px';
        qel.style.padding = '7px 10px';
        qel.style.color = qualityCol;
        qel.style.fontSize = '11px';
        qel.style.lineHeight = '1.5';
        qel.textContent = quality;
      } else { qel.style.display = 'none'; }
    }
}

// ── INDICATOR INFO MODAL ──
const INDICATOR_DEFS = {
  'momentum': {
    title: 'Momentum Prezzo (M5/H1)',
    meaning: 'Misura la velocità del trend. Se il prezzo si muove velocemente nella direzione del trend, il momentum è alto e attira altri buyer.'
  },
  'dxy': {
    title: 'Correlazione DXY',
    meaning: 'L\'oro ha una correlazione inversa col Dollaro (DXY). Se il DXY crolla o è in un setup bearish, la probabilità di un rialzo dell\'oro (XAU) aumenta drasticamente.'
  },
  'session': {
    title: 'Sessione di Trading',
    meaning: 'Le sessioni London (08:00+) e New York (14:30+) portano la massima liquidità. Operare fuori sessione (Asiatica) è spesso rischioso per i breakout.'
  },
  'sentiment': {
    title: 'Retail Sentiment (Contrarian)',
    meaning: 'Logica Smart Money: se la maggior parte dei trader retail è LONG, noi cerchiamo opportunità SHORT (e viceversa) per catturare la liquidità degli stop loss.'
  },
  'multi': {
    title: 'Multi-Timeframe Confluence',
    meaning: 'Controlla che il trend su M15, H1 e H4 sia allineato. Una posizione è molto più sicura se tutti i timeframe puntano nella stessa direzione.'
  },
  'vol': {
    title: 'Volatilità (ATR)',
    meaning: 'L\'ATR misura quanto "rumore" c\'è nel mercato. Alta volatilità richiede stop loss più larghi, bassa volatilità permette entry più precise.'
  },
  'news': {
    title: 'Filtro News Macro',
    meaning: 'Evitiamo di fare trading 30 minuti prima e dopo news High Impact. Le news possono causare slippage o movimenti irrazionali del prezzo.'
  },
  'cci': {
    title: 'CCI_S (MFKK Parameter)',
    meaning: 'Commodity Channel Index ottimizzato. Identifica se siamo in una fase di spinta ciclica. MFKK lo usa per confermare la continuazione del trend.'
  },
  'macd': {
    title: 'MACD (MFKK Parameter)',
    meaning: 'Moving Average Convergence Divergence. Monitoriamo l\'incrocio delle medie e l\'istogramma per capire se il momentum sta accelerando o se c\'è esaurimento.'
  },
  'adx': {
    title: 'ADX (Trend Strength)',
    meaning: 'Misura la forza del trend. Valori sopra 25 indicano un trend deciso, rendendo i segnali di continuazione molto più affidabili.'
  },
  'yield': {
    title: 'US 10Y Yield Pressure',
    meaning: 'I rendimenti obbligazionari competono con l\'oro. Rendimenti in crescita rendono il dollaro più attrattivo e pesano negativamente sul prezzo dei metalli.'
  },
  'gsr': {
    title: 'Gold/Silver Ratio (GSR)',
    meaning: 'Indica il regime di rischio. Un ratio che scende indica Risk-On (Silver forte), un ratio che sale indica Risk-Off o sovraperformance difensiva dell\'Oro.'
  },
  'cot': {
    title: 'COT Large Speculators',
    meaning: 'Sentiment istituzionale (Smart Money). Seguiamo il posizionamento netto dei grandi speculatori per allinearci ai flussi monetari globali.'
  }
};

function showIndicatorInfo(key, currentData){
  const def = INDICATOR_DEFS[key];
  if(!def) return;
  document.getElementById('info-title').innerHTML = `<span>${currentData?.ico||'ℹ️'}</span> ${def.title}`;
  document.getElementById('info-meaning').textContent = def.meaning;
  
  let statusText = '';
  if(currentData){
    statusText = `<b>Stato Attuale:</b> ${currentData.label}<br><b>Score:</b> ${currentData.score}/100`;
  } else {
    statusText = `<b>Parametro calcolato in tempo reale</b> dal motore MFKK Strategy Score.`;
  }
  document.getElementById('info-status').innerHTML = statusText;
  document.getElementById('info-overlay').style.display = 'flex';
}
window.closeIndicatorInfo = function(){
  document.getElementById('info-overlay').style.display = 'none';
};
window.showIndicatorInfo = showIndicatorInfo;

function updateSentiment(s, source){
  const srcEl=document.getElementById('sent-source');
  if(!s||s.longPct==null){
    document.getElementById('sent-note').style.display='none';
    document.getElementById('sent-long-bar').style.width='50%';
    document.getElementById('sent-short-bar').style.width='50%';
    document.getElementById('sent-long-pct').textContent='—';
    document.getElementById('sent-short-pct').textContent='—';
    document.getElementById('sent-contrarian').textContent='';
    if(srcEl)srcEl.textContent='';
    return;
  }
  // Show data source
  if(srcEl){
    if(source==='myfxbook_auth'||source==='myfxbook') srcEl.textContent='MyFxBook ✓';
    else if(s.synthetic) srcEl.textContent='⚡ Stimato';
    else srcEl.textContent='';
    srcEl.style.color=source?.includes('myfxbook')?'var(--green)':'var(--yellow)';
  }
  document.getElementById('sent-long-bar').style.width=s.longPct+'%';
  document.getElementById('sent-short-bar').style.width=s.shortPct+'%';
  document.getElementById('sent-long-pct').textContent=s.longPct+'%';
  document.getElementById('sent-short-pct').textContent=s.shortPct+'%';
  const note=document.getElementById('sent-note');
  // Only show note if it's a real warning, not fallback text
  if(s.note&&s.note!=='Sentiment bilanciato'&&!s.note.includes('stimati')){
    note.style.display='block';note.textContent=s.note;
  }else{note.style.display='none';}
  const contra=document.getElementById('sent-contrarian');
  contra.textContent=s.contrarian!=='NEUTRAL'?`Segnale contrarian: ${s.contrarian}. Smart money probabile posizione opposta al retail.`:'';
  contra.style.color=s.contrarian==='BULLISH_BIAS'?'var(--green)':s.contrarian==='BEARISH_BIAS'?'var(--red)':'var(--dim)';
}

// XAU-impacting events keywords
const XAU_EVENTS=['NFP','Non-Farm','CPI','Inflation','FOMC','Federal Reserve','Fed','Interest Rate','GDP','PCE','PPI','Jobless','Employment','Powell','Yellen','Treasury','ISM','PMI','ECB','Draghi','Lagarde','Gold','DXY','Dollar','Unemployment'];

function isXauEvent(name){return XAU_EVENTS.some(k=>name&&name.toLowerCase().includes(k.toLowerCase()));}

let allCalEvents=[];
let calFilter='all';

function filterCal(f){
  calFilter=f;
  document.querySelectorAll('.cal-filter').forEach(b=>b.classList.remove('on'));
  document.getElementById(`cal-f-${f}`)?.classList.add('on');
  renderCalEvents();
}

function updateCalendar(events){
  allCalEvents=events||[];
  // Find next high-impact event
  const now=new Date();
  const upcoming=allCalEvents
    .filter(e=>e.impact==='High'&&new Date(e.time)>now)
    .sort((a,b)=>new Date(a.time)-new Date(b.time));
  
  if(upcoming.length){
    const next=upcoming[0];
    const nextEl=document.getElementById('cal-next');
    nextEl.style.display='block';
    document.getElementById('cal-next-name').textContent=next.event||'—';
    const d=new Date(next.time);
    const tzName=Intl.DateTimeFormat().resolvedOptions().timeZone;
    const tzShort=new Date().toLocaleTimeString('en',{timeZoneName:'short',timeZone:tzName}).split(' ').pop();
    document.getElementById('cal-next-meta').textContent=
      next.currency+' · '+d.toLocaleDateString(navigator.language||'it-IT',{weekday:'long',day:'numeric',month:'short',timeZone:tzName})+' '+d.toLocaleTimeString(navigator.language||'it-IT',{hour:'2-digit',minute:'2-digit',timeZone:tzName})+' '+tzShort;
    // Start countdown
    updateCountdown(d);
    if(window._cdInterval) clearInterval(window._cdInterval);
    window._cdInterval=setInterval(()=>updateCountdown(d),60000);
  }
  renderCalEvents();
}

function updateCountdown(targetDate){
  const now=new Date();
  const diff=targetDate-now;
  if(diff<=0){document.getElementById('cal-countdown').textContent='IN CORSO';return;}
  const h=Math.floor(diff/3600000);
  const m=Math.floor((diff%3600000)/60000);
  const d=Math.floor(diff/86400000);
  const txt=d>0?`${d}g ${h%24}h`:h>0?`${h}h ${m}m`:`${m} min`;
  document.getElementById('cal-countdown').textContent=`⏱ ${txt}`;
}

function renderCalEvents(){
  const el=document.getElementById('cal-events');
  let filtered=allCalEvents;
  if(calFilter==='xau') filtered=allCalEvents.filter(e=>isXauEvent(e.event));
  else if(calFilter==='usd') filtered=allCalEvents.filter(e=>e.currency==='USD');
  else if(calFilter==='eur') filtered=allCalEvents.filter(e=>e.currency==='EUR');

  if(!filtered.length){
    el.innerHTML='<div style="font-size:12px;color:var(--dim);padding:8px 0">Nessun evento trovato per questo filtro.</div>';
    return;
  }

  // Group by day
  const byDay={};
  filtered.forEach(e=>{
    const d=new Date(e.time);
    const key=d.toLocaleDateString(navigator.language||'it-IT',{weekday:'long',day:'numeric',month:'long',timeZone:Intl.DateTimeFormat().resolvedOptions().timeZone});
    if(!byDay[key])byDay[key]=[];
    byDay[key].push(e);
  });

  const now=new Date();
  el.innerHTML=Object.entries(byDay).map(([day,evs])=>{
    const dayHtml=evs.map(e=>{
      const d=new Date(e.time);
      const isPast=d<now;
      const isHigh=e.impact==='High';
      const isMed=e.impact==='Medium';
      const impCol=isHigh?'var(--red)':isMed?'var(--yellow)':'var(--dim)';
      const isXau=isXauEvent(e.event);
      const hasActual=e.actual&&e.actual!=='';
      const actualBetter=hasActual&&e.forecast&&parseFloat(e.actual)>parseFloat(e.forecast);
      const actualWorse=hasActual&&e.forecast&&parseFloat(e.actual)<parseFloat(e.forecast);
      const tz=Intl.DateTimeFormat().resolvedOptions().timeZone;
      const timeStr=d.toLocaleTimeString(navigator.language||'it-IT',{hour:'2-digit',minute:'2-digit',timeZone:tz});

      return `<div class="cal-ev" style="${isPast?'opacity:0.5':''}">
        <div class="cal-ev-imp" style="background:${impCol}"></div>
        <div class="cal-ev-body">
          <div style="display:flex;align-items:center;gap:5px">
            <div class="cal-ev-time">${timeStr}</div>
            ${isXau?`<span style="font-size:9px;background:#c8a96e18;border:1px solid #c8a96e33;border-radius:3px;padding:1px 4px;color:var(--g)">⚡${window.activeAsset||'XAU'}</span>`:''}
            ${isHigh?'<span style="font-size:9px;background:#ff475710;border:1px solid #ff475730;border-radius:3px;padding:1px 4px;color:var(--red)">●HIGH</span>':''}
          </div>
          <div class="cal-ev-name">${e.event||'—'}</div>
          <div style="font-size:10px;color:var(--dim);margin-top:1px">${e.currency||''}</div>
        </div>
        <div class="cal-ev-vals">
          ${hasActual?`<div class="cal-ev-actual" style="color:${actualBetter?'var(--green)':actualWorse?'var(--red)':'var(--dim)'}">A: ${e.actual}</div>`:''}
          ${e.forecast&&!hasActual?`<div style="font-size:10px;color:var(--blue);font-family:monospace">F: ${e.forecast}</div>`:''}
          ${e.previous?`<div class="cal-ev-prev">P: ${e.previous}</div>`:''}
        </div>
      </div>`;
    }).join('');

    return `<div class="cal-day">
      <div class="cal-day-hdr">${day.toUpperCase()}</div>
      ${dayHtml}
    </div>`;
  }).join('');
}

function updateHeader(prices){
  // Already handled in updatePriceStrip
}


async function loadCotData(){
  try{
    const d = await fetchJSON('/api/market?type=cot', 8000);
    if(d?.ok && d.cot){
      window._cotData = d.cot;
      // Update COT card directly
      const el = document.getElementById('cot-net');
      const sig = document.getElementById('cot-signal');
      const lbl = document.getElementById('cot-label');
      if(el) el.textContent = d.cot.net || '—';
      if(sig){
        const bull = d.cot.signal?.includes('BULL'), bear = d.cot.signal?.includes('BEAR');
        sig.textContent = d.cot.signal || '—';
        sig.style.color = bull ? 'var(--green)' : bear ? 'var(--red)' : 'var(--dim)';
      }
      if(lbl) lbl.textContent = d.cot.labels || 'CFTC Large Spec';
      // Show last update date (cleanup previous if any)
      const oldD = lbl.parentNode.querySelector('.cot-date');
      if(oldD) oldD.remove();
      if(sig && d.cot.last_updated){
        const dateEl = document.createElement('div');
        dateEl.className = 'cot-date';
        dateEl.style.fontSize = '8px';
        dateEl.style.color = 'var(--dim)';
        dateEl.style.marginTop = '2px';
        dateEl.textContent = 'Aggiornato: ' + d.cot.last_updated;
        lbl.parentNode.appendChild(dateEl);
      }
    }
  } catch(e){ console.log('COT:', e.message); }
}
