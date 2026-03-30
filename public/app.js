// TradeFlow AI — app.js

// ── TRADINGVIEW CHART WIDGET ─────────────────────────────
function initTVChart(){
  try{
    if(typeof TradingView === 'undefined') return;
    new TradingView.widget({
      container_id: "tv-chart-widget",
      autosize: true,
      symbol: "OANDA:XAUUSD",
      interval: "60",
      timezone: "Europe/Rome",
      theme: "dark",
      style: "1",
      locale: "it",
      toolbar_bg: "#0d0f12",
      enable_publishing: false,
      hide_top_toolbar: false,
      hide_legend: true,
      save_image: false,
      backgroundColor: "#0d0f12",
      gridColor: "#1e222a",
      hide_side_toolbar: true,
      allow_symbol_change: false,
      studies: ["RSI@tv-basicstudies","MACD@tv-basicstudies"],
      withdateranges: false,
      details: false,
      hotlist: false,
      calendar: false,
      width: "100%",
      height: 220,
    });
  }catch(e){ console.log('TradingView widget:', e.message); }
}

// ── AUTO LEARN ──────────────────────────────────────────
function autoLearn(text){
  const lo=text.toLowerCase();
  const map=[['revenge','revenge trading'],['oversize','oversize'],['fomo','FOMO'],['senza sl','senza SL'],['overtrading','overtrading'],['breakout falso','breakout falsi']];
  let ch=false;const errs=[...(P.errors||[])];
  map.forEach(([k,l])=>{if(lo.includes(k)&&!errs.includes(l)){errs.push(l);ch=true;}});
  if(ch||true){P.errors=errs;P.sessions=(P.sessions||0)+1;S.set(K.p,P);updateHdr();}
}

// ── PROFILE ─────────────────────────────────────────────
function openProfile(){
  document.getElementById('pname').value=P.name||'';
  const pcurr=document.getElementById('pcurrency');
  if(pcurr)pcurr.value=P.currency||'USD';
  const sl=document.getElementById('psliders');
  const defs=[{lb:'Risk %',k:'risk',min:.5,max:5,step:.5},{lb:'Max DD %',k:'dd',min:1,max:15,step:1},{lb:'TP1 R',k:'tp1',min:1,max:3,step:.5},{lb:'TP2 R',k:'tp2',min:2,max:10,step:.5}];
  sl.innerHTML=defs.map(d=>`<div class="ff"><div class="rlbl">${d.lb} <span class="rval" id="rv-${d.k}">${P[d.k]}</span></div><input type="range" min="${d.min}" max="${d.max}" step="${d.step}" value="${P[d.k]||d.min}" id="rs-${d.k}" oninput="document.getElementById('rv-${d.k}').textContent=this.value"></div>`).join('');
  const pw=document.getElementById('perrs-wrap');const pt=document.getElementById('perrs-tags');
  if(P.errors?.length){pw.style.display='block';pt.innerHTML=P.errors.map(e=>`<span style="font-size:11px;background:#ff475712;border:1px solid #ff475722;border-radius:4px;padding:2px 8px;color:#ff8a80;cursor:pointer" onclick="removeErr('${e}')">✕ ${e}</span>`).join('');}else{pw.style.display='none';}
  openOvl('profsheet');
}
function removeErr(e){P.errors=P.errors.filter(x=>x!==e);openProfile();}
function saveProfile(){
  P.name=document.getElementById('pname').value||'Trader';
  const pcurr=document.getElementById('pcurrency');
  if(pcurr)P.currency=pcurr.value;
  ['risk','dd','tp1','tp2'].forEach(k=>{const el=document.getElementById(`rs-${k}`);if(el)P[k]=parseFloat(el.value);});
  S.set(K.p,P);closeOvl('profsheet');updateHdr();
  // Immediately fetch new FX rate and refresh prices
  fetchFxRates().then(()=>{
    if(marketData)updatePriceStrip(marketData);
  });
}

function updateHdr(){
  document.getElementById('lsub').textContent=`XAU/USD · DXY · FOREX · ${(P.name||'').toUpperCase()}`;
  const be=document.getElementById('berr');
  if(P.errors?.length){be.style.display='';be.textContent=`⚠${P.errors.length}`;}else{be.style.display='none';}
}

// ── BACKUP / RESTORE ─────────────────────────────────────
function exportData(){
  const data={profile:P,journal:entries,kb,chat:history.slice(-50).map(m=>({role:m.role,content:m.content})),exportedAt:new Date().toISOString(),app:'TradeFlowAI',version:3};
  const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);const a=document.createElement('a');
  a.href=url;a.download=`tradeflow-backup-${new Date().toISOString().slice(0,10)}.json`;a.click();URL.revokeObjectURL(url);
}
function importData(file){
  const r=new FileReader();
  r.onload=e=>{
    try{
      const data=JSON.parse(e.target.result);
      if(data.profile){P={...defP(),...data.profile};S.set(K.p,P);}
      if(data.journal){entries=data.journal;S.set(K.j,entries);}
      if(data.kb){kb=data.kb;S.set(K.kb,kb);}
      if(data.knowledge){kb=data.knowledge;S.set(K.kb,kb);}
      if(data.chat){history=data.chat;S.set(K.chat,data.chat);}
      // Always rebuild knowledge from KB docs
      if(kb.length>0){
        P.knowledge=kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6);
        S.set(K.p,P);
      }
      updateHdr();renderJournal();renderKb();closeOvl('profsheet');
      alert('✅ Backup importato! '+kb.length+' documenti KB ripristinati.');
    }catch(err){alert('❌ File non valido: '+err.message);}
  };
  r.readAsText(file);
}

// ── TABS ────────────────────────────────────────────────
function switchTab(tab){
  document.querySelectorAll('.tb').forEach(b=>b.classList.remove('on'));
  document.querySelectorAll('.tp').forEach(p=>p.classList.remove('on'));
  document.querySelector(`[data-tab="${tab}"]`).classList.add('on');
  const panel=document.getElementById(`tp-${tab}`);
  panel.classList.add('on');
  // Reset scroll to top on tab switch
  const dp=panel.querySelector('.dp,.jp,.kbp,.mfxp');
  if(dp) dp.scrollTop=0;
  if(tab==='journal')renderJournal();
  if(tab==='kb')renderKb();
  if(tab==='myfx')renderMyfx();
}
document.querySelectorAll('.tb').forEach(btn=>btn.onclick=()=>switchTab(btn.dataset.tab));

// ── OVERLAYS ────────────────────────────────────────────
function openOvl(id){document.getElementById(id).classList.add('on');}
function closeOvl(id){document.getElementById(id).classList.remove('on');}
['imgsheet','csvsheet','scrsheet','profsheet'].forEach(id=>{
  document.getElementById(id).onclick=e=>{if(e.target===document.getElementById(id))closeOvl(id);};
});

// ── EVENTS ──────────────────────────────────────────────
// Safe button wiring - never crash if element missing
function wire(id, fn){ const el=document.getElementById(id); if(el) el.onclick=fn; }

document.getElementById('bsend').onclick=send;
document.getElementById('minput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}});
document.getElementById('minput').addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,88)+'px';});
document.getElementById('btn-set').onclick=openProfile;
document.getElementById('btn-psave').onclick=saveProfile;
document.getElementById('btn-preset').onclick=()=>{if(confirm('Reset completo?')){[K.j,K.kb,K.chat,K.mfx].forEach(k=>S.set(k,[]));S.set(K.p,defP());location.reload();}};
document.getElementById('btn-export').onclick=exportData;
// KB export button (wired after render)
document.addEventListener('click',e=>{
  if(e.target.id==='btn-kb-export')exportKb();
});
document.getElementById('btn-import-data').onclick=()=>document.getElementById('import-file').click();
document.getElementById('import-file').onchange=e=>{const f=e.target.files?.[0];if(f)importData(f);e.target.value='';};

// ── UTILS ───────────────────────────────────────────────
function nowT(){return new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});}

// ── INIT ────────────────────────────────────────────────
initChips();updateHdr();
kb=S.get(K.kb,[]);
updateMemoryInfo();
// Always rebuild knowledge summaries from KB docs on init (survives version updates)
if(kb.length>0){
  P.knowledge=kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6);
  S.set(K.p,P);
}
renderKb();

// Initial confidence render (will update when prices load)
try{updateConfidence({},{});}catch(e){}

// Restore chat history
if(history.length>0){
  history.forEach(m=>addBubble(m.role,m.content||''));
  addBubble('assistant','_Sessione ripristinata — '+history.length+' messaggi precedenti._');
}else{
  addBubble('assistant','**TradeFlow AI — Online** 🚀\n\n**Dashboard:** prezzi live, DXY correlation, confidence score, calendario economico, sentiment retail.\n\n**Analisi:** screenshot TradingView/MT5, manipulation score, coach psicologico integrato.\n\n**Journal:** import CSV, screenshot storico, MyFxBook.\n\nPremi 📷 per analizzare un grafico.');
}

// Prevent browser scroll restoration
if('scrollRestoration' in history) history.scrollRestoration = 'manual';

// Guard: wrap all init in try/catch so one error never blocks everything
window.onerror = function(msg, src, line, col, err) {
  console.error('JS Error:', msg, 'line:', line);
  return false; // don't suppress
};

// Render UI immediately with placeholders (never block)
try{ renderPlaceholders(); }catch(e){ console.error('renderPlaceholders:', e); }
// Stagger loads to avoid hammering APIs simultaneously
// Force scroll to top on load
document.querySelectorAll('.dp,.jp,.kbp,.mfxp').forEach(el=>{ el.scrollTop=0; });

setTimeout(loadPrices, 100);
setTimeout(()=>{ try{updateConfidence({XAU:{price:'0',change:0}},{});} catch(e){} }, 50);
setTimeout(loadCotData, 5000);
setTimeout(loadSlowData, 1500);

setTimeout(loadIndicators, 3000);
// Confidence score with session data immediately (no API needed)
try{updateConfidence({},{});}catch(e){}
// Refresh intervals
setInterval(loadPrices, 3000);
setInterval(loadSlowData, 30000);
setInterval(loadSentimentOnly, 3000);
setInterval(loadIndicatorCandles, 60000);
setInterval(recalcIndicators, 5000);
setInterval(()=>{if(P.currency&&P.currency!=='USD')fetchFxRates();}, 60000);
// GitHub KB sync
checkKbSync();
