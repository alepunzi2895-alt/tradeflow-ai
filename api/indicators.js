export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  const tf = (req.query?.tf || '1h').toLowerCase();
  const resolution = tf === '1d' ? 'D' : tf === '4h' ? '240' : '60';
  const interval   = tf === '1d' ? '1d' : '1h';
  const COUNT = 300;

  async function fetchT(url, opts = {}, ms = 8000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try { const r = await fetch(url, { ...opts, signal: ctrl.signal }); clearTimeout(tid); return r; }
    catch(e) { clearTimeout(tid); throw e; }
  }

  // ── Math helpers — exact TradingView Pine Script behaviour ─────────────────
  // ta.ema(): seed = first value (NOT SMA of first N)
  const ema = (src, p) => {
    const k = 2/(p+1); let v = src[0]; const o = [v];
    for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
    return o;
  };
  const hi = (a,p,i)=>{ let m=-Infinity; for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.max(m,a[j]); return m; };
  const lo = (a,p,i)=>{ let m=Infinity;  for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.min(m,a[j]); return m; };
  // sma: null-propagating (matches Pine Script na behaviour)
  const sma = (src, p) => {
    const o=new Array(src.length).fill(null);
    for(let i=p-1;i<src.length;i++){
      const sl=src.slice(i-p+1,i+1);
      if(sl.some(v=>v==null)){o[i]=null;continue;}
      o[i]=sl.reduce((a,b)=>a+b,0)/p;
    }
    return o;
  };

  // ── Compute CCI_S from candles (can't get this from TV Scanner directly) ───
  function computeCCIS(candles) {
    if(candles.length < 120) return null;
    const C=candles.map(x=>x.c), n=C.length;
    const CP=50, SP=50, SK=8, SD=8;
    // CCI(close,50)
    const cci=new Array(n).fill(null);
    for(let i=CP-1;i<n;i++){
      const sl=C.slice(i-CP+1,i+1);
      const mn=sl.reduce((a,b)=>a+b,0)/CP;
      const md=sl.reduce((a,b)=>a+Math.abs(b-mn),0)/CP;
      cci[i]=md===0?0:(C[i]-mn)/(0.015*md);
    }
    // stoch(cci,cci,cci,50)
    const stk=new Array(n).fill(null);
    for(let i=CP+SP-2;i<n;i++){
      if(cci[i]==null) continue;
      const lv=lo(cci,SP,i), hv=hi(cci,SP,i);
      stk[i]=(hv-lv)===0?50:((cci[i]-lv)/(hv-lv))*100;
    }
    // SMA(K,8) then SMA(D,8) — null-propagating like Pine Script
    const stk_k=sma(stk, SK);
    const stk_d=sma(stk_k, SD);
    const cv=stk_d[n-1]??50, cp=stk_d[n-2]??50;
    let cciSig='neutral';
    if(cp>=25&&cv<25)cciSig='enter_buy';
    else if(cp<=75&&cv>75)cciSig='enter_sell';
    else if(cp>75&&cv<=75)cciSig='exit_sell';
    else if(cp<25&&cv>=25)cciSig='exit_buy';
    return { cv, cciSig };
  }

  // ── SOURCE A: TV Scanner — exact TV values for MACD(12,26,9) and ADX ───────
  // Uses OANDA:XAUUSD (same data TV uses) with H1 column suffix |60
  // ADX Note: TV Scanner returns built-in ADX (Wilder RMA), not SMA version.
  // MACD Note: TV Scanner MACD.macd uses default 12,26,9 — exact match.
  async function fetchTVScannerIndicators() {
    const tickers = ['OANDA:XAUUSD','FOREXCOM:XAUUSD','PEPPERSTONE:XAUUSD'];
    const body = {
      symbols: { tickers, query: { types: [] } },
      columns: [
        'close|60',
        'MACD.macd|60', 'MACD.signal|60', 'MACD.hist|60',
        'ADX[10]|60', 'plus_di[10]|60', 'minus_di[10]|60',
        'CCI[50]|60'
      ]
    };
    try {
      const r = await fetchT('https://scanner.tradingview.com/global/scan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          'Origin': 'https://www.tradingview.com',
          'Referer': 'https://www.tradingview.com/'
        },
        body: JSON.stringify(body)
      }, 7000);
      if(!r.ok) return null;
      const d = await r.json();
      const item = d.data?.find(x => x.d && x.d[0]!=null && !isNaN(+x.d[0]));
      if(!item) return null;
      const [close, macdLine, macdSig, macdHist, adx, diPlus, diMinus, cci50] = item.d;
      if(macdLine==null || adx==null) return null;
      console.log(`TV Scanner: ${item.s} MACD=${(+macdLine).toFixed(2)} ADX=${(+adx).toFixed(2)} DI+=${(+diPlus).toFixed(2)}`);
      return { close:+close, macdLine:+macdLine, macdSig:+macdSig, macdHist:+macdHist,
               adx:+adx, diPlus:+diPlus, diMinus:+diMinus, cci50:+cci50, source:item.s };
    } catch(e){ console.log('TV Scanner indicators:', e.message); return null; }
  }

  // ── SOURCE B: TV History API — exact candles for CCI_S ────────────────────
  async function fetchTVCandles(){
    const now=Math.floor(Date.now()/1000);
    const from=now-COUNT*(resolution==='D'?86400:resolution==='240'?14400:3600)-86400;
    for(const sym of ['OANDA:XAUUSD','FOREXCOM:XAUUSD','PEPPERSTONE:XAUUSD']){
      try{
        const url=`https://data.tradingview.com/history?symbol=${encodeURIComponent(sym)}&resolution=${resolution}&from=${from}&to=${now}&countback=${COUNT}`;
        const r=await fetchT(url,{headers:{'User-Agent':'Mozilla/5.0','Origin':'https://www.tradingview.com','Referer':'https://www.tradingview.com/'}},6000);
        if(!r.ok) continue;
        const d=await r.json();
        if(d.s!=='ok'||!d.t?.length) continue;
        const candles=[];
        for(let i=0;i<d.t.length;i++) if(d.c[i]!=null&&d.h[i]!=null&&d.l[i]!=null) candles.push({t:d.t[i],h:d.h[i],l:d.l[i],c:d.c[i]});
        if(candles.length<120) continue;
        console.log(`TV history OK: ${sym} ${candles.length} candles`);
        return {candles, source:'tradingview_'+sym};
      }catch(e){console.log(`TV history ${sym}:`,e.message);}
    }
    return null;
  }

  // ── SOURCE C: Yahoo Finance SPOT gold (XAUUSD=X) — NOT futures GC=F ────────
  // XAUUSD=X is spot gold, much closer to OANDA:XAUUSD than GC=F futures
  async function fetchYahooSpotCandles(){
    try{
      const range = tf==='1d'?'60d':'14d';
      const r=await fetchT(
        `https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X?interval=${interval}&range=${range}`,
        {headers:{'User-Agent':'Mozilla/5.0'}}
      );
      if(!r.ok) return null;
      const d=await r.json();
      const rs=d?.chart?.result?.[0]; if(!rs?.timestamp) return null;
      const q=rs.indicators?.quote?.[0]||{};
      const candles=[];
      for(let i=0;i<rs.timestamp.length;i++)
        if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null)
          candles.push({t:rs.timestamp[i],h:q.high[i],l:q.low[i],c:q.close[i]});
      if(candles.length<120) return null;
      console.log(`Yahoo XAUUSD=X: ${candles.length} candles, last=$${candles.at(-1).c.toFixed(2)}`);
      return {candles, source:'yahoo_XAUUSD=X'};
    }catch(e){console.log('Yahoo XAUUSD=X:',e.message); return null;}
  }

  try {
    // Run TV Scanner (for exact MACD/ADX) and candle fetch in parallel
    const [scannerResult, candles_tv] = await Promise.all([
      fetchTVScannerIndicators(),
      fetchTVCandles()
    ]);

    // Get candles: TV first, then Yahoo spot (NEVER futures GC=F)
    const candleResult = candles_tv || await fetchYahooSpotCandles();
    if(!candleResult) return res.status(503).json({ok:false, error:'No candle data available'});

    let {candles, source:candleSource} = candleResult;

    if(tf==='4h'){
      const map=new Map();
      for(const c of candles){
        const d=new Date(c.t*1000),b=Math.floor(d.getUTCHours()/4)*4;
        const k=`${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}-${b}`;
        if(!map.has(k)) map.set(k,{t:c.t,h:c.h,l:c.l,c:c.c});
        else{const e=map.get(k);e.h=Math.max(e.h,c.h);e.l=Math.min(e.l,c.l);e.c=c.c;e.t=c.t;}
      }
      candles=[...map.values()].sort((a,b)=>a.t-b.t);
    }

    if(candles.length<120) return res.status(503).json({ok:false, error:'Insufficient candles: '+candles.length});

    // Compute CCI_S from candle data (TV Scanner doesn't have CCI_S stochastic)
    const cciResult = computeCCIS(candles);
    if(!cciResult) return res.status(503).json({ok:false, error:'CCI_S computation failed'});
    const {cv, cciSig} = cciResult;

    // Use TV Scanner values for MACD and ADX if available (exact TV values)
    // Fall back to computing from candles if Scanner fails
    let mv, sv, hv_val, hp, crossVal, adxVal, diPlusV, diMinusV, macdSource;

    if(scannerResult){
      // EXACT values from TradingView OANDA:XAUUSD H1
      mv = scannerResult.macdLine;
      sv = scannerResult.macdSig;
      hv_val = scannerResult.macdHist;
      hp = 0; // hist_prev not available from scanner
      crossVal = mv > sv ? (mv > 0 ? 'above' : 'cross_buy') : (mv < 0 ? 'below' : 'cross_sell');
      adxVal   = scannerResult.adx;
      diPlusV  = scannerResult.diPlus;
      diMinusV = scannerResult.diMinus;
      macdSource = 'tv_scanner_'+scannerResult.source;
      console.log(`Using TV Scanner: MACD=${mv.toFixed(2)} Signal=${sv.toFixed(2)} ADX=${adxVal.toFixed(2)}`);
    } else {
      // Fallback: compute from candles
      const C=candles.map(x=>x.c), n=C.length;
      const H=candles.map(x=>x.h), L=candles.map(x=>x.l);
      // MACD(12,26,9) EMA
      const eFast=ema(C,12), eSlow=ema(C,26);
      const ml=eFast.map((v,i)=>v-eSlow[i]);
      const sg=ema(ml,9);
      const hist=ml.map((v,i)=>v-sg[i]);
      mv=ml[n-1]; sv=sg[n-1]; hv_val=hist[n-1]; hp=hist[n-2]||0;
      crossVal=mv>sv?'above':'below';
      if((ml[n-2]||0)<=(sg[n-2]||0)&&mv>sv) crossVal='cross_buy';
      else if((ml[n-2]||0)>=(sg[n-2]||0)&&mv<sv) crossVal='cross_sell';
      // ADX(10): Wilder smooth TR/DM, then SMA(DX,10)
      const AP=10;
      const TR=new Array(n).fill(0),DMP=new Array(n).fill(0),DMM=new Array(n).fill(0);
      for(let i=1;i<n;i++){
        TR[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));
        const u=H[i]-H[i-1],d=L[i-1]-L[i];
        DMP[i]=(u>d&&u>0)?u:0; DMM[i]=(d>u&&d>0)?d:0;
      }
      const sTR=new Array(n).fill(0),sDMP=new Array(n).fill(0),sDMM=new Array(n).fill(0);
      for(let i=1;i<n;i++){sTR[i]=sTR[i-1]-sTR[i-1]/AP+TR[i];sDMP[i]=sDMP[i-1]-sDMP[i-1]/AP+DMP[i];sDMM[i]=sDMM[i-1]-sDMM[i-1]/AP+DMM[i];}
      const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
      const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
      const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
      const ADX=sma(DX,AP);
      adxVal=ADX[n-1]??0; diPlusV=DIP[n-1]; diMinusV=DIM[n-1];
      macdSource = candleSource;
    }

    const C=candles.map(x=>x.c), n=C.length;
    const candle_data=candles.slice(-300).map(x=>({t:x.t,h:+x.h.toFixed(2),l:+x.l.toFixed(2),c:+x.c.toFixed(2)}));

    console.log(`OK | CCI_S=${cv.toFixed(2)}[${candleSource}] MACD=${mv.toFixed(2)}[${macdSource}] ADX=${(adxVal??0).toFixed(2)}`);

    return res.status(200).json({
      ok:true, timeframe:tf,
      timestamp:new Date().toISOString(),
      last_candle:new Date(candles.at(-1).t*1000).toISOString(),
      last_close:+C[n-1].toFixed(2),
      candles:n, candle_data,
      source:candleSource, macd_source:macdSource,
      cci:{value:+cv.toFixed(2),signal:cciSig,zone:cv>75?'overbought':cv<25?'oversold':'neutral',ob:75,os:25},
      macd:{macd:+mv.toFixed(4),signal:+sv.toFixed(4),histogram:+hv_val.toFixed(4),hist_prev:+(hp||0).toFixed(4),hist_rising:hv_val>(hp||0),cross:crossVal,diff:+(mv-sv).toFixed(4)},
      adx:{adx:+(adxVal??0).toFixed(2),di_plus:+diPlusV.toFixed(2),di_minus:+diMinusV.toFixed(2),threshold:10,trending:(adxVal??0)>10,strong:(adxVal??0)>25}
    });
  } catch(e){
    console.error('Indicators:', e.message);
    return res.status(500).json({ok:false, error:e.message});
  }
}
