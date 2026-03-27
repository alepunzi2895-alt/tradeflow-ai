export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  const tf = (req.query?.tf || '1h').toLowerCase();
  const interval = tf === '1d' ? '1d' : '1h';
  // 3 days = ~72 H1 candles — enough for CCI(28)+MACD(26)+ADX(10) with warmup
  const range = tf === '1d' ? '60d' : '7d'; // 7d = ~168 H1 candles, enough for CCI(28)+Stoch(28)+SMA(8)+SMA(8)=72 warmup

  const SYMBOLS = ['XAUUSD=X', 'GC=F', 'GLD']; // XAUUSD spot first (closer to broker prices)

  async function fetch1(sym) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 8000);
    try {
      const r = await fetch(
        `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=${interval}&range=${range}`,
        { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }, signal: ctrl.signal }
      );
      clearTimeout(tid);
      if (!r.ok) return null;
      const d = await r.json();
      const rs = d?.chart?.result?.[0];
      if (!rs?.timestamp) return null;
      const q = rs.indicators?.quote?.[0] || {};
      const candles = [];
      for (let i = 0; i < rs.timestamp.length; i++) {
        if (q.close[i]!=null && q.high[i]!=null && q.low[i]!=null)
          candles.push({ t:rs.timestamp[i], h:q.high[i], l:q.low[i], c:q.close[i] });
      }
      if (candles.length < 30) return null;
      console.log(`${sym}: ${candles.length} candles, last=$${candles.at(-1).c.toFixed(2)}`);
      return candles;
    } catch(e) { clearTimeout(tid); return null; }
  }

  try {
    let raw = null;
    for (const sym of SYMBOLS) { raw = await fetch1(sym); if (raw) break; }
    if (!raw) return res.status(503).json({ ok:false, error:'Yahoo Finance non disponibile' });

    // Resample H1 → H4
    let candles = raw;
    if (tf === '4h') {
      const map = new Map();
      for (const c of raw) {
        const d = new Date(c.t * 1000);
        const b = Math.floor(d.getUTCHours()/4)*4;
        const k = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}-${b}`;
        if (!map.has(k)) map.set(k, {t:c.t,h:c.h,l:c.l,c:c.c});
        else { const e=map.get(k); e.h=Math.max(e.h,c.h); e.l=Math.min(e.l,c.l); e.c=c.c; e.t=c.t; }
      }
      candles = [...map.values()].sort((a,b)=>a.t-b.t);
    }

    if (candles.length < 30) return res.status(503).json({ ok:false, error:'Candele insufficienti: '+candles.length });

    const H=candles.map(x=>x.h), L=candles.map(x=>x.l), C=candles.map(x=>x.c), n=C.length;

    const ema=(src,p)=>{const k=2/(p+1);let v=src[0];const o=[v];for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}return o;};
    const sma=(src,p)=>{const o=new Array(src.length).fill(null);for(let i=p-1;i<src.length;i++){let s=0;for(let j=0;j<p;j++)s+=(src[i-j]||0);o[i]=s/p;}return o;};
    const hi=(a,p,i)=>{let m=-Infinity;for(let j=Math.max(0,i-p+1);j<=i;j++)if(a[j]!=null)m=Math.max(m,a[j]);return m;};
    const lo=(a,p,i)=>{let m=Infinity; for(let j=Math.max(0,i-p+1);j<=i;j++)if(a[j]!=null)m=Math.min(m,a[j]);return m;};

    // CCI_S exact Pine Script: source=close (NOT typical price)
    const CP=28, SP=28, SK=8, SD=8;
    // cci(close,28): use close as source, not (H+L+C)/3
    const cci=new Array(n).fill(null);
    for(let i=CP-1;i<n;i++){const sl=C.slice(i-CP+1,i+1);const mn=sl.reduce((a,b)=>a+b,0)/CP;const md=sl.reduce((a,b)=>a+Math.abs(b-mn),0)/CP;cci[i]=md===0?0:(C[i]-mn)/(0.015*md);}
    const stk=new Array(n).fill(null);
    for(let i=CP+SP-2;i<n;i++){if(cci[i]==null)continue;const lv=lo(cci,SP,i),hv=hi(cci,SP,i);stk[i]=(hv-lv)===0?50:((cci[i]-lv)/(hv-lv))*100;}
    const stk_k=sma(stk.map(v=>v??50),SK);
    const stk_d=sma(stk_k.map(v=>v??50),SD);
    const cv=stk_d[n-1]??50, cp=stk_d[n-2]??50;
    let cciSig='neutral';
    if(cp>=25&&cv<25)cciSig='enter_buy';
    else if(cp<=75&&cv>75)cciSig='enter_sell';
    else if(cp>75&&cv<=75)cciSig='exit_sell';
    else if(cp<25&&cv>=25)cciSig='exit_buy';

    // MACD
    const e12=ema(C,Math.min(12,n-1)),e26=ema(C,Math.min(26,n-1));
    const ml=e12.map((v,i)=>v-e26[i]);
    const sg=ema(ml,Math.min(9,n-1));
    const hist=ml.map((v,i)=>v-sg[i]);
    const mv=ml[n-1],sv=sg[n-1],hv=hist[n-1],hp=hist[n-2]||0;
    let cross=mv>sv?'above':'below';
    if((ml[n-2]||0)<=(sg[n-2]||0)&&mv>sv)cross='cross_buy';
    else if((ml[n-2]||0)>=(sg[n-2]||0)&&mv<sv)cross='cross_sell';

    // ADX
    const AP=10;
    const TR=new Array(n).fill(0),DMP=new Array(n).fill(0),DMM=new Array(n).fill(0);
    for(let i=1;i<n;i++){TR[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));DMP[i]=H[i]-H[i-1]>L[i-1]-L[i]?Math.max(H[i]-H[i-1],0):0;DMM[i]=L[i-1]-L[i]>H[i]-H[i-1]?Math.max(L[i-1]-L[i],0):0;}
    const sTR=new Array(n).fill(0),sDMP=new Array(n).fill(0),sDMM=new Array(n).fill(0);
    sTR[0]=TR[0];sDMP[0]=DMP[0];sDMM[0]=DMM[0];
    for(let i=1;i<n;i++){sTR[i]=sTR[i-1]-sTR[i-1]/AP+TR[i];sDMP[i]=sDMP[i-1]-sDMP[i-1]/AP+DMP[i];sDMM[i]=sDMM[i-1]-sDMM[i-1]/AP+DMM[i];}
    const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
    const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
    const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
    const ADX=sma(DX,AP);

    // Always include recent candle data for client-side live recalc
    const candle_data = candles.slice(-150).map(x=>({t:x.t,h:+x.h.toFixed(2),l:+x.l.toFixed(2),c:+x.c.toFixed(2)}));

    return res.status(200).json({
      ok:true, timeframe:tf,
      timestamp:new Date().toISOString(),
      last_candle:new Date(candles.at(-1).t*1000).toISOString(),
      last_close:+C[n-1].toFixed(2),
      candles:n,
      candle_data,
      cci:{value:+cv.toFixed(2),signal:cciSig,zone:cv>75?'overbought':cv<25?'oversold':'neutral',ob:75,os:25},
      macd:{macd:+mv.toFixed(4),signal:+sv.toFixed(4),histogram:+hv.toFixed(4),hist_prev:+hp.toFixed(4),hist_rising:hv>hp,cross,diff:+(mv-sv).toFixed(4)},
      adx:{adx:+ADX[n-1].toFixed(2),di_plus:+DIP[n-1].toFixed(2),di_minus:+DIM[n-1].toFixed(2),threshold:10,trending:ADX[n-1]>10,strong:ADX[n-1]>25}
    });
  } catch(e) {
    console.error('Indicators:', e.message);
    return res.status(500).json({ ok:false, error:e.message });
  }
}
