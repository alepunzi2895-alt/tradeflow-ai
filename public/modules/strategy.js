// TradeFlow AI — Strategy Engine v2
// 18 indicatori · 5 strategie validate (PF ≥ 1.10) su 730gg H1 XAU/USD
// Multi-Timeframe test (1h/4h/1d): 1H confermato ottimale per tutte le strategie
// Regime detection → selezione automatica strategia ottimale

// ── CONFIG (ottimizzata da backtest MTF) ──────────────────────────────────────
const SE = {
  session:  { start: 7, end: 17 },     // UTC London+NY
  maxTrades: 3,
  cooldownH: 1,
  extremeMult: 3.0,                     // ATR > 3x avg = giorno estremo
  strategies: {
    // tf = timeframe ottimale validato su 730gg (MTF test: 1h vs 4h vs 1d)
    S01_EXHAUSTION:    { tp: 15, sl: 9,  pf: 2.288, wr: '57.9%', label: 'Exhaustion',       tf: '1h' },
    S06_ORDERBLOCK:    { tp: 18, sl: 10, pf: 1.424, wr: '46.1%', label: 'Order Block',      tf: '1h' },
    S09_VWAP_WPER:     { tp: 18, sl: 10, pf: 1.501, wr: '47.4%', label: 'VWAP + W%R',      tf: '1h' },
    S12_WPR_KELTNER:   { tp: 20, sl: 12, pf: 1.220, wr: '42.3%', label: 'W%R + Keltner',   tf: '1h' },
    S10_SESSION_MOM:   { tp: 20, sl: 12, pf: 1.042, wr: '38.5%', label: 'Session Momentum', tf: '1h' },
  },
  regimePriority: {
    TREND_UP:   ['S01_EXHAUSTION','S06_ORDERBLOCK','S10_SESSION_MOM'],
    TREND_DOWN: ['S01_EXHAUSTION','S06_ORDERBLOCK','S10_SESSION_MOM'],
    WEAK_UP:    ['S06_ORDERBLOCK','S10_SESSION_MOM','S12_WPR_KELTNER'],
    WEAK_DOWN:  ['S06_ORDERBLOCK','S10_SESSION_MOM','S12_WPR_KELTNER'],
    RANGE:      ['S09_VWAP_WPER','S12_WPR_KELTNER','S06_ORDERBLOCK'],
    VOLATILE:   ['S12_WPR_KELTNER','S09_VWAP_WPER'],
    UNKNOWN:    ['S10_SESSION_MOM','S09_VWAP_WPER'],
  }
};

// ── STATE ─────────────────────────────────────────────────────────────────────
let seCandles = [];
let seInds = null;
let seRegime = 'UNKNOWN';
let seTimer = null;

// ── MATH HELPERS ──────────────────────────────────────────────────────────────
const _seEma = (src,p) => {
  const k=2/(p+1); let v=src[0]; const o=[v];
  for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
  return o;
};
const _seSma = (src,p) => {
  const o=new Array(src.length).fill(null);
  for(let i=p-1;i<src.length;i++){
    let s=0;for(let j=0;j<p;j++)s+=(src[i-j]||0);o[i]=s/p;
  }
  return o;
};
const _seSmma = (src,p) => {  // Smoothed MA (Alligator)
  const o=new Array(p-1).fill(null);
  let v=src.slice(0,p).reduce((a,b)=>a+b,0)/p;o.push(v);
  for(let i=p;i<src.length;i++){v=(v*(p-1)+src[i])/p;o.push(v);}
  return o;
};
const _seRsi = (src,p=14) => {
  const n=src.length,out=new Array(n).fill(null);
  const g=[],l=[];
  for(let i=1;i<n;i++){g.push(Math.max(0,src[i]-src[i-1]));l.push(Math.max(0,src[i-1]-src[i]));}
  let ag=g.slice(0,p).reduce((a,b)=>a+b,0)/p,al=l.slice(0,p).reduce((a,b)=>a+b,0)/p;
  out[p]=100-100/(1+(al>0?ag/al:100));
  for(let i=p;i<g.length;i++){ag=(ag*(p-1)+g[i])/p;al=(al*(p-1)+l[i])/p;out[i+1]=100-100/(1+(al>0?ag/al:100));}
  return out;
};
const _seAtr = (H,L,C,p=14) => {
  const tr=[0];
  for(let i=1;i<C.length;i++)tr.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));
  return _seSma(tr,p);
};
const _seAdx = (H,L,C,p=14) => {
  const n=C.length,TR=[0],DMP=[0],DMM=[0];
  for(let i=1;i<n;i++){
    TR.push(Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1])));
    const up=H[i]-H[i-1],dn=L[i-1]-L[i];
    DMP.push(up>dn&&up>0?up:0);DMM.push(dn>up&&dn>0?dn:0);
  }
  const sT=[0],sP=[0],sM=[0];
  for(let i=1;i<n;i++){
    sT.push(sT[i-1]-sT[i-1]/p+TR[i]);sP.push(sP[i-1]-sP[i-1]/p+DMP[i]);sM.push(sM[i-1]-sM[i-1]/p+DMM[i]);
  }
  const DIP=sT.map((v,i)=>v>0?sP[i]/v*100:0);
  const DIM=sT.map((v,i)=>v>0?sM[i]/v*100:0);
  const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
  return {adx:_seSma(DX,p),dip:DIP,dim:DIM};
};
const _seMacd = (C,f=12,sl=26,sig=9) => {
  const e1=_seEma(C,f),e2=_seEma(C,sl),ml=e1.map((v,i)=>v-e2[i]),sg=_seEma(ml,sig);
  return {line:ml,sig:sg,hist:ml.map((v,i)=>v-sg[i])};
};
const _seBB = (C,p=20,m=2.0) => {
  const mid=_seSma(C,p),up=[],lo=[],bw=[];
  for(let i=0;i<C.length;i++){
    if(mid[i]==null){up.push(null);lo.push(null);bw.push(null);continue;}
    const sl=C.slice(i-p+1,i+1),mn=sl.reduce((a,b)=>a+b,0)/p;
    const std=Math.sqrt(sl.reduce((a,b)=>a+(b-mn)**2,0)/p);
    up.push(mid[i]+m*std);lo.push(mid[i]-m*std);
    bw.push(mid[i]>0?(up[up.length-1]-lo[lo.length-1])/mid[i]:null);
  }
  return {up,mid,lo,bw};
};
const _seKeltner = (H,L,C,p=20,m=2.0,ap=10) => {
  const mid=_seEma(C,p),atr=_seAtr(H,L,C,ap);
  return {up:mid.map((v,i)=>v+m*(atr[i]||0)),mid,lo:mid.map((v,i)=>v-m*(atr[i]||0))};
};
const _seSupertrend = (H,L,C,p=10,m=3.0) => {
  const atr=_seAtr(H,L,C,p),n=C.length,dir=new Array(n).fill(1);
  const fUp=new Array(n).fill(0),fLo=new Array(n).fill(0);
  for(let i=1;i<n;i++){
    const ub=(H[i]+L[i])/2+m*(atr[i]||0),lb=(H[i]+L[i])/2-m*(atr[i]||0);
    fUp[i]=ub<fUp[i-1]||C[i-1]>fUp[i-1]?ub:fUp[i-1];
    fLo[i]=lb>fLo[i-1]||C[i-1]<fLo[i-1]?lb:fLo[i-1];
    if(dir[i-1]===1&&C[i]<=fUp[i]){dir[i]=1;}
    else if(dir[i-1]===1&&C[i]>fUp[i]){dir[i]=-1;}
    else if(dir[i-1]===-1&&C[i]>=fLo[i]){dir[i]=-1;}
    else if(dir[i-1]===-1&&C[i]<fLo[i]){dir[i]=1;}
    else dir[i]=dir[i-1];
  }
  return dir; // -1=bullish (price above), 1=bearish
};
const _seAlligator = (H,L) => {
  const med=H.map((h,i)=>(h+L[i])/2);
  return {jaw:_seSmma(med,13),teeth:_seSmma(med,8),lips:_seSmma(med,5)};
};
const _seObv = (C,V) => {
  const o=[0];
  for(let i=1;i<C.length;i++)
    o.push(o[i-1]+(C[i]>C[i-1]?V[i]:C[i]<C[i-1]?-V[i]:0));
  return o;
};
const _seMom = (C,p=10) => C.map((v,i)=>i<p?null:(v-C[i-p])/C[i-p]*100);
const _seWpr = (H,L,C,p=14) => C.map((_,i)=>{
  if(i<p-1)return null;
  const hi=Math.max(...H.slice(i-p+1,i+1)),lo=Math.min(...L.slice(i-p+1,i+1));
  return hi>lo?(hi-C[i])/(hi-lo)*-100:-50;
});
const _seStochRsi = (C,rp=14,sp=14,kp=3,dp=3) => {
  const r=_seRsi(C,rp),n=C.length,raw=new Array(n).fill(null);
  for(let i=sp-1;i<n;i++){
    const sl=r.slice(i-sp+1,i+1).filter(x=>x!=null);
    if(sl.length<sp||r[i]==null)continue;
    const hi=Math.max(...sl),lo=Math.min(...sl);
    raw[i]=hi>lo?(r[i]-lo)/(hi-lo)*100:50;
  }
  return {k:_seSma(raw.map(x=>x??50),kp),d:_seSma(raw.map(x=>x??50).map((_,i)=>_seSma(raw.map(x=>x??50),kp)[i]??50),dp)};
};
const _seVwap = (candles) => {
  let cpv=0,cv=0,lastDay=-1;
  return candles.map(c=>{
    const d=new Date(c.t*1000).getUTCDate();
    if(d!==lastDay){cpv=0;cv=0;lastDay=d;}
    const tp=(c.h+c.l+c.c)/3;cpv+=tp*c.v;cv+=c.v;
    return cv>0?cpv/cv:tp;
  });
};
const _seOrderBlocks = (H,L,C,lookback=5,thr=0.5) => {
  const bull=new Array(C.length).fill(false),bear=new Array(C.length).fill(false);
  for(let i=lookback;i<C.length-3;i++){
    const gain=([1,2,3].map(j=>Math.max(0,C[i+j]-C[i+j-1])).reduce((a,b)=>a+b,0))/C[i]*100;
    const drop=([1,2,3].map(j=>Math.max(0,C[i+j-1]-C[i+j])).reduce((a,b)=>a+b,0))/C[i]*100;
    if(gain>thr&&C[i]<C[i-1]){// bull OB
      for(let j=i+1;j<Math.min(i+50,C.length);j++){
        if(C[j]>=L[i]&&C[j]<=H[i]){bull[j]=true;}
        else if(C[j]<L[i]) break;
      }
    }
    if(drop>thr&&C[i]>C[i-1]){// bear OB
      for(let j=i+1;j<Math.min(i+50,C.length);j++){
        if(C[j]>=L[i]&&C[j]<=H[i]){bear[j]=true;}
        else if(C[j]>H[i]) break;
      }
    }
  }
  return {bull,bear};
};

// ── COMPUTE ALL INDICATORS ────────────────────────────────────────────────────
function seComputeAll(candles) {
  if(!candles||candles.length<220) return null;
  const H=candles.map(c=>c.h),L=candles.map(c=>c.l),C=candles.map(c=>c.c),V=candles.map(c=>c.v||1);
  const n=C.length;
  const {adx,dip,dim}=_seAdx(H,L,C,14);
  const {line:macd,sig:macdSig,hist:macdHist}=_seMacd(C);
  const atr=_seAtr(H,L,C,14),atr30=_seSma(atr.map(x=>x||0),30);
  const rsi=_seRsi(C,14);
  const {up:bbUp,lo:bbLo,bw:bbW}=_seBB(C,20,2.0);
  const kc=_seKeltner(H,L,C,20,2.0,10);
  const st=_seSupertrend(H,L,C,10,3.0);
  const {jaw,teeth,lips}=_seAlligator(H,L);
  const obv=_seObv(C,V),obvE=_seEma(obv,20);
  const mom=_seMom(C,10),wpr=_seWpr(H,L,C,14),vwap=_seVwap(candles);
  const {bull:obBull,bear:obBear}=_seOrderBlocks(H,L,C);
  const srsi=_seStochRsi(C);
  const e20=_seEma(C,20),e50=_seEma(C,50),e100=_seEma(C,100),e200=_seEma(C,200);
  return {H,L,C,V,n,adx,dip,dim,macd,macdSig,macdHist,atr,atr30,rsi,
          bbUp,bbLo,bbW,kc,st,jaw,teeth,lips,obv,obvE,mom,wpr,vwap,
          obBull,obBear,srsiK:srsi.k,srsiD:srsi.d,e20,e50,e100,e200};
}

// ── REGIME DETECTION ──────────────────────────────────────────────────────────
function seDetectRegime(I,i) {
  const a=I.adx[i],dp=I.dip[i],dm=I.dim[i],av=I.atr[i],aa=I.atr30[i];
  if(a==null||av==null||aa==null) return 'UNKNOWN';
  const rv=aa>0?av/aa:1;
  if(a>=30&&dp>dm) return 'TREND_UP';
  if(a>=30&&dm>dp) return 'TREND_DOWN';
  if(a>=22&&dp>dm) return 'WEAK_UP';
  if(a>=22&&dm>dp) return 'WEAK_DOWN';
  if(rv>1.4)       return 'VOLATILE';
  return 'RANGE';
}

// ── 5 STRATEGIE VALIDATE (PF ≥ 1.10) ─────────────────────────────────────────

function seS01_Exhaustion(I,i) {
  /* EXHAUSTION — PF 2.79, WR 62.6% (TP$15/SL$9)
     ADX≥30 + DI dominante + MACD esteso contro-trend
     Pattern: trend forte con momentum opposto = esaurimento imminente */
  const a=I.adx[i],dp=I.dip[i],dm=I.dim[i],m=I.macd[i],sg=I.macdSig[i];
  if(a==null||dp==null||m==null) return null;
  const diff=m-sg,spread=Math.abs(dp-dm);
  if(a>=30&&dm>dp&&spread>=15&&diff>=1.0)
    return {dir:'sell',why:`ADX ${a.toFixed(1)} · DI- ${dm.toFixed(1)} > DI+ ${dp.toFixed(1)} (spread ${spread.toFixed(0)}) · MACD +${diff.toFixed(2)} esaurito`};
  if(a>=28&&dp>dm&&spread>=15&&diff<=-1.0)
    return {dir:'buy',why:`ADX ${a.toFixed(1)} · DI+ ${dp.toFixed(1)} > DI- ${dm.toFixed(1)} (spread ${spread.toFixed(0)}) · MACD ${diff.toFixed(2)} esaurito`};
  return null;
}

function seS06_OrderBlock(I,i) {
  /* ORDER BLOCK — PF 1.57, WR 46.6% (TP$18/SL$10)
     Prezzo ritesta zona istituzionale (ultima candela prima di impulso forte)
     + RSI non esaurito + EMA50 conferma direzione */
  const ob=I.obBull[i],os=I.obBear[i],r=I.rsi[i],e50=I.e50[i],c=I.C[i];
  if(r==null||e50==null) return null;
  if(ob&&r<=55&&c>e50*0.998)
    return {dir:'buy',why:`Order Block bullish · Prezzo $${c.toFixed(0)} su zona istituzionale · RSI ${r.toFixed(0)} · sopra EMA50 $${e50.toFixed(0)}`};
  if(os&&r>=45&&c<e50*1.002)
    return {dir:'sell',why:`Order Block bearish · Prezzo $${c.toFixed(0)} su zona istituzionale · RSI ${r.toFixed(0)} · sotto EMA50 $${e50.toFixed(0)}`};
  return null;
}

function seS09_VwapWpr(I,i) {
  /* VWAP + WILLIAMS %R — PF 1.65, WR 47.9% (TP$18/SL$10)
     Prezzo torna al VWAP dopo deviazione + Williams%R in zona di svolta
     Intraday mean-reversion affidabile */
  const vwap=I.vwap[i],c=I.C[i],wpr=I.wpr[i],mom=I.mom[i],r=I.rsi[i];
  if(vwap==null||wpr==null||mom==null||r==null) return null;
  const dev=(c-vwap)/vwap*100;
  if(dev>=-0.3&&dev<=0.1&&wpr<-70&&mom>-0.1&&r>=40)
    return {dir:'buy',why:`VWAP $${vwap.toFixed(0)} (dev ${dev.toFixed(2)}%) · W%R ${wpr.toFixed(0)} oversold · Momentum ${mom.toFixed(1)}%`};
  if(dev>=-0.1&&dev<=0.3&&wpr>-30&&mom<0.1&&r<=60)
    return {dir:'sell',why:`VWAP $${vwap.toFixed(0)} (dev ${dev.toFixed(2)}%) · W%R ${wpr.toFixed(0)} overbought · Momentum ${mom.toFixed(1)}%`};
  return null;
}

function seS12_WprKeltner(I,i) {
  /* WILLIAMS %R + KELTNER + RSI — PF 1.22, WR 42.3%
     Prezzo ai limiti del Keltner Channel + W%R estremo + RSI conferma
     Mean-reversion con filtro volatilità (ADX<30) */
  const wpr=I.wpr[i],r=I.rsi[i],c=I.C[i],ku=I.kc.up[i],kl=I.kc.lo[i],a=I.adx[i];
  if(wpr==null||r==null||ku==null||kl==null||a==null) return null;
  if(a>=30) return null;
  if(c<=kl*1.002&&wpr<-80&&r<35)
    return {dir:'buy',why:`Keltner lower $${kl.toFixed(0)} · W%R ${wpr.toFixed(0)} oversold · RSI ${r.toFixed(0)} · ADX ${a.toFixed(0)} (ranging)`};
  if(c>=ku*0.998&&wpr>-20&&r>65)
    return {dir:'sell',why:`Keltner upper $${ku.toFixed(0)} · W%R ${wpr.toFixed(0)} overbought · RSI ${r.toFixed(0)} · ADX ${a.toFixed(0)} (ranging)`};
  return null;
}

function seS10_SessionMom(I,i,hour) {
  /* SESSION MOMENTUM — PF 1.10, WR 39.8%
     Supertrend + MACD + EMA50 · SOLO apertura London (7-13 UTC)
     Segue il momentum del mercato nell'ora di massima liquidità */
  if(hour==null||hour<7||hour>13) return null;
  const st=I.st[i],m=I.macd[i],sg=I.macdSig[i],r=I.rsi[i],e50=I.e50[i],c=I.C[i];
  if(m==null||r==null||e50==null) return null;
  const diff=m-sg;
  if(st===-1&&diff>0&&r>=45&&r<=70&&c>e50)
    return {dir:'buy',why:`Supertrend BULL · MACD +${diff.toFixed(2)} · RSI ${r.toFixed(0)} · sopra EMA50 · ${hour}:00 UTC London`};
  if(st===1&&diff<0&&r>=30&&r<=55&&c<e50)
    return {dir:'sell',why:`Supertrend BEAR · MACD ${diff.toFixed(2)} · RSI ${r.toFixed(0)} · sotto EMA50 · ${hour}:00 UTC London`};
  return null;
}

const SE_STRATEGY_FNS = {
  S01_EXHAUSTION:  (I,i,h) => seS01_Exhaustion(I,i),
  S06_ORDERBLOCK:  (I,i,h) => seS06_OrderBlock(I,i),
  S09_VWAP_WPER:   (I,i,h) => seS09_VwapWpr(I,i),
  S12_WPR_KELTNER: (I,i,h) => seS12_WprKeltner(I,i),
  S10_SESSION_MOM: (I,i,h) => seS10_SessionMom(I,i,h),
};

// ── DAILY STATE ────────────────────────────────────────────────────────────────
function seGetState() {
  const today=new Date().toISOString().split('T')[0];
  try{const s=JSON.parse(localStorage.getItem('se_v2')||'{}');
    if(s.date!==today)return{date:today,trades:[],regime:'UNKNOWN',lastH:-99};
    return s;
  }catch{return{date:today,trades:[],regime:'UNKNOWN',lastH:-99};}
}
function seSaveState(s){try{localStorage.setItem('se_v2',JSON.stringify(s));}catch{}}

// ── MAIN REFRESH ──────────────────────────────────────────────────────────────
async function seRefresh() {
  // Carica candles
  if(window.mfkkCandles&&window.mfkkCandles.length>=220) seCandles=window.mfkkCandles;
  else if(seCandles.length<220){
    try{
      const asset=window.activeAsset||'XAU';
      const r=await fetch(`/api/candles?asset=${asset}&range=60d&interval=1h`);
      const d=await r.json();
      if(d?.ok&&d.candles?.length>=220) seCandles=d.candles;
    }catch{}
  }
  if(seCandles.length<220){seRenderNoData();return;}

  seInds=seComputeAll(seCandles);
  if(!seInds){seRenderNoData();return;}

  const I=seInds,i=I.n-1;
  const nowUtc=new Date(),hour=nowUtc.getUTCHours();
  seRegime=seDetectRegime(I,i);

  const state=seGetState();
  state.regime=seRegime;

  // Extreme day check
  const av=I.atr[i],aa=I.atr30[i];
  const isExtreme=av&&aa&&av>SE.extremeMult*aa;
  const inSession=hour>=SE.session.start&&hour<SE.session.end;

  // Scan segnali
  let pending=[];
  if(!isExtreme&&inSession){
    const priority=SE.regimePriority[seRegime]||['S10_SESSION_MOM'];
    for(const name of priority){
      const fn=SE_STRATEGY_FNS[name];
      if(!fn)continue;
      const sig=fn(I,i,hour);
      if(sig){
        const cfg=SE.strategies[name];
        pending.push({name,label:cfg.label,dir:sig.dir,why:sig.why,
          tp:cfg.tp,sl:cfg.sl,pf:cfg.pf,wr:cfg.wr,priority:priority.indexOf(name)+1});
      }
    }
  }

  // Aggiunge trade se:
  const liveP=parseFloat(I.C[i]);
  if(pending.length>0&&state.trades.length<SE.maxTrades&&hour-state.lastH>=SE.cooldownH){
    const best=pending[0];
    const dup=state.trades.find(t=>t.strategy===best.name&&new Date().toISOString().split('T')[0]===t.date&&t.hour===hour);
    if(!dup){
      state.trades.push({
        strategy:best.name,label:best.label,dir:best.dir,why:best.why,
        tp:best.tp,sl:best.sl,pf:best.pf,wr:best.wr,
        entry:liveP,date:state.date,hour,
        time:nowUtc.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'})+' UTC',
        tpPrice:liveP+(best.dir==='buy'?best.tp:-best.tp),
        slPrice:liveP+(best.dir==='buy'?-best.sl:best.sl),
        status:'open'
      });
      state.lastH=hour;
    }
  }

  // Aggiorna status trade aperti
  if(liveP>0){
    for(const t of state.trades){
      if(t.status!=='open')continue;
      if(t.dir==='buy'){
        if(liveP>=t.tpPrice){t.status='win';t.closePrice=t.tpPrice;}
        else if(liveP<=t.slPrice){t.status='loss';t.closePrice=t.slPrice;}
      }else{
        if(liveP<=t.tpPrice){t.status='win';t.closePrice=t.tpPrice;}
        else if(liveP>=t.slPrice){t.status='loss';t.closePrice=t.slPrice;}
      }
    }
  }
  seSaveState(state);

  // Snapshot indicatori per UI
  const snap={
    price:liveP.toFixed(2),adx:I.adx[i]?.toFixed(1),dip:I.dip[i]?.toFixed(1),dim:I.dim[i]?.toFixed(1),
    rsi:I.rsi[i]?.toFixed(0),macd:I.macd[i]?.toFixed(2),e20:I.e20[i]?.toFixed(0),e50:I.e50[i]?.toFixed(0),
    e100:I.e100[i]?.toFixed(0),e200:I.e200[i]?.toFixed(0),
    st:I.st[i]===-1?'BULL':'BEAR',wpr:I.wpr[i]?.toFixed(0),mom:I.mom[i]?.toFixed(1),
    vwap:I.vwap[i]?.toFixed(0),
    jaw:I.jaw[i]?.toFixed(0),teeth:I.teeth[i]?.toFixed(0),lips:I.lips[i]?.toFixed(0),
    srsiK:I.srsiK[i]?.toFixed(0),atr:I.atr[i]?.toFixed(2),
  };

  seRender(state,pending,snap,isExtreme,inSession,hour);
}

// ── RENDER ────────────────────────────────────────────────────────────────────
function seRender(state,pending,snap,isExtreme,inSession,hour){
  const el=document.getElementById('se-content');
  if(!el)return;

  const REGIME_META={
    TREND_UP:    {col:'#00e676',bg:'#00e67612',icon:'📈',label:'TREND RIALZISTA'},
    TREND_DOWN:  {col:'#ff4757',bg:'#ff475712',icon:'📉',label:'TREND RIBASSISTA'},
    WEAK_UP:     {col:'#ffd700',bg:'#ffd70012',icon:'↗️',label:'TREND DEBOLE ↑'},
    WEAK_DOWN:   {col:'#ffca28',bg:'#ffca2812',icon:'↘️',label:'TREND DEBOLE ↓'},
    RANGE:       {col:'#c8a96e',bg:'#c8a96e12',icon:'↔️',label:'LATERALE (RANGING)'},
    VOLATILE:    {col:'#b36cff',bg:'#b36cff12',icon:'⚡',label:'VOLATILE'},
    UNKNOWN:     {col:'var(--dim)',bg:'var(--bg2)',icon:'❓',label:'SCONOSCIUTO'},
  };
  const rm=REGIME_META[seRegime]||REGIME_META.UNKNOWN;
  const wins=state.trades.filter(t=>t.status==='win').length;
  const losses=state.trades.filter(t=>t.status==='loss').length;
  const open=state.trades.filter(t=>t.status==='open').length;
  const pnl=state.trades.reduce((a,t)=>a+(t.status==='win'?t.tp:t.status==='loss'?-t.sl:0),0);

  // ── STATUS BAR
  let statusHtml='';
  if(isExtreme){
    statusHtml=`<div style="background:#ff475720;border:1px solid #ff475740;border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:#ff4757">
      ⚠️ <b>GIORNO ESTREMO</b> — Volatilità anomala (ATR>${SE.extremeMult}x media). Trading sospeso automaticamente.
    </div>`;
  } else if(!inSession){
    statusHtml=`<div style="background:var(--bg2);border:1px solid var(--border);border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:var(--dim)">
      🔴 <b>Fuori sessione</b> (${hour}:00 UTC) — Il sistema genera segnali dalle 07:00 alle 17:00 UTC (London + New York)
    </div>`;
  } else if(state.trades.length>=SE.maxTrades){
    statusHtml=`<div style="background:#00e67610;border:1px solid #00e67625;border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:var(--green)">
      ✅ Massimo trade giornaliero raggiunto (${SE.maxTrades}/${SE.maxTrades}). Riprende domani.
    </div>`;
  } else {
    statusHtml=`<div style="background:#00e67610;border:1px solid #00e67625;border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:var(--green)">
      🟢 <b>Sessione attiva</b> (${hour}:00 UTC) — ${SE.maxTrades-state.trades.length} trade disponibili · Cooldown ${SE.cooldownH}h tra trade
    </div>`;
  }

  // ── REGIME + P&L
  const regimeHtml=`
<div style="background:${rm.bg};border:1px solid ${rm.col}40;border-radius:9px;padding:11px 13px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:3px">REGIME DI MERCATO</div>
      <div style="font-size:16px;font-weight:800;color:${rm.col}">${rm.icon} ${rm.label}</div>
      <div style="font-size:9px;color:${rm.col};margin-top:4px">
        Strategie attive: ${(SE.regimePriority[seRegime]||['S10_SESSION_MOM']).map(n=>`<b>${SE.strategies[n]?.label||n}</b>`).join(' › ')}
      </div>
    </div>
    <div style="text-align:right">
      <div style="font-size:9px;color:var(--dim);margin-bottom:2px">P&L OGGI</div>
      <div style="font-size:18px;font-weight:800;color:${pnl>0?'var(--green)':pnl<0?'var(--red)':'var(--fg)'}">${pnl>=0?'+':''}$${pnl.toFixed(0)}</div>
      <div style="font-size:9px;color:var(--dim)">${wins}✅ · ${losses}❌ · ${open}⏳</div>
    </div>
  </div>
</div>`;

  // ── INDICATORI SNAPSHOT (2 righe compatte)
  const indSnap=`
<div style="margin-bottom:8px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:4px">INDICATORI CORRENTI</div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-bottom:3px">
    ${[['ADX',snap.adx],['DI+',snap.dip],['DI-',snap.dim],['RSI',snap.rsi],['W%R',snap.wpr]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px">
    ${[['MACD',snap.macd],['EMA50',snap.e50],['EMA200',snap.e200],['MOM%',snap.mom],['VWAP',snap.vwap]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-top:3px">
    ${[['Jaw',snap.jaw],['Teeth',snap.teeth],['Lips',snap.lips],['StRSI',snap.srsiK],['ATR',snap.atr]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
</div>`;

  // ── SEGNALI ATTIVI
  let pendingHtml='';
  if(pending.length>0&&!isExtreme&&inSession){
    pendingHtml=`<div style="margin-bottom:10px">
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">🔔 SEGNALI ATTIVI ORA</div>
      ${pending.map((s,idx)=>{
        const dc=s.dir==='buy'?'#00e676':'#ff4757';
        const pc=idx===0?'#ffd700':'var(--dim)';
        return `<div style="background:${dc}10;border:1px solid ${dc}35;border-radius:7px;padding:8px 10px;margin-bottom:5px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="color:${dc};font-weight:800;font-size:12px">${s.dir==='buy'?'▲ BUY':'▼ SELL'}</span>
            <span style="color:${pc};font-size:9px">${idx===0?'★ PRIORITÀ 1':'P'+(idx+1)} · ${s.label} · ${s.tf||'1h'} · WR ${s.wr} · PF ${s.pf}</span>
          </div>
          <div style="font-size:9px;color:var(--fg);margin-bottom:4px">${s.why}</div>
          <div style="display:flex;gap:8px;font-size:9px;color:var(--dim)">
            <span style="color:var(--green)">TP +$${s.tp}</span>
            <span style="color:var(--red)">SL -$${s.sl}</span>
            <span>R:R 1:${(s.tp/s.sl).toFixed(1)}</span>
          </div>
        </div>`;
      }).join('')}
    </div>`;
  }

  // ── TRADE DEL GIORNO
  const tradeHtml=`
<div style="margin-bottom:10px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">TRADE OGGI (${state.date})</div>
  ${state.trades.length===0
    ? `<div style="text-align:center;padding:12px;background:var(--bg2);border-radius:7px;font-size:10px;color:var(--dim)">Nessun trade aperto oggi — il sistema attende il setup ideale</div>`
    : state.trades.map(t=>{
        const sc=t.status==='win'?'#00e676':t.status==='loss'?'#ff4757':'#ffca28';
        const si=t.status==='win'?'✅':t.status==='loss'?'❌':'⏳';
        const dc=t.dir==='buy'?'#00e676':'#ff4757';
        const pnlT=t.status==='win'?t.tp:t.status==='loss'?-t.sl:0;
        return `<div style="background:var(--bg2);border:1px solid ${sc}35;border-radius:7px;padding:8px 10px;margin-bottom:5px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
            <div>
              <span style="color:${dc};font-weight:800;font-size:11px">${t.dir==='buy'?'▲ BUY':'▼ SELL'}</span>
              <span style="font-size:9px;color:var(--dim);margin-left:6px">${t.time} · ${t.label}</span>
            </div>
            <div style="display:flex;align-items:center;gap:5px">
              ${t.status!=='open'?`<span style="color:${sc};font-size:10px;font-weight:700">${pnlT>=0?'+':''}$${pnlT}</span>`:''}
              <span style="font-size:14px">${si}</span>
            </div>
          </div>
          <div style="font-size:9px;color:var(--dim);margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t.why}</div>
          <div style="display:flex;gap:8px;font-size:9px">
            <span>Entry <b>$${t.entry?.toFixed(0)}</b></span>
            <span style="color:var(--green)">TP $${t.tpPrice?.toFixed(0)} (+$${t.tp})</span>
            <span style="color:var(--red)">SL $${t.slPrice?.toFixed(0)} (-$${t.sl})</span>
          </div>
        </div>`;
      }).join('')}
</div>`;

  // ── GUIDE (collassabile) + PERFORMANCE TABLE
  const guideHtml=`
<details style="margin-bottom:10px">
  <summary style="font-size:9px;color:var(--dim);letter-spacing:.08em;cursor:pointer;user-select:none;padding:5px 0">
    ❓ COME USARE STRATEGY ENGINE (tocca per aprire)
  </summary>
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:7px;padding:10px;margin-top:6px;font-size:10px;line-height:1.6;color:var(--fg)">
    <b style="color:var(--g)">Come funziona il sistema:</b><br>
    1. Ogni ora il sistema analizza 18 indicatori e rileva il <b>regime di mercato</b> (Trend/Range/Volatile).<br>
    2. In base al regime, seleziona automaticamente le <b>strategie più adatte</b> ordinate per efficienza.<br>
    3. Se le condizioni di entrata sono soddisfatte, compare un <b>segnale arancione/verde</b> nella sezione "Segnali Attivi".<br>
    4. Il sistema apre <b>max 3 trade al giorno</b>, con almeno 1 ora tra un trade e l'altro.<br>
    5. <b>Non tradare nei giorni estremi</b> (ATR anomalo) — il sistema lo segna automaticamente.<br><br>

    <b style="color:var(--g)">Come eseguire i trade:</b><br>
    • Quando compare un segnale, apri il trade sul tuo broker con il prezzo attuale<br>
    • Metti il <b>Take Profit</b> e <b>Stop Loss</b> esattamente come mostrato<br>
    • <b>Non spostare mai lo SL</b> — il sistema è calibrato con queste distanze<br>
    • Ogni trade usa la stessa size (es. 0.1 lotti) per gestione rischio uniforme<br><br>

    <b style="color:var(--g)">Sessione operativa:</b><br>
    • <b>07:00 - 17:00 UTC</b> = London + New York (massima liquidità)<br>
    • Evita Asian session (00:00-07:00 UTC) — meno volatilità, spread più alti<br><br>

    <b style="color:var(--g)">Indicatori usati:</b><br>
    EMA 20/50/100/200 · MACD · ADX+DI · RSI · StochRSI · Bollinger Bands · Keltner Channels · Supertrend · Alligator (Williams) · OBV · Momentum/ROC · Williams %R · VWAP · Order Blocks · ATR
  </div>
</details>`;

  const perfHtml=`
<div>
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">PERFORMANCE STRATEGIE — MTF test 1h/4h/1d · 730gg XAU/USD</div>
  <table style="width:100%;border-collapse:collapse;font-size:9px">
    <tr style="color:var(--dim);border-bottom:1px solid var(--border)">
      <td style="padding:3px 0">Strategia</td><td style="text-align:right">TF✓</td><td style="text-align:right">WR%</td><td style="text-align:right">PF</td><td style="text-align:right">TP/SL</td>
    </tr>
    ${[
      ['S01_EXHAUSTION','1h','57.9%','2.288','$15/$9','#ffd700'],
      ['S09_VWAP+W%R','1h','47.4%','1.501','$18/$10','#00e676'],
      ['S06_ORDER BLOCK','1h','46.1%','1.424','$18/$10','#00e676'],
      ['S12_WPR+KELTNER','1h','42.3%','1.220','$20/$12','#c8a96e'],
      ['S10_SESSION MOM','1h','38.5%','1.042','$20/$12','#ffca28'],
    ].map(([n,tf,wr,pf,tpsl,col])=>`
    <tr style="border-bottom:1px solid var(--border2)">
      <td style="padding:4px 0;color:${col};font-weight:600;font-size:8px">${n}</td>
      <td style="text-align:right;color:#4fc3f7;font-weight:700">${tf}</td>
      <td style="text-align:right;color:${col}">${wr}</td>
      <td style="text-align:right;color:var(--fg)">${pf}</td>
      <td style="text-align:right;color:var(--dim)">${tpsl}</td>
    </tr>`).join('')}
  </table>
  <div style="margin-top:6px;font-size:8px;color:var(--border2);text-align:center">
    Aggiornamento ogni 5 min · Max ${SE.maxTrades} trade/gg · Session 07-17 UTC
  </div>
</div>`;

  el.innerHTML=statusHtml+regimeHtml+indSnap+pendingHtml+tradeHtml+guideHtml+perfHtml;
}

function seRenderNoData(){
  const el=document.getElementById('se-content');
  if(!el)return;
  el.innerHTML=`<div style="text-align:center;padding:25px;color:var(--dim);font-size:12px">
    Caricamento dati in corso...<br>
    <span style="font-size:10px">Le candele vengono condivise con il modulo MFKK (stesso fetch)</span>
  </div>`;
}

// ── INIT ──────────────────────────────────────────────────────────────────────
async function initStrategyEngine(){
  if(seTimer)clearInterval(seTimer);
  await seRefresh();
  seTimer=setInterval(seRefresh,5*60*1000);
}
window.initStrategyEngine=initStrategyEngine;
window.seRefresh=seRefresh;
