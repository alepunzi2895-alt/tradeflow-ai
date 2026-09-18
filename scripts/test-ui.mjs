// Browser fixtures are local and synthetic. No production API or MT5 connection.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {registrySnapshot} from '../lib/strategy-registry.js';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const root=path.resolve('public');
const server=http.createServer((req,res)=>{
  const file=path.resolve(root,'.'+new URL(req.url,'http://localhost').pathname);
  const target=file===root?path.join(root,'index.html'):file;
  if(!target.startsWith(root+path.sep)||!fs.existsSync(target)||!fs.statSync(target).isFile()){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',({'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json'})[path.extname(target)]||'application/octet-stream');
  res.end(fs.readFileSync(target));
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const base='http://127.0.0.1:'+server.address().port;
const browser=await chromium.launch({headless:true});
const errors=[];
let quoteRequests=0, quoteFailure=false, statsDenied=false;
const page=await browser.newPage({viewport:{width:1440,height:1100}});
page.setDefaultTimeout(8000);
page.on('pageerror',e=>errors.push(e.message));
const dates=[0,3,15,45].map(days=>{const d=new Date();d.setDate(d.getDate()-days);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;});
await page.addInitScript(({dates})=>{
  localStorage.setItem('tf_token','cookie');localStorage.setItem('tf_user_id','test-user');
  localStorage.setItem('tf_journal',JSON.stringify(dates.map((date,i)=>({id:'fixture'+i,date,dir:'BUY',entry:100,sl:95,tp1:110,result:'WIN',pnl:10,symbol:'XAUUSD',source:'myfxbook:fixture'}))));
},{dates});
await page.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.origin!==base){await route.abort();return;}
  if(!url.pathname.startsWith('/api/')){await route.continue();return;}
  let b={};try{b=request.postDataJSON()||{};}catch{}
  let json={ok:true,data:null};
  if(b.action==='session')json={ok:true,user:{id:'test-user',email:'test@example.test'}};
  if(b.action==='get_user_data')json={ok:true,data:[{doc_type:'mfx',payload:JSON.stringify({session:'fixture-session',email:'test@example.test',pass:'legacy-test-password'})}]};
  if(b.action==='get_trades')json={ok:true,trades:[]};
  if(b.action==='strategy_registry')json={ok:true,data:registrySnapshot()};
  if(b.action==='mt5_get'){
    if(statsDenied){await route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({ok:false,error:'Accesso non abilitato'})});return;}
    json={ok:true,data:{account:{equity:10000,balance:9900,currency:'USD'},positions:[],trades:[{profit:10},{profit:-5},{profit:15}],bot_status:{running:true,pnl_today:25,registry:registrySnapshot()},synced_at:new Date().toISOString()}};
  }
  if(url.pathname==='/api/price')json={ok:true,price:4000,changePct:0.2};
  if(url.pathname==='/api/kb')json={ok:true,kb:[],knowledge:[]};
  if(url.pathname==='/api/market')json={ok:true,prices:{},events:[]};
  if(url.pathname==='/api/market' && url.searchParams.get('type')==='prices'){
    quoteRequests++;
    if(quoteFailure){await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,error:'offline'})});return;}
    const values={XAU:4000,XAG:40,US30:42000,DXY:100,EURUSD:1.08456,GBPUSD:1.23,OIL:70,US10Y:4,US02Y:3.8,VIX:16,SPX:5000,NDX:18000,RUT:2000};
    const timestamp=new Date().toISOString();json={ok:true,timestamp,prices:Object.fromEntries(Object.entries(values).map(([key,price])=>[key,{price,change:key==='XAG'?null:.25,_source:'TradingView:'+key,received_at:timestamp}]))};
  }
  await route.fulfill({contentType:'application/json',body:JSON.stringify(json)});
});
try {
  await page.goto(base);
  await page.waitForSelector('.saturn-satellite');
  assert.equal(await page.locator('.saturn-satellite').count(),3);
  await page.waitForFunction(()=>document.querySelector('[data-quote-symbol=XAU] .pc-val')?.textContent.includes('4.000'));
  assert.equal(await page.locator('.price-strip').count(),1,'only one quote surface');
  assert.equal(await page.locator('#market-quotes .pc').count(),13);
  assert.equal(await page.locator('.market-watch,#hdr #bxau,#hdr #bxag').count(),0,'no duplicated price areas');
  assert.equal(await page.locator('[data-quote-symbol=XAG] .pc-chg').innerText(),'—');
  const xauBefore=await page.locator('[data-quote-symbol=XAU] .pc-val').innerText();
  await page.locator('#asset-seg [data-asset=US30]').click();
  assert.match(await page.locator('#lbl-sent-title').innerText(),/US30/);
  assert.equal(await page.locator('[data-quote-symbol=XAU] .pc-val').innerText(),xauBefore,'asset selection never replaces the gold quote');
  assert.equal(await page.locator('[data-quote-symbol=US30] .pc-val').innerText(),'42.000,00');
  assert.equal(await page.locator('#system-winrate').innerText(),'66,7%');
  assert.equal(await page.locator('#system-pf').innerText(),'5');
  assert.match(await page.locator('#system-status').innerText(),/3 trade chiusi/);
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('tf_myfx:test-user')).pass),undefined,'legacy cloud password is not persisted');
  const first=page.locator('.saturn-satellite').nth(1);
  const before=await first.getAttribute('style');
  await page.waitForTimeout(700);
  assert.notEqual(await first.getAttribute('style'),before,'orbits advance');
  const sceneBox=await page.locator('.saturn-universe').boundingBox();
  await page.mouse.move(sceneBox.x+sceneBox.width/2,sceneBox.y+sceneBox.height/2);
  const moonBox=await first.boundingBox();
  await page.mouse.click(moonBox.x+moonBox.width/2,moonBox.y+moonBox.height/2);
  assert.equal(await first.getAttribute('aria-pressed'),'true');
  await page.mouse.move(10,10);
  const focusedPosition=await first.getAttribute('style');await page.waitForTimeout(250);
  assert.equal(await first.getAttribute('style'),focusedPosition,'keyboard focus holds the orbit even when pointer leaves');
  await page.locator('.saturn-motion').click();
  const frozen=await first.getAttribute('style');await page.waitForTimeout(250);
  assert.equal(await first.getAttribute('style'),frozen,'pause preserves position');
  fs.mkdirSync('artifacts',{recursive:true});
  await page.locator('#orbit-hero').screenshot({path:'artifacts/saturn-desktop.png'});
  await page.locator('#market-quotes').screenshot({path:'artifacts/quotes-desktop.png'});
  quoteFailure=true;
  await page.evaluate(()=>loadPrices());
  assert.equal(await page.locator('[data-quote-symbol=XAU] .pc-val').innerText(),xauBefore,'failed refresh retains the last value with a stale label');
  assert.match(await page.locator('.quote-status').innerText(),/Fonte non disponibile/);
  quoteFailure=false;await page.evaluate(()=>loadPrices());
  await page.locator('[data-tab=journal]').click();
  await page.locator('#btn-report-day').click();assert.equal(await page.locator('#elist .ec').count(),1);
  await page.locator('#btn-report-week').click();assert.equal(await page.locator('#elist .ec').count(),2);
  await page.locator('#btn-report-month').click();assert.equal(await page.locator('#elist .ec').count(),3);
  await page.locator('#btn-progress').click();assert.match(await page.locator('#jp').innerText(),/Progressi/);
  await page.locator('[data-tab=lab]').click();
  const candles=Array.from({length:5000},(_,i)=>({t:1700000000+i*3600,o:100+i*.01,h:101+i*.01,l:99+i*.01,c:100.5+i*.01,v:100}));
  await page.locator('#lab-file').setInputFiles({name:'fixture-ohlc.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(candles))});
  await page.locator('#lab-form [type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('#lab-result')?.textContent.includes('Esperimento completato'));
  await page.locator('[data-tab=dash]').click();
  await page.setViewportSize({width:390,height:844});
  await page.locator('#orbit-stage').scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'no horizontal overflow');
  await page.locator('#orbit-hero').screenshot({path:'artifacts/saturn-mobile.png'});
  await page.locator('#market-quotes').screenshot({path:'artifacts/quotes-mobile.png'});
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('.saturn-motion').isVisible(),false);
  statsDenied=true;
  await page.evaluate(()=>{_orbitMt5Fetch=0;return loadOrbitEquity();});
  assert.match(await page.locator('#system-status').innerText(),/Accesso/,'authorization failure is shown explicitly');
  assert.equal(await page.locator('#orbit-equity').innerText(),'—','a forbidden response clears account data');
  await page.evaluate(()=>{applyStrategyRegistry({strategies:{}},'configurazione');renderOrbitHero();});
  assert.equal(await page.locator('.saturn-satellite').count(),0,'missing registry entries cannot enable strategies');
  assert.match(await page.locator('#orbit-detail').innerText(),/Nessuna strategia/);
  await page.evaluate(()=>{useLocalUser('second-test-user');renderOrbitHero();});
  assert.equal(await page.locator('#orbit-equity').innerText(),'—','account equity does not leak between users');
  // Freeze page timers to measure the shared refresh without an interval racing it.
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now()+100));
  const requestCount=quoteRequests;
  await page.evaluate(()=>Promise.all([loadPrices(),loadPrices(),loadPrices()]));
  assert.equal(quoteRequests,requestCount+1,'concurrent refreshes share one market request');
  assert.deepEqual(errors,[]);
  console.log('Desktop/mobile Saturn, unified quotes, private system stats, journal filters/progress, worker backtest: passed');
} catch(e){fs.mkdirSync('artifacts',{recursive:true});await page.screenshot({path:'artifacts/ui-failure.png',fullPage:true});console.log('UI errors',errors);throw e;} finally {await browser.close();await new Promise(r=>server.close(r));}
