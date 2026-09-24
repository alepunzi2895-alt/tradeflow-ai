import fs from 'node:fs';
import assert from 'node:assert/strict';
import handler from '../api/market.js';
import analysisHandler from '../api/analysis.js';
import priceHandler from '../api/price.js';
import {normalizeQuotes,QUOTE_SYMBOLS} from '../lib/market-quotes.js';
assert.equal(handler,analysisHandler,'Vercel filesystem route and rewrite target must share the same handler');
const rows=Array.from({length:40},(_,i)=>({date:`2026-09-${String(1+Math.floor(i/2)).padStart(2,'0')}T12:00:00Z`,country:'USD',title:'Event '+i,impact:'High',forecast:'1',previous:'2',actual:'3'}));
let fetchCalls=0;globalThis.fetch=async()=>{fetchCalls++;return {ok:true,json:async()=>rows}};
async function call(type,extra={}){let body,status;const res={setHeader(){},status(s){status=s;return this},json(d){body=d;return this}};await handler({query:{type,...extra},url:'/api/market',method:'GET'},res);return {body,status};}
let r=await call('calendar');assert.equal(r.body.events.length,40);assert.equal(r.body.events[39].forecast,'1');assert.equal(r.body.events[39].actual,'3');await call('calendar');assert.equal(fetchCalls,1);
// Sentiment spostato in api/myfxbook.js (sessione lato server, 2026-09-24) — vedi test-myfxbook.mjs.
r=await call('sentiment',{symbol:'XAUUSD'});assert.equal(r.status,410);assert.equal(r.body.ok,false);assert.ok(!r.body.outlook);
console.log('Market data: 6 assertions passed');
r=await call('indicators',{asset:'US30'});assert.equal(r.body.ok,false);assert.equal(r.body.adx,null);assert.equal(r.body.macd,null);
let scanned;
globalThis.fetch=async(url,opts)=>{if(url.includes('scanner')){scanned=JSON.parse(opts.body);return {ok:true,json:async()=>({data:[{d:[42000,5,3]}]})};}return {ok:true,json:async()=>({})};};
r=await call('indicators',{asset:'US30'});assert.equal(scanned.symbols.tickers[0],'OANDA:US30USD');assert.equal(r.body.macd.histogram,2);
console.log('Indicator API: missing values and US30 MACD verified');

const quoteRows=[{s:'TVC:GOLD',d:[3900,1,4000,3800]}, {s:'OANDA:XAUUSD',d:[3897,.75,4000,3800]},
  {s:'OANDA:US30USD',d:[42000,null,null,41000]}, {s:'TVC:DXY',d:[null,0,100,90]},
  {s:'OANDA:EURUSD',d:[1.08456,-.1,1.09,1.08]}, {s:'COMEX:GC1!',d:[6000,2,6001,5999]}];
const snapshot=normalizeQuotes(quoteRows,'2026-09-18T13:00:00Z');
assert.equal(snapshot.prices.XAU.price,3897,'broker priority does not depend on response order');
assert.equal(snapshot.prices.XAU._source,'OANDA:XAUUSD');
assert.equal(snapshot.prices.US30.change,null,'unknown percentage is not zero');
assert.equal(snapshot.prices.DXY,undefined,'null prices are unavailable, not zero');
assert.equal(snapshot.prices.EURUSD.price,1.08456,'FX precision preserved');
assert.equal(snapshot.prices.XAU.received_at,snapshot.prices.EURUSD.received_at);
let quoteRequests=0;
globalThis.fetch=async(url,opts)=>{quoteRequests++;assert.match(url,/scanner.tradingview.com/);const request=JSON.parse(opts.body);assert.deepEqual(request.columns,['close','change','high','low']);assert.ok(!request.symbols.tickers.includes('GC=F'));return {ok:true,json:async()=>({data:quoteRows})};};
r=await call('prices');assert.equal(quoteRequests,1);assert.equal(r.body.prices.XAU.price,3897);
let single;await priceHandler({query:{asset:'XAU'},url:'/api/price',method:'GET'},{setHeader(){},status(){return this},json(body){single=body}});
assert.equal(single.price,r.body.prices.XAU.price);assert.equal(single.changePct,r.body.prices.XAU.change);
// Registro strumenti (public/instruments.json) + 8 quotazioni macro di contesto.
const REG=JSON.parse(fs.readFileSync('public/instruments.json','utf8')).instruments;
assert.equal(Object.keys(QUOTE_SYMBOLS).length,REG.length+8);
for(const i of REG)assert.deepEqual(QUOTE_SYMBOLS[i.id],i.quotes,'quotazioni dal registro: '+i.id);
// Asset sconosciuto: errore esplicito, mai i dati dell'oro sotto un altro nome.
let bad;await priceHandler({query:{asset:'FOOBAR'},url:'/api/candles',method:'GET'},{setHeader(){},status(c){bad={status:c};return this},json(b){bad.body=b}});
assert.equal(bad.status,400);
r=await call('indicators',{asset:'FOOBAR'});assert.equal(r.status,400);
// FX: ticker del registro e precisione a 5 decimali nelle candele.
globalThis.fetch=async(url,opts)=>{if(url.includes('scanner')){scanned=JSON.parse(opts.body);return {ok:true,json:async()=>({data:[]})};}
  return {ok:true,json:async()=>({chart:{result:[{timestamp:Array.from({length:40},(_,i)=>1700000000+i*3600),indicators:{quote:[{open:Array(40).fill(1.138041),high:Array(40).fill(1.13901),low:Array(40).fill(1.13701),close:Array(40).fill(1.13804),volume:Array(40).fill(0)}]}}]}})};};
r=await call('indicators',{asset:'EURUSD'});assert.equal(scanned.symbols.tickers[0],'OANDA:EURUSD');
let fx;await priceHandler({query:{asset:'EURUSD'},url:'/api/candles',method:'GET'},{setHeader(){},status(c){fx={status:c};return this},json(b){fx.body=b}});
assert.equal(fx.body.candles[0].c,1.13804,'FX precision preserved in candles');
globalThis.fetch=async()=>{throw Error('offline')};r=await call('prices');assert.equal(r.status,503);assert.deepEqual(r.body.prices,{});
console.log('Unified quote batch, provider priority, missing values and endpoint consistency: passed');
