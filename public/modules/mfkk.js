// TradeFlow AI — modules/mfkk.js

// Scroll-safe value setter — saves/restores dash-panel scroll position
function _setVal(id, v){
  const el = document.getElementById(id);
  if(!el || v==null || isNaN(+v)) return;
  const dp = document.getElementById('dash-panel');
  const saved = dp ? dp.scrollTop : 0;
  el.value = +v;
  if(dp && saved > 0){
    requestAnimationFrame(()=>{ dp.scrollTop = saved; });
  }
}

// ── MFKK STRATEGY SCORE ──────────────────────────────────
let mfkkDir = 'buy'; // 'buy' or 'sell'
const mfkkTF = '1h'; // MFKK works on H1 only

function setMfkkTF(tf){
  mfkkTF = tf;
  ['1h','4h','1d'].forEach(t=>{
    const btn=document.getElementById('mfkk-tf-'+t);
    if(!btn)return;
    if(t===tf){btn.style.background='#c8a96e30';btn.style.borderColor='#c8a96e55';btn.style.color='var(--g)';}
    else{btn.style.background='var(--bg2)';btn.style.borderColor='var(--border)';btn.style.color='var(--dim)';}
  });
  loadIndicators();
}

// ── MFKK INDICATOR ENGINE ────────────────────────────────
// Candle cache: fetch once per minute, recalculate every 5s with live price
let mfkkCandles = [];     // H1 OHLCV cache (fetched browser-side)
let mfkkLastFetch = 0;    // timestamp of last candle fetch
let mfkkServerMacd = null; // MACD/ADX from TV Scanner via /api/indicators
let mfkkServerAdx = null;

// Math helpers
function _ema(src,p){
  // TradingView ta.ema(): first value as seed (not SMA)
  const k=2/(p+1);
  let v=src[0];
  const o=[v];
  for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
  return o;
}
function _sma(src,p){const o=new Array(src.length).fill(null);for(let i=p-1;i<src.length;i++){let s=0;for(let j=0;j<p;j++)s+=(src[i-j]||0);o[i]=s/p;}return o;}
function _hi(a,p,i){let m=-Infinity;for(let j=Math.max(0,i-p+1);j<=i;j++)if(a[j]!=null)m=Math.max(m,a[j]);return m;}
function _lo(a,p,i){let m=Infinity; for(let j=Math.max(0,i-p+1);j<=i;j++)if(a[j]!=null)m=Math.min(m,a[j]);return m;}

function computeFromCandles(candles, tf){
  // Resample to H4 if needed
  let c4 = candles;
  if(tf==='4h'){
    const map=new Map();
    for(const c of candles){
      const d=new Date(c.t*1000);
      const b=Math.floor(d.getUTCHours()/4)*4;
      const k=`${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}-${b}`;
      if(!map.has(k))map.set(k,{t:c.t,h:c.h,l:c.l,c:c.c});
      else{const e=map.get(k);e.h=Math.max(e.h,c.h);e.l=Math.min(e.l,c.l);e.c=c.c;e.t=c.t;}
    }
    c4=[...map.values()].sort((a,b)=>a.t-b.t);
  }
  if(c4.length<120)return null; // need at least 120 candles for CCI(50)+Stoch(50)+SMA(8)+SMA(8) warmup

  const H=c4.map(x=>x.h), L=c4.map(x=>x.l), C=c4.map(x=>x.c), n=C.length;

  // CCI_S: CCI(close,50) → stoch(cci,cci,cci,50) → SMA(K,8) → SMA(D,8) — exact Pine Script v4
  const CCI_P=50, STOCH_P=50, SK=8, SD=8;
  const cci=new Array(n).fill(null);
  for(let i=CCI_P-1;i<n;i++){
    const sl=C.slice(i-CCI_P+1,i+1);
    const mn=sl.reduce((a,b)=>a+b,0)/CCI_P;
    const md=sl.reduce((a,b)=>a+Math.abs(b-mn),0)/CCI_P;
    cci[i]=md===0?0:(C[i]-mn)/(0.015*md);
  }
  // stoch(cci,cci,cci,50) — pine: 100*(src-lowest)/(highest-lowest)
  const stk=new Array(n).fill(null);
  for(let i=CCI_P+STOCH_P-2;i<n;i++){
    if(cci[i]==null)continue;
    const lv=_lo(cci,STOCH_P,i), hv=_hi(cci,STOCH_P,i);
    stk[i]=(hv-lv)===0?50:((cci[i]-lv)/(hv-lv))*100;
  }
  // SMA(stoch,8) — propagate null like Pine Script (no 50-fill)
  const stk_k=new Array(n).fill(null);
  for(let i=SK-1;i<n;i++){
    const sl=stk.slice(i-SK+1,i+1);
    if(sl.some(v=>v==null))continue;
    stk_k[i]=sl.reduce((a,b)=>a+b,0)/SK;
  }
  const stk_d=new Array(n).fill(null);
  for(let i=SD-1;i<n;i++){
    const sl=stk_k.slice(i-SD+1,i+1);
    if(sl.some(v=>v==null))continue;
    stk_d[i]=sl.reduce((a,b)=>a+b,0)/SD;
  }
  const cciVal=+(stk_d[n-1]??50).toFixed(2);
  const cciPrev=stk_d[n-2];
  let cciSig='neutral';
  if(cciPrev!=null){
    if(cciPrev>=25&&cciVal<25)cciSig='enter_buy';
    else if(cciPrev<=75&&cciVal>75)cciSig='enter_sell';
    else if(cciPrev>75&&cciVal<=75)cciSig='exit_sell';
    else if(cciPrev<25&&cciVal>=25)cciSig='exit_buy';
  }

  // MACD(12,26,9) EMA — standard Pine Script v6 default parameters
  const e12=_ema(C,12), e26=_ema(C,26);
  const ml=e12.map((v,i)=>v-e26[i]);
  const sg=_ema(ml,9);
  const hist=ml.map((v,i)=>v-sg[i]);
  const macdVal=+ml[n-1].toFixed(4), sigVal=+sg[n-1].toFixed(4);
  const histVal=+hist[n-1].toFixed(4), histPrev=+(hist[n-2]||0).toFixed(4);
  let cross=macdVal>sigVal?'above':'below';
  if((ml[n-2]||0)<=(sg[n-2]||0)&&macdVal>sigVal)cross='cross_buy';
  else if((ml[n-2]||0)>=(sg[n-2]||0)&&macdVal<sigVal)cross='cross_sell';

  // ADX: Wilder smoothing for TR/DM, then SMA(DX,len) — exact Pine Script "ADX and DI for v4"
  const ADX_P=10; // Per=10 as set in user's TradingView indicator settings
  const TR=new Array(n).fill(0),DMP=new Array(n).fill(0),DMM=new Array(n).fill(0);
  for(let i=1;i<n;i++){
    TR[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));
    const upMove=H[i]-H[i-1], downMove=L[i-1]-L[i];
    DMP[i]=(upMove>downMove&&upMove>0)?upMove:0;
    DMM[i]=(downMove>upMove&&downMove>0)?downMove:0;
  }
  // Wilder smoothing: X = X[1] - X[1]/len + value (nz() starts at 0)
  const sTR=new Array(n).fill(0),sDMP=new Array(n).fill(0),sDMM=new Array(n).fill(0);
  for(let i=1;i<n;i++){
    sTR[i]=sTR[i-1]-sTR[i-1]/ADX_P+TR[i];
    sDMP[i]=sDMP[i-1]-sDMP[i-1]/ADX_P+DMP[i];
    sDMM[i]=sDMM[i-1]-sDMM[i-1]/ADX_P+DMM[i];
  }
  const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
  const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
  const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
  // ADX = SMA(DX, len) — Pine Script uses simple moving average here, NOT Wilder RMA!
  const ADX=_sma(DX, ADX_P);

  return {
    cci:{value:cciVal,signal:cciSig,zone:cciVal>75?'overbought':cciVal<25?'oversold':'neutral'},
    macd:{macd:macdVal,signal:sigVal,histogram:histVal,hist_prev:histPrev,hist_rising:histVal>histPrev,cross},
    adx:{adx:+ADX[n-1].toFixed(2),di_plus:+DIP[n-1].toFixed(2),di_minus:+DIM[n-1].toFixed(2)},
    last_close:+C[n-1].toFixed(2), candles:n
  };
}

// Fetch candles via server proxy (bypasses both CORS and IP blocks)
async function fetchBrowserCandles(){
  try{
    // Try our server proxy first (it handles Yahoo + TV history fallback)
    const url = '/api/candles?range=60d&interval=1h';
    const r = await fetch(url);
    if(!r.ok) throw new Error('Candle proxy HTTP '+r.status);
    const d = await r.json();
    if(!d?.ok || !d.candles?.length) throw new Error('No candles from proxy');
    console.log('Server candle proxy OK:', d.count, 'candles from', d.source);
    return d.candles;
  }catch(e){
    console.log('fetchBrowserCandles proxy:', e.message);
    // Fallback: try the indicators API which also returns candle_data
    try{
      const d = await fetchJSON('/api/indicators?tf=1h', 12000);
      if(d?.ok && d.candle_data?.length > 50){
        console.log('Candles from indicators API:', d.candle_data.length);
        return d.candle_data;
      }
    }catch(e2){ console.log('Candle fallback:', e2.message); }
    return [];
  }
}


// Fetch all indicators from /api/indicators (MACD from TV Scanner + ADX/CCI from candles)
async function fetchServerIndicators(){
  try{
    const d = await fetchJSON('/api/indicators?tf='+mfkkTF, 12000);
    if(d?.ok){
      if(d.macd) mfkkServerMacd = d.macd;
      if(d.adx)  mfkkServerAdx  = d.adx;
      console.log('Server indicators: MACD='+(d.macd?.macd?.toFixed(2)??'N/A')+' ADX='+(d.adx?.adx?.toFixed(2)??'N/A')+' CCI='+(d.cci?.value??'N/A')+' ['+d.macd_source+']');
    }
    return d;
  }catch(e){ console.log('fetchServerIndicators:', e.message); return null; }
}


// Main loader: fetches candles + server indicators, populates all MFKK fields
async function loadIndicatorCandles(){
  try{
    mfkkLastFetch = Date.now();
    const telEl = document.getElementById('mfkk-time');

    // Run in parallel: candle proxy (for CCI_S live recalc) + server indicators (MACD+ADX+CCI)
    const [candles, serverData] = await Promise.all([
      fetchBrowserCandles(),
      fetchServerIndicators()
    ]);

    const set = (id,v) => _setVal(id,v);

    // Store candles for live recalc
    if(candles.length > 0) mfkkCandles = candles;

    // CCI_S: prefer server-computed (from same candle data), fallback to browser computation
    if(serverData?.cci?.value != null){
      set('mfkk-cci', serverData.cci.value);
      console.log('CCI_S from server:', serverData.cci.value);
    } else if(mfkkCandles.length >= 120){
      const vals = computeFromCandles(mfkkCandles, mfkkTF);
      if(vals){
        const cciVal = vals.cci?.value ?? vals.cci;
        set('mfkk-cci', cciVal);
        console.log('CCI_S from browser candles:', cciVal);
      }
    }

    // MACD: from TV Scanner (exact TradingView values)
    if(mfkkServerMacd){
      set('mfkk-macd-fast', mfkkServerMacd.macd);
      set('mfkk-macd-slow', mfkkServerMacd.signal);
      set('mfkk-macd-hist', mfkkServerMacd.histogram);
    }

    // ADX(10): prefer server-computed (exact Pine Script formula)
    if(mfkkServerAdx?.adx != null){
      set('mfkk-adx',     mfkkServerAdx.adx);
      set('mfkk-diplus',  mfkkServerAdx.di_plus);
      set('mfkk-diminus', mfkkServerAdx.di_minus);
    }

    // Update timestamp display
    if(telEl){
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const now = new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit',timeZone:tz});
      const price = serverData?.last_close || mfkkCandles.at(-1)?.c || '?';
      telEl.textContent = '$'+price+' · '+now+' ('+mfkkTF.toUpperCase()+') ⟳';
    }

    if(serverData?.ok || mfkkCandles.length >= 120){
      dashContext.indicatorBase = serverData;
      dashContext.indicators = serverData;
      setTimeout(autoSelectBestDir, 50);
    }
  }catch(e){ console.log('loadIndicatorCandles:', e.message); }
}



// Recalculate CCI_S every 5s: inject live price into last candle
// MACD and ADX use the server TV Scanner values (updated every 60s)
function recalcIndicators(){
  if(mfkkCandles.length<50) return;
  const livePrice=marketData?.XAU?.price;
  if(!livePrice) return;
  const live=parseFloat(livePrice);
  if(isNaN(live)) return;

  // Clone candles and update last candle with live price
  const candles=[...mfkkCandles];
  const last={...candles[candles.length-1]};
  last.c=live; last.h=Math.max(last.h,live); last.l=Math.min(last.l,live);
  candles[candles.length-1]=last;

  // Recalculate CCI_S with live price — only if we have enough candles
  const vals=computeFromCandles(candles, mfkkTF);
  if(!vals) return;

  const set=(id,v)=>_setVal(id,v);
  const cv=vals.cci?.value??vals.cci;
  // Always set CCI from local computation (it uses live price injection)
  if(cv != null && !isNaN(cv)) set('mfkk-cci', cv);


  // Use server TV Scanner values for MACD/ADX (no recalc needed - they update every 60s)
  const mv = mfkkServerMacd?.macd;
  const sv_val = mfkkServerMacd?.signal;
  const hv = mfkkServerMacd?.histogram;
  const av = mfkkServerAdx?.adx;
  const dp = mfkkServerAdx?.di_plus;
  const dm = mfkkServerAdx?.di_minus;
  if(mv!=null){set('mfkk-macd-fast',mv);set('mfkk-macd-slow',sv_val);set('mfkk-macd-hist',hv);}
  if(av!=null){set('mfkk-adx',av);set('mfkk-diplus',dp);set('mfkk-diminus',dm);}


  const telEl=document.getElementById('mfkk-time');
  if(telEl){
    const now=new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});
    telEl.textContent='$'+live+' · '+now+' ⚡live';
  }
  calcMfkk();
  setTimeout(autoSelectBestDir,20);
}

// Backward compatible wrapper
async function loadIndicators(){
  return loadIndicatorCandles();
}

function setMfkkDir(dir){
  mfkkDir = dir;
  document.getElementById('mfkk-buy').className = 'mfkk-dir' + (dir==='buy'?' on-buy':'');
  document.getElementById('mfkk-sell').className = 'mfkk-dir' + (dir==='sell'?' on-sell':'');
  calcMfkk();
}

function calcMfkk(){
  const dir = mfkkDir;
  const isBuy = dir === 'buy';
  const cciVal    = parseFloat(document.getElementById('mfkk-cci').value);
  const macdFast  = parseFloat(document.getElementById('mfkk-macd-fast').value);
  const macdSlow  = parseFloat(document.getElementById('mfkk-macd-slow').value);
  const macdHist  = parseFloat(document.getElementById('mfkk-macd-hist').value);
  const adxVal    = parseFloat(document.getElementById('mfkk-adx').value);
  const diPlus    = parseFloat(document.getElementById('mfkk-diplus').value);
  const diMinus   = parseFloat(document.getElementById('mfkk-diminus').value);
  const hasCci = !isNaN(cciVal);
  const hasMacd = !isNaN(macdFast) && !isNaN(macdSlow);
  const hasHist = !isNaN(macdHist);
  const hasAdx = !isNaN(adxVal) && !isNaN(diPlus) && !isNaN(diMinus);

  if(!hasCci && !hasMacd && !hasAdx){
    ['mfkk-num','mfkk-bias','mfkk-circle','mfkk-desc','mfkk-quality'].forEach(id=>{
      const el=document.getElementById(id);
      if(!el)return;
      if(id==='mfkk-num')el.textContent='0';
      if(id==='mfkk-bias'){el.textContent='In attesa di dati...';el.style.color='var(--dim)';}
      if(id==='mfkk-circle'){el.style.strokeDashoffset='163.4';el.style.stroke='var(--dim)';}
      if(id==='mfkk-desc')el.textContent='Caricamento automatico indicatori...';
      if(id==='mfkk-quality')el.style.display='none';
    });
    return;
  }

  // ── CCI SCORE (35%) — CCI_S params: OB=75, OS=25 ──────
  let cciScore=50, cciCol='var(--dim)', cciHint='';
  if(hasCci){
    if(isBuy){
      if(cciVal<=25){cciScore=95;cciCol='var(--green)';cciHint='ZONA OS (<25) — freccia Enter BUY perfetto';}
      else if(cciVal<=35){cciScore=85;cciCol='var(--green)';cciHint='Appena uscito da OS — freccia Exit, entry BUY';}
      else if(cciVal<=50){cciScore=60;cciCol='var(--yellow)';cciHint='Zona centrale — momentum in costruzione';}
      else if(cciVal<=65){cciScore=35;cciCol='var(--yellow)';cciHint='Zona alta — setup rischioso per BUY';}
      else if(cciVal<75){cciScore=15;cciCol='var(--red)';cciHint='Avvicina OB — evita BUY';}
      else{cciScore=0;cciCol='var(--red)';cciHint='ZONA OB (>75) — zona SELL, no BUY';}
    } else {
      if(cciVal>=75){cciScore=95;cciCol='var(--green)';cciHint='ZONA OB (>75) — freccia Enter SELL perfetto';}
      else if(cciVal>=65){cciScore=85;cciCol='var(--green)';cciHint='Appena uscito da OB — freccia Exit, entry SELL';}
      else if(cciVal>=50){cciScore=60;cciCol='var(--yellow)';cciHint='Zona centrale — momentum in costruzione';}
      else if(cciVal>=35){cciScore=35;cciCol='var(--yellow)';cciHint='Zona bassa — setup rischioso per SELL';}
      else if(cciVal>25){cciScore=15;cciCol='var(--red)';cciHint='Avvicina OS — evita SELL';}
      else{cciScore=0;cciCol='var(--red)';cciHint='ZONA OS (<25) — zona BUY, no SELL';}
    }
    const pct=Math.max(0,Math.min(100,cciScore));
    const bar=document.getElementById('mfkk-cci-bar');
    const pp=document.getElementById('mfkk-cci-pct');
    const hint=document.getElementById('mfkk-cci-hint');
    const row=document.getElementById('mfkk-cci-row');
    if(bar){bar.style.width=pct+'%';bar.style.background=cciCol;}
    if(pp){pp.textContent=pct;pp.style.color=cciCol;}
    if(hint)hint.textContent=cciHint;
    if(row)row.style.borderColor=cciScore>=70?cciCol+'55':'var(--border)';
  }

  // ── MACD SCORE (35%) — params: 12,26,9 EMA ─────────────
  let macdScore=50, macdCol='var(--dim)', macdHint='';
  if(hasMacd){
    const diff=macdFast-macdSlow;
    const str=Math.min(Math.abs(diff)/3,1);
    // Histogram adds confirmation: if hist same direction as signal = stronger
    const histBonus=hasHist?((isBuy&&macdHist>0)||((!isBuy)&&macdHist<0)?10:0):0;
    if(isBuy){
      if(diff>0.5){macdScore=Math.round(65+str*25)+histBonus;macdCol='var(--green)';macdHint='BLU>ROSSO +'+diff.toFixed(2)+(hasHist?' Hist:'+macdHist.toFixed(2):'')+(Math.abs(diff)>1?' FORTE':'');}
      else if(diff>0){macdScore=60+histBonus;macdCol='var(--yellow)';macdHint='Appena incrociato BUY'+(hasHist?' · Hist:'+macdHist.toFixed(2):'');}
      else if(diff>-1){macdScore=30;macdCol='var(--yellow)';macdHint='Prossimo cross BUY — attendi';}
      else{macdScore=5;macdCol='var(--red)';macdHint='ROSSO>BLU '+diff.toFixed(2)+' — bearish, no BUY';}
    } else {
      if(diff<-0.5){macdScore=Math.round(65+str*25)+histBonus;macdCol='var(--green)';macdHint='ROSSO>BLU '+diff.toFixed(2)+(hasHist?' Hist:'+macdHist.toFixed(2):'')+(Math.abs(diff)>1?' FORTE':'');}
      else if(diff<0){macdScore=60+histBonus;macdCol='var(--yellow)';macdHint='Appena incrociato SELL'+(hasHist?' · Hist:'+macdHist.toFixed(2):'');}
      else if(diff<1){macdScore=30;macdCol='var(--yellow)';macdHint='Prossimo cross SELL — attendi';}
      else{macdScore=5;macdCol='var(--red)';macdHint='BLU>ROSSO — bullish, no SELL';}
    }
    const pct=Math.max(0,Math.min(100,macdScore));
    const bar=document.getElementById('mfkk-macd-bar');
    const pp=document.getElementById('mfkk-macd-pct');
    const hint=document.getElementById('mfkk-macd-hint');
    const row=document.getElementById('mfkk-macd-row');
    if(bar){bar.style.width=pct+'%';bar.style.background=macdCol;}
    if(pp){pp.textContent=pct;pp.style.color=macdCol;}
    if(hint)hint.textContent=macdHint;
    if(row)row.style.borderColor=macdScore>=70?macdCol+'55':'var(--border)';
  }

  // ── ADX SCORE (30%) — params: period=10, Th=10 ──────────
  let adxScore=50, adxCol='var(--dim)', adxHint='';
  if(hasAdx){
    const diDiff=diPlus-diMinus;
    const diSpread=Math.abs(diDiff);
    const spreadBonus=Math.min(diSpread/20,1);
    let adxStr=adxVal>=35?1.0:adxVal>=27?0.85:adxVal>=20?0.65:adxVal>=14?0.4:adxVal>=10?0.2:0.05;
    if(isBuy){
      if(diDiff>0&&adxVal>=25){
        adxScore=Math.round(60+adxStr*25+spreadBonus*15);adxCol='var(--green)';
        adxHint='DI+('+diPlus.toFixed(1)+')>DI-('+diMinus.toFixed(1)+') gap '+diSpread.toFixed(1)+' · ADX '+adxVal.toFixed(1)+' '+(adxVal>=30?'FORTE':'mod.');
      } else if(diDiff>0&&adxVal>=10){
        adxScore=50;adxCol='var(--yellow)';adxHint='DI+>DI- · ADX '+adxVal.toFixed(1)+' (sopra Th=10, < 25) trend nascente';
      } else if(diDiff>0){
        adxScore=30;adxCol='var(--yellow)';adxHint='DI+>DI- ma ADX '+adxVal.toFixed(1)+' < Th=10 — laterale';
      } else {
        adxScore=5;adxCol='var(--red)';adxHint='DI-('+diMinus.toFixed(1)+')>DI+('+diPlus.toFixed(1)+') — bearish, no BUY';
      }
    } else {
      if(diDiff<0&&adxVal>=25){
        adxScore=Math.round(60+adxStr*25+spreadBonus*15);adxCol='var(--green)';
        adxHint='DI-('+diMinus.toFixed(1)+')>DI+('+diPlus.toFixed(1)+') gap '+diSpread.toFixed(1)+' · ADX '+adxVal.toFixed(1)+' '+(adxVal>=30?'FORTE':'mod.');
      } else if(diDiff<0&&adxVal>=10){
        adxScore=50;adxCol='var(--yellow)';adxHint='DI->DI+ · ADX '+adxVal.toFixed(1)+' (sopra Th=10, < 25) trend nascente';
      } else if(diDiff<0){
        adxScore=30;adxCol='var(--yellow)';adxHint='DI->DI+ ma ADX '+adxVal.toFixed(1)+' < Th=10 — laterale';
      } else {
        adxScore=5;adxCol='var(--red)';adxHint='DI+('+diPlus.toFixed(1)+')>DI-('+diMinus.toFixed(1)+') — bullish, no SELL';
      }
    }
    adxScore=Math.max(0,Math.min(100,adxScore));
    const bar=document.getElementById('mfkk-adx-bar');
    const pp=document.getElementById('mfkk-adx-pct');
    const hint=document.getElementById('mfkk-adx-hint');
    const row=document.getElementById('mfkk-adx-row');
    if(bar){bar.style.width=adxScore+'%';bar.style.background=adxCol;}
    if(pp){pp.textContent=adxScore;pp.style.color=adxCol;}
    if(hint)hint.textContent=adxHint;
    if(row)row.style.borderColor=adxScore>=70?adxCol+'55':'var(--border)';
  }

  // ── WEIGHTED TOTAL ─────────────────────────────────────
  let tot=0, w=0;
  if(hasCci){tot+=cciScore*0.35;w+=0.35;}
  if(hasMacd){tot+=macdScore*0.35;w+=0.35;}
  if(hasAdx){tot+=adxScore*0.30;w+=0.30;}
  const score=w>0?Math.round(tot/w):0;
  const allThree=hasCci&&hasMacd&&hasAdx;
  const strong=[hasCci&&cciScore>=70,hasMacd&&macdScore>=70,hasAdx&&adxScore>=70].filter(Boolean).length;
  const weak=[hasCci&&cciScore<=30,hasMacd&&macdScore<=30,hasAdx&&adxScore<=30].filter(Boolean).length;
  const col=score>=75?'var(--green)':score>=55?'var(--yellow)':score>=40?'var(--yellow)':'var(--red)';
  const dirLabel=isBuy?'BUY':'SELL';
  let bias='', desc='';
  if(score>=80&&allThree&&strong>=3){bias=dirLabel+' FORTE';desc='Tutti e 3 gli indicatori allineati — segnale ad alta probabilità';}
  else if(score>=70&&strong>=2){bias=dirLabel+' VALIDO';desc='2/3 indicatori confermano — buona confluenza';}
  else if(score>=55){bias=dirLabel+' PARZIALE';desc='Segnale parziale — attendi ulteriori conferme';}
  else if(score>=40){bias='NEUTRO';desc='Indicatori misti — evita entries adesso';}
  else{bias='CONTRO '+dirLabel;desc='Segnale contro la direzione — no trade';}

  // Render
  const DASH=163.4;
  const circ=document.getElementById('mfkk-circle');
  if(circ){circ.style.strokeDashoffset=DASH*(1-score/100);circ.style.stroke=col;}
  const num=document.getElementById('mfkk-num');
  if(num){num.textContent=score;num.style.color=col;}
  const bel=document.getElementById('mfkk-bias');
  if(bel){bel.textContent=bias;bel.style.color=col;}
  const del=document.getElementById('mfkk-desc');
  if(del)del.textContent=desc;
  const qel=document.getElementById('mfkk-quality');
  if(qel){
    if(score>=80&&allThree&&strong>=3){
      qel.style.cssText='display:block;background:#00e67615;border:1px solid #00e67630;color:var(--green)';
      qel.textContent='CONFLUENZA PERFETTA — Tutti gli indicatori allineati';
    } else if(weak>=2){
      qel.style.cssText='display:block;background:#ff475715;border:1px solid #ff475730;color:var(--red)';
      qel.textContent='SEGNALE DEBOLE — Aspetta allineamento indicatori';
    } else if(score>=70&&!allThree){
      qel.style.cssText='display:block;background:#ffca2810;border:1px solid #ffca2825;color:var(--yellow)';
      qel.textContent='Dati parziali — inserisci tutti e 3 per score completo';
    } else {
      qel.style.display='none';
    }
  }
  const tel=document.getElementById('mfkk-time');
  if(tel)tel.textContent=new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});
  dashContext.mfkk={score,dir:dirLabel,bias,cciScore,macdScore,adxScore,allThree,strongSignals:strong};
}

// Auto-calculate both directions and pick the best one
function autoSelectBestDir(){
  // Check if any values are actually populated
  const cci = parseFloat(document.getElementById('mfkk-cci')?.value);
  const macd = parseFloat(document.getElementById('mfkk-macd-fast')?.value);
  const adx = parseFloat(document.getElementById('mfkk-adx')?.value);
  if(isNaN(cci) && isNaN(macd) && isNaN(adx)) return; // no data yet

  const origDir = mfkkDir;

  // Calculate BUY score without side effects
  mfkkDir='buy';
  document.getElementById('mfkk-buy').className='mfkk-dir on-buy';
  document.getElementById('mfkk-sell').className='mfkk-dir';
  calcMfkk();
  const buyScore = dashContext.mfkk?.score || 0;

  // Calculate SELL score
  mfkkDir='sell';
  document.getElementById('mfkk-buy').className='mfkk-dir';
  document.getElementById('mfkk-sell').className='mfkk-dir on-sell';
  calcMfkk();
  const sellScore = dashContext.mfkk?.score || 0;

  // Keep best
  const best = sellScore > buyScore ? 'sell' : 'buy';
  mfkkDir = best;
  document.getElementById('mfkk-buy').className='mfkk-dir'+(best==='buy'?' on-buy':'');
  document.getElementById('mfkk-sell').className='mfkk-dir'+(best==='sell'?' on-sell':'');
  calcMfkk();
  console.log('MFKK auto-dir: BUY='+buyScore+' SELL='+sellScore+' → '+best.toUpperCase());
}
