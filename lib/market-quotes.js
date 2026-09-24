// One TradingView batch and a deterministic broker priority for every quote.
// All UI symbols share this snapshot; unavailable changes remain null, never 0%.
import {INSTRUMENTS} from './instruments.js';
// Strumenti tradabili dal registro (public/instruments.json) + quotazioni macro di contesto
// (non selezionabili: griglia Quotazioni, correlazioni, macro-score).
export const QUOTE_SYMBOLS = {
  ...Object.fromEntries(INSTRUMENTS.map(i => [i.id, i.quotes])),
  DXY: ['TVC:DXY'], OIL: ['FX:USOIL','TVC:USOIL'],
  US10Y: ['TVC:US10Y'], US02Y: ['TVC:US02Y'], VIX: ['TVC:VIX'],
  SPX: ['SP:SPX'], NDX: ['NASDAQ:NDX'], RUT: ['TVC:RUT']
};
const finite = value => typeof value==='number' && Number.isFinite(value);

export function normalizeQuotes(rows, receivedAt=new Date().toISOString()) {
  const byTicker=new Map((Array.isArray(rows)?rows:[]).map(row=>[row.s,row.d]));
  const prices={};
  for(const [symbol,tickers] of Object.entries(QUOTE_SYMBOLS)) {
    const source=tickers.find(ticker=>finite(byTicker.get(ticker)?.[0]) && byTicker.get(ticker)[0]>0);
    if(!source)continue;
    const [price,change,high,low]=byTicker.get(source);
    prices[symbol]={price,change:finite(change)?change:null,high:finite(high)?high:null,
      low:finite(low)?low:null,_source:source,received_at:receivedAt};
  }
  return {ok:Object.keys(prices).length>0,prices,source:'TradingView',timestamp:receivedAt,
    refreshIntervalMs:5000,missing:Object.keys(QUOTE_SYMBOLS).filter(key=>!prices[key])};
}

export async function fetchQuotes() {
  // The timeout covers both headers and body, within the Vercel execution limit.
  const fetchT=(url,options)=>fetch(url,{...options,signal:AbortSignal.timeout(7500)});
  try {
    const response=await fetchT('https://scanner.tradingview.com/global/scan',{
      method:'POST',headers:{'Content-Type':'application/json','User-Agent':'Mozilla/5.0',
        Origin:'https://www.tradingview.com',Referer:'https://www.tradingview.com/'},
      body:JSON.stringify({symbols:{tickers:[...new Set(Object.values(QUOTE_SYMBOLS).flat())],query:{types:[]}},columns:['close','change','high','low']})
    });
    if(!response.ok)throw Error('Fonte quotazioni temporaneamente non disponibile');
    const data=await response.json();
    const snapshot=normalizeQuotes(data.data);
    if(!snapshot.ok)snapshot.error='Nessuna quotazione disponibile dalla fonte';
    return snapshot;
  }catch{return {ok:false,prices:{},error:'Quotazioni temporaneamente non disponibili',source:'TradingView',timestamp:new Date().toISOString()};}
}
