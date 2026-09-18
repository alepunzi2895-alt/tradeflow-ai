import assert from 'node:assert/strict';
import handler from '../api/analysis.js';
const rows=Array.from({length:40},(_,i)=>({date:`2026-09-${String(1+Math.floor(i/2)).padStart(2,'0')}T12:00:00Z`,country:'USD',title:'Event '+i,impact:'High',forecast:'1',previous:'2',actual:'3'}));
let fetchCalls=0;globalThis.fetch=async()=>{fetchCalls++;return {ok:true,json:async()=>rows}};
async function call(type,extra={}){let body,status;const res={setHeader(){},status(s){status=s;return this},json(d){body=d;return this}};await handler({query:{type,...extra},url:'/api/market',method:'GET'},res);return {body,status};}
let r=await call('calendar');assert.equal(r.body.events.length,40);assert.equal(r.body.events[39].forecast,'1');assert.equal(r.body.events[39].actual,'3');await call('calendar');assert.equal(fetchCalls,1);
globalThis.fetch=async()=>({ok:true,json:async()=>({symbols:[{name:'GOLD',longPercentage:60,shortPercentage:40}]})});
r=await call('sentiment',{symbol:'XAGUSD'});assert.equal(r.body.ok,false);
r=await call('sentiment',{symbol:'XAUUSD'});assert.equal(r.body.outlook.symbols[0].longPercentage,60);
globalThis.fetch=async()=>{throw Error('offline')};r=await call('sentiment');assert.equal(r.body.ok,false);assert.ok(!r.body.outlook);
console.log('Market data: 8 assertions passed');
r=await call('indicators',{asset:'US30'});assert.equal(r.body.ok,false);assert.equal(r.body.adx,null);assert.equal(r.body.macd,null);
let scanned;
globalThis.fetch=async(url,opts)=>{if(url.includes('scanner')){scanned=JSON.parse(opts.body);return {ok:true,json:async()=>({data:[{d:[42000,5,3]}]})};}return {ok:true,json:async()=>({})};};
r=await call('indicators',{asset:'US30'});assert.equal(scanned.symbols.tickers[0],'OANDA:US30USD');assert.equal(r.body.macd.histogram,2);
console.log('Indicator API: missing values and US30 MACD verified');
