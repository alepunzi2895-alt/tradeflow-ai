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
const sentimentAssets=[], indicatorAssets=[]; let mfxLoginBody=null, mfxConnected=true;
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
  if(url.pathname==='/api/myfxbook'){
    const SENT={XAU:[62,38],XAG:[70,30],EURUSD:[35,65]};
    if(b.action==='status')json=mfxConnected?{ok:true,connected:true,email:'test@example.test',session:'fixture-session',remembered:true}:{ok:true,connected:false,remembered:false};
    if(b.action==='sentiment'){
      sentimentAssets.push(b.asset);
      await new Promise(r=>setTimeout(r,150));   // latenza: rende osservabili i cambi asset durante una richiesta
      json=!mfxConnected?{ok:false,needsLogin:true,error:'Collega MyFxBook (tab MyFxBook) per il sentiment retail'}
        :SENT[b.asset]?{ok:true,symbol:b.asset,longPct:SENT[b.asset][0],shortPct:SENT[b.asset][1],updatedAt:new Date().toISOString()}
        :{ok:false,error:`MyFxBook non pubblica il sentiment per ${b.asset}`};
    }
    if(b.action==='login'){mfxLoginBody=b;mfxConnected=true;json={ok:true,session:'new-session',email:b.email,remembered:!!b.remember};}
    if(b.action==='logout'){mfxConnected=false;json={ok:true};}
    if(b.action==='accounts')json={ok:true,accounts:[]};
  }
  if(url.pathname==='/api/indicators'||url.pathname==='/api/candles')indicatorAssets.push(url.searchParams.get('asset'));
  if(url.pathname==='/api/price')json={ok:true,price:4000,changePct:0.2};
  if(url.pathname==='/api/kb')json={ok:true,kb:[],knowledge:[]};
  if(url.pathname==='/api/market')json={ok:true,prices:{},events:[]};
  if(url.pathname==='/api/market' && url.searchParams.get('type')==='prices'){
    quoteRequests++;
    if(quoteFailure){await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({ok:false,error:'offline'})});return;}
    const values={XAU:4000,XAG:40,US30:42000,DXY:100,EURUSD:1.08456,GBPUSD:1.23,OIL:70,US10Y:4,US02Y:3.8,VIX:16,SPX:5000,NDX:18000,RUT:2000,
      USDJPY:158.762,USDCHF:.82737,AUDUSD:.70262,USDCAD:1.41346,NZDUSD:.5669,US500:5000,NAS100:18000,GER40:25433,UK100:10680,JP225:65513.77};
    const timestamp=new Date().toISOString();json={ok:true,timestamp,prices:Object.fromEntries(Object.entries(values).map(([key,price])=>[key,{price,change:key==='XAG'?null:.25,_source:'TradingView:'+key,received_at:timestamp}]))};
  }
  await route.fulfill({contentType:'application/json',body:JSON.stringify(json)});
});
try {
  await page.goto(base);
  await page.waitForSelector('.saturn-satellite');
  // 5, non più 3: S00_MFKK/S16_GOLDEN_SQUEEZE riattivate in data/hard_blocks.json (2026-09-22,
  // decisione utente su conto demo) — registrySnapshot() le legge da lì, un roster più grande
  // è il comportamento corretto, non una regressione.
  // 6: + S35_ASIA_BREAK (blocco isolato M5, eligible dal 2026-09-24).
  assert.equal(await page.locator('.saturn-satellite').count(),6);
  // Sentiment MyFxBook dalla sessione lato server, aggiornato al caricamento.
  await page.waitForFunction(()=>document.querySelector('#sent-long-pct')?.textContent==='62%');
  assert.match(await page.locator('#sent-source').innerText(),/MyFxBook ✓ · \d\d:\d\d/);
  await page.waitForFunction(()=>document.querySelector('[data-quote-symbol=XAU] .pc-val')?.textContent.includes('4.000'));
  // Regola audit "niente prezzi duplicati": ogni simbolo compare una sola volta (la griglia
  // forex/indici del registro ha simboli diversi dalla principale, non è un doppione).
  await page.waitForSelector('#fx-quotes .pc');
  assert.equal(await page.evaluate(()=>{const s=[...document.querySelectorAll('[data-quote-symbol]')].map(e=>e.dataset.quoteSymbol);return s.length===new Set(s).size;}),true,'each quote symbol rendered once');
  // 10, non più 13: DXY/EURUSD/GBPUSD tolte dalla griglia visibile (2026-09-22, richiesta
  // utente) — restano fetchate lato server per il fattore di correlazione, solo non renderizzate.
  assert.equal(await page.locator('#market-quotes .pc').count(),10);
  assert.equal(await page.locator('.market-watch,#hdr #bxau,#hdr #bxag').count(),0,'no duplicated price areas');
  assert.equal(await page.locator('[data-quote-symbol=XAG] .pc-chg').innerText(),'—');
  const xauBefore=await page.locator('[data-quote-symbol=XAU] .pc-val').innerText();
  await page.locator('#asset-seg [data-asset=US30]').click();
  assert.match(await page.locator('#lbl-sent-title').innerText(),/US30/);
  await page.waitForFunction(()=>/US30/.test(document.querySelector('#sent-source')?.textContent||''));
  assert.equal(await page.locator('#sent-long-pct').innerText(),'—','nessun numero inventato per un simbolo non coperto');
  // Cambi rapidi durante una richiesta in corso: deve vincere l'ultimo asset scelto.
  await page.locator('#asset-seg [data-asset=XAG]').click();
  await page.locator('#asset-seg [data-asset=XAU]').click();
  await page.waitForFunction(()=>document.querySelector('#sent-long-pct')?.textContent==='62%');
  assert.equal(sentimentAssets.at(-1),'XAU','il cambio asset durante una richiesta non viene perso');
  assert.equal(await page.locator('[data-quote-symbol=XAU] .pc-val').innerText(),xauBefore,'asset selection never replaces the gold quote');
  assert.equal(await page.locator('[data-quote-symbol=US30] .pc-val').innerText(),'42.000,00');
  assert.equal(await page.locator('#system-winrate').innerText(),'66,7%');
  assert.equal(await page.locator('#system-pf').innerText(),'5');
  assert.match(await page.locator('#system-status').innerText(),/3 trade chiusi/);
  assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('tf_myfx:test-user')).pass),undefined,'legacy cloud password is not persisted');
  const first=page.locator('.saturn-satellite').nth(1);
  await page.locator('#orbit-hero').scrollIntoViewIfNeeded();   // l'animazione è in pausa fuori schermo (IntersectionObserver)
  const before=await first.getAttribute('style');
  await page.waitForTimeout(700);
  assert.notEqual(await first.getAttribute('style'),before,'orbits advance');
  // Scroll esplicito: con 5 satelliti (era 3) la card orbita può eccedere il viewport di
  // test, boundingBox() darebbe coordinate fuori schermo e il click atterrerebbe altrove
  // (verificato: colpiva un satellite diverso da quello target — audit 2026-09-22).
  await page.locator('.saturn-universe').scrollIntoViewIfNeeded();
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
  await page.locator('#hdr').screenshot({path:'artifacts/header-desktop.png'});
  await page.locator('#fx-quotes').screenshot({path:'artifacts/fx-quotes-desktop.png'});
  quoteFailure=true;
  await page.evaluate(()=>loadPrices());
  assert.equal(await page.locator('[data-quote-symbol=XAU] .pc-val').innerText(),xauBefore,'failed refresh retains the last value with a stale label');
  assert.match(await page.locator('.quote-status').innerText(),/Fonte non disponibile/);
  quoteFailure=false;await page.evaluate(()=>loadPrices());
  // Registro strumenti: griglia forex/indici, menu "Altri…", pannelli MFKK/confidence onesti.
  const REG=JSON.parse(fs.readFileSync('public/instruments.json','utf8')).instruments;
  await page.waitForFunction(n=>document.querySelectorAll('#fx-quotes .pc').length===n,REG.filter(i=>!i.core).length);
  await page.waitForFunction(()=>document.querySelector('[data-quote-symbol=EURUSD] .pc-val')?.textContent==='1,08456');
  assert.equal(await page.locator('[data-quote-symbol=USDJPY] .pc-val').innerText(),'158,762','decimali dal registro');
  assert.equal(await page.locator('#market-quotes .pc').count(),10,'griglia principale invariata');
  const indBefore=indicatorAssets.length;
  await page.selectOption('#asset-more','EURUSD');
  assert.match(await page.locator('#lbl-sent-title').innerText(),/EUR\/USD/);
  await page.waitForFunction(()=>document.querySelector('#sent-long-pct')?.textContent==='35%');
  assert.equal(await page.locator('#conf-card').evaluate(e=>e.classList.contains('asset-unavailable')),true);
  assert.match(await page.locator('#conf-card .asset-note').innerText(),/EUR\/USD/);
  assert.equal(await page.locator('#mfkk-card').evaluate(e=>e.classList.contains('asset-unavailable')),true);
  await page.waitForTimeout(300);
  assert.ok(!indicatorAssets.slice(indBefore).includes('EURUSD'),'nessun indicatore MFKK chiesto per uno strumento non core');
  assert.equal(await page.evaluate(()=>dashContext.confidence),null,'nessun confidence inventato');
  // Carta della griglia forex → asset attivo; simbolo senza sentiment MyFxBook → messaggio, niente numeri.
  await page.locator('#fx-quotes [data-quote-symbol=GBPUSD]').click();
  await page.waitForFunction(()=>/GBPUSD/.test(document.querySelector('#sent-source')?.textContent||''));
  assert.equal(await page.locator('#sent-long-pct').innerText(),'—');
  assert.equal(await page.locator('#asset-more').inputValue(),'GBPUSD');
  // Ritorno all'oro: pannelli attivi e MFKK ricaricato subito per XAU.
  const indBack=indicatorAssets.length;
  await page.locator('#asset-seg [data-asset=XAU]').click();
  assert.equal(await page.locator('#conf-card').evaluate(e=>e.classList.contains('asset-unavailable')),false);
  await page.waitForFunction(n=>window.__noop||true,indBack);
  await page.waitForTimeout(300);
  assert.ok(indicatorAssets.slice(indBack).includes('XAU'),'MFKK ricaricato subito al cambio asset');
  await page.waitForFunction(()=>document.querySelector('#sent-long-pct')?.textContent==='62%');

  // MyFxBook: accesso ricordato dal server, logout, nuovo login con "Ricorda l'accesso".
  await page.locator('[data-tab=myfx]').click();
  await page.waitForFunction(()=>/accesso ricordato/.test(document.querySelector('#mfx-content')?.textContent||''));
  await page.locator('#mfx-content button',{hasText:'Disconnetti'}).click();
  await page.waitForSelector('#mfx-remember');
  assert.equal(await page.locator('#mfx-remember').isChecked(),true,'ricorda accesso attivo di default');
  await page.waitForFunction(()=>/Collega MyFxBook/.test(document.querySelector('#sent-source')?.textContent||''));
  await page.fill('#mfx-email','test@example.test');await page.fill('#mfx-pass','secret-pw');
  await page.locator('#btn-mfx-login').click();
  await page.waitForFunction(()=>/Connesso a MyFxBook/.test(document.querySelector('#mfx-content')?.textContent||''));
  assert.equal(mfxLoginBody.remember,true);
  const storedMfx=await page.evaluate(()=>localStorage.getItem('tf_myfx:test-user'));
  assert.ok(!storedMfx.includes('secret-pw'),'la password non resta nel browser');
  assert.equal(await page.evaluate(()=>typeof mfxSession.pass),'undefined','la password non resta nemmeno in memoria');
  await page.waitForFunction(()=>document.querySelector('#sent-long-pct')?.textContent==='62%');
  // Asset non core salvato: dopo il reload il registro completo riallinea etichette e selettore.
  await page.evaluate(()=>localStorage.setItem('tf_asset',JSON.stringify('EURUSD')));
  await page.reload();
  await page.waitForFunction(()=>/EUR\/USD/.test(document.querySelector('#lbl-sent-title')?.textContent||''));
  assert.equal(await page.locator('#asset-more').inputValue(),'EURUSD');
  await page.locator('#asset-seg [data-asset=XAU]').click();
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
  await page.locator('#hdr').screenshot({path:'artifacts/header-mobile.png'});
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
  console.log('Desktop/mobile Saturn, unified quotes, MyFxBook session + sentiment per asset, forex/index registry + honest non-core panels, private system stats, journal filters/progress, worker backtest: passed');
} catch(e){fs.mkdirSync('artifacts',{recursive:true});await page.screenshot({path:'artifacts/ui-failure.png',fullPage:true});console.log('UI errors',errors);throw e;} finally {await browser.close();await new Promise(r=>server.close(r));}
