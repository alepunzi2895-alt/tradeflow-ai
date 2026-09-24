// TradeFlow AI — modules/core.js

// ── USER ID ───────────────────────────────────────────────
function genUUID(){
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{
    const r=(Math.random()*16)|0;return(c==='x'?r:(r&0x3)|0x8).toString(16);
  });
}
const USER_ID_KEY='tf_user_id';
const TOKEN_KEY='tf_token';
let userId=localStorage.getItem(USER_ID_KEY);
let sessionToken=localStorage.getItem(TOKEN_KEY);
if(!userId){userId=genUUID();localStorage.setItem(USER_ID_KEY,userId);}
window.userId=userId;
window.sessionToken=sessionToken;

async function authFetch(input, options={}) {
  const url = new URL(typeof input==='string'?input:input.url, location.href);
  const headers = new Headers(options.headers || {});
  if(url.origin===location.origin && url.pathname.startsWith('/api/')) {
    const token=window.sessionToken;
    if(token && token!=='cookie') headers.set('Authorization','Bearer '+token);
  }
  return fetch(input,{...options,headers});
}
window.authFetch=authFetch;
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

// Le zone .sdrop (Journal CSV/screenshot, Knowledge Base, Chat foto) hanno bordo tratteggiato
// che promette drag&drop visivamente, ma nessuna di loro ha mai avuto un vero handler
// dragover/drop — un trascinamento reale attiva il comportamento di default del browser
// (apre/naviga il file), perdendo tutto lo stato dell'app in memoria (audit 2026-09-18).
// Guardia globale: mai lasciare che il browser gestisca un drop di file sulla pagina.
document.addEventListener('dragover', e=>{ e.preventDefault(); });
document.addEventListener('drop', e=>{ e.preventDefault(); });

// ── TURSO DB HELPERS ────────────────────────────────────
/**
 * Returns the server result; failures also surface as a sync notice.
 */
async function dbSave(action, data){
  try {
    const r=await authFetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action,...data,user_id:window.userId}),signal:AbortSignal.timeout(8000)});
    const result=await r.json();
    if(!r.ok || !result.ok) throw Error(result.error || 'Salvataggio non riuscito');
    return result;
  } catch(e) {
    window.dispatchEvent(new CustomEvent('sync-error',{detail:e.message}));
    return {ok:false,error:e.message};
  }
}
window.addEventListener('sync-error',e=>{
  let notice=document.getElementById('sync-notice');
  if(!notice){notice=document.createElement('div');notice.id='sync-notice';notice.setAttribute('role','status');notice.style.cssText='position:fixed;bottom:85px;left:50%;transform:translateX(-50%);z-index:9999;background:#263144;color:#fff;padding:12px 18px;border-radius:12px;max-width:90vw;font-size:12px';document.body.append(notice);}
  notice.textContent='Sincronizzazione: '+e.detail;notice.hidden=false;
  clearTimeout(window._syncNoticeTimer);window._syncNoticeTimer=setTimeout(()=>notice.hidden=true,9000);
});

/**
 * Load data from Turso with timeout. Returns null on failure (fallback to localStorage).
 */
async function dbLoad(action, data={}, timeoutMs=5000){
  try{
    const ctrl=new AbortController();
    const tid=setTimeout(()=>ctrl.abort(),timeoutMs);
    const r=await authFetch('/api/db',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action,...data,user_id:data.user_id||window.userId}),
      signal:ctrl.signal,
    });
    clearTimeout(tid);
    if(!r.ok)return null;
    return await r.json();
  }catch(e){console.log(`[db] ${action} load failed:`,e.message);return null;}
}

window.dbSave=dbSave;
window.dbLoad=dbLoad;

// ── STORAGE ────────────────────────────────────────────
const S={get:(k,d=null)=>{try{const v=localStorage.getItem(k);return v?JSON.parse(v):d;}catch{return d;}},set:(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));}catch{}}};
const STORAGE_BASE={p:'tf_profile',j:'tf_journal',kb:'tf_knowledge',chat:'tf_chat',mfx:'tf_myfx',mem:'tf_memory',amem:'tf_analysis_mem'};
const K=Object.fromEntries(Object.entries(STORAGE_BASE).map(([key,base])=>[key,base+':'+userId]));
for(const [key,base] of Object.entries(STORAGE_BASE)){
  const legacy=localStorage.getItem(base);
  if(legacy!==null){if(localStorage.getItem(K[key])===null)localStorage.setItem(K[key],legacy);localStorage.removeItem(base);}
}
function useLocalUser(id){
  if(id===window.userId)return;
  for(const [key,base] of Object.entries(STORAGE_BASE))K[key]=base+':'+id;
  P=S.get(K.p,defP());entries=S.get(K.j,[]);kb=S.get(K.kb,[]);
  tradeMemory=S.get(K.mem,{entries:{},summary:'',resetDate:null});analysisMemory=S.get(K.amem,{entries:[],lastReset:null});
  mfxSession=S.get(K.mfx,null);history=S.get(K.chat,[]);cm.replaceChildren();
  if(mfxSession?.pass){delete mfxSession.pass;S.set(K.mfx,mfxSession);}
  _orbitMt5=null;_orbitMt5Fetch=0;_orbitError=null;
  if(history.length)renderHistoryMessages(history);
}
const defP=()=>({name:'Alessandro',risk:2,dd:6,tp1:1.5,tp2:3,errors:[],sessions:0,winRate:null,knowledge:[],currency:'USD'});
let P=S.get(K.p,defP()),entries=S.get(K.j,[]),kb=S.get(K.kb,[]);
let tradeMemory=S.get(K.mem,{entries:{},summary:'',resetDate:null});
let analysisMemory=S.get(K.amem,{entries:[],lastReset:null});
let pendingImg=null,loading=false,newsMode=true;
let mfxSession=S.get(K.mfx,null);
if(mfxSession?.pass){delete mfxSession.pass;S.set(K.mfx,mfxSession);}
let marketData=null;
let dashContext={prices:null,confidence:null,sentiment:null,calendar:null};
let fxRates={USD:1,EUR:null,GBP:null,CHF:null,JPY:null};

async function dbSaveUserData(type, payload){
  if(!window.sessionToken) return; // Only sync if fully logged in
  await dbSave('save_user_data', { doc_type: type, payload: JSON.stringify(payload) });
}
window.dbSaveUserData = dbSaveUserData;

// ── CLOUD SYNC & BOOTSTRAP ──────────────────────────────
async function syncStateFromCloud() {
  if (!window.sessionToken) return;
  console.log('[Sync] Sto scaricando user data dal cloud...');
  const res = await dbLoad('get_user_data', { user_id: window.userId });
  if (res && res.ok && res.data) {
    res.data.forEach(row => {
      try {
        const payload = JSON.parse(row.payload);
        if (row.doc_type === 'chat') { history = payload; S.set(K.chat, history); }
        if (row.doc_type === 'kb') { kb = payload; S.set(K.kb, kb); }
        if (row.doc_type === 'mfx') {
          // Solo sessione + email: la password (se "Ricorda l'accesso") resta cifrata sul server.
          mfxSession = payload ? {session:payload.session,email:payload.email} : null;
          S.set(K.mfx, mfxSession);
        }
        if (row.doc_type === 'amem') { analysisMemory = payload; S.set(K.amem, analysisMemory); }
        if (row.doc_type === 'mem') { tradeMemory = payload; S.set(K.mem, tradeMemory); }
      } catch(e) { console.error('Sync error parsing', row.doc_type, e); }
    });
    // rebuild knowledge
    if(kb.length>0){ P.knowledge=kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6); S.set(K.p,P); }
  }
  // Stato MyFxBook dal server (vale su ogni dispositivo) → poi sentiment dell'asset attivo.
  if (typeof mfxRefreshStatus === 'function') await mfxRefreshStatus();
  if (typeof loadSentimentOnly === 'function') loadSentimentOnly();
}
window.syncStateFromCloud = syncStateFromCloud;

// ── AUTO-REGISTER USER ON BOOT (DEPRECATO IN FAVORE DEL LOGIN)
// Non forziamo più la registrazione su Turso al boot se è anonimo.

async function fetchFxRates(){
  if(!P.currency||P.currency==='USD'){fxRates['USD']=1;return;}
  try{
    // TradingView public quote endpoint
    const pairs={EUR:'FX:EURUSD',GBP:'FX:GBPUSD',CHF:'FX:USDCHF',JPY:'FX:USDJPY'};
    const sym=pairs[P.currency];if(!sym)return;
    // Fallback: use our server-side endpoint which uses TradingView data
    const resp=await authFetch(`/api/market?type=fx&currency=${P.currency}`);
    const txt=await resp.text();
    if(!txt.trim().startsWith('<')){
      const d=JSON.parse(txt);
      if(d.rate&&d.rate>0){
        // Yahoo Finance FX conventions:
        // EUR=X → EURUSD rate (e.g. 1.158 = 1 EUR costs 1.158 USD)
        //   To convert: USD → EUR = USD_amount / 1.158
        //   So store: fxRates[EUR] = 1 / 1.158 = 0.8636
        // CHF=X → USDCHF rate (e.g. 0.912 = 1 USD costs 0.912 CHF)  
        //   To convert: USD → CHF = USD_amount * 0.912
        //   So store: fxRates[CHF] = 0.912
        // JPY=X → USDJPY rate (e.g. 149 = 1 USD costs 149 JPY)
        //   To convert: USD → JPY = USD_amount * 149
        //   So store: fxRates[JPY] = 149
        if(P.currency==='EUR'||P.currency==='GBP'){
          fxRates[P.currency] = 1 / d.rate;
        } else {
          fxRates[P.currency] = d.rate;
        }
        console.log('FX rate fetched: 1 USD =', fxRates[P.currency].toFixed(4), P.currency, '(raw rate:', d.rate, ')');
      }
    }
  }catch(e){console.log('FX:',e.message);}
}

function convertPrice(usdPrice){
  // Indici (US30): sono punti indice, non un prezzo in USD → niente conversione FX
  if(window.activeAsset==='US30')return{val:parseFloat(usdPrice).toLocaleString('en-US',{maximumFractionDigits:0}),sym:''};
  // Forex e altri indici: quotazioni/punti, non un prezzo in USD → niente conversione FX
  if(!isCoreAsset(window.activeAsset||'XAU')){const d=instrumentOf(window.activeAsset)?.decimals??2;return{val:parseFloat(usdPrice).toFixed(d),sym:''};}
  if(!P.currency||P.currency==='USD')return{val:parseFloat(usdPrice).toFixed(2),sym:'$'};
  const rate=fxRates[P.currency];
  if(!rate){
    // Return USD as fallback with note
    return{val:parseFloat(usdPrice).toFixed(2),sym:'$'};
  }
  const syms={EUR:'€',GBP:'£',CHF:'Fr.',JPY:'¥'};
  const converted=(parseFloat(usdPrice)*rate);
  const decimals=P.currency==='JPY'?0:2;
  return{val:converted.toFixed(decimals),sym:syms[P.currency]||P.currency};
}

// ── COMPRESS ───────────────────────────────────────────
function compress(file){
  return new Promise(res=>{
    const r=new FileReader();
    r.onload=e=>{
      const img=new Image();
      img.onload=()=>{
        const MAX=800;let w=img.width,h=img.height;
        if(w>MAX){h=Math.round(h*MAX/w);w=MAX;}
        if(h>MAX){w=Math.round(w*MAX/h);h=MAX;}
        const c=document.createElement('canvas');c.width=w;c.height=h;
        c.getContext('2d').drawImage(img,0,0,w,h);
        const du=c.toDataURL('image/jpeg',.65);
        res({dataUrl:du,b64:du.split(',')[1],type:'image/jpeg'});
      };
      img.onerror=()=>{const du=e.target.result;res({dataUrl:du,b64:du.split(',')[1],type:file.type});};
      img.src=e.target.result;
    };
    r.readAsDataURL(file);
  });
}

// ── API ────────────────────────────────────────────────
async function api(messages,system){
  // 1500 token generava spesso oltre 8s (il self-abort server-side di api/chat.js, l'unico modo
  // di restare sotto il cap reale di Vercel senza sapere con certezza il piano — vedi commento
  // in api/chat.js) → "This operation was aborted" su Analisi Journal e Chat (audit 2026-09-23,
  // segnalato dall'utente). Abbassato per stare più affidabilmente sotto quel limite; risposte
  // più corte ma senza troncamenti a metà frase in caso di timeout. Condiviso da chat.js (tab
  // Analisi) e journal.js (bottone 🧠 Analisi) — stesso endpoint, stesso vincolo per entrambi.
  const r=await authFetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:'claude-sonnet-5',max_tokens:800,thinking:{type:'disabled'},system:system||buildSys(),messages})});
  const d=await r.json();
  // api/chat.js inoltra la risposta di Anthropic così com'è in caso di errore API (d.error =
  // oggetto con .message), ma le proprie eccezioni (timeout fetchT, auth) tornano una stringa
  // semplice — prima .message su una stringa dava undefined e si finiva sempre nel fallback
  // JSON.stringify, mostrando all'utente il messaggio vero ma con le virgolette letterali
  // intorno (es. su timeout — audit 2026-09-23).
  if(d.error)throw new Error(typeof d.error==='string' ? d.error : (d.error.message||JSON.stringify(d.error)));
  const t=(d.content||[]).filter(b=>b.type==='text').map(b=>b.text).join('\n').trim();
  if(!t)throw new Error('Risposta vuota');
  return t;
}

function buildSys(){
  const e=P.errors?.length?P.errors.join(', '):'nessuno';
  const k=P.knowledge?.length?'\nKNOWLEDGE BASE PERSONALE:\n'+P.knowledge.slice(-3).join('\n---\n'):'';
  const active = window.activeAsset || 'XAU';
  const news=newsMode?`\nModalità NEWS attiva: includi analisi impatto macro del giorno su ${instrumentLabel(active)}.`:'';

  // ── LIVE MARKET CONTEXT (critico — non ignorare) ───────
  let mktCtx='';
  if(dashContext.prices?.[active]){
    const x=dashContext.prices[active];
    const d=dashContext.prices.DXY;
    const eu=dashContext.prices.EURUSD;
    mktCtx=`

⚠️ DATI DI MERCATO IN TEMPO REALE — USA QUESTI, NON QUELLI DEL TRAINING:
• ${instrumentLabel(active)} PREZZO ATTUALE: $${x.price} (${x.change>=0?'+':''}${x.change}% oggi, Max: $${x.high||'N/D'}, Min: $${x.low||'N/D'})
• DXY: ${d?.price||'N/D'} (${d?.change>=0?'+':''}${d?.change||0}%)
• EUR/USD: ${eu?.price||'N/D'}
• Correlazione DXY/${active}: ${dashContext.prices.CORRELATION?.status||'N/D'} — ${dashContext.prices.CORRELATION?.signal||''}
NOTA CRITICA: Il prezzo ${instrumentLabel(active)} è ATTUALMENTE $${x.price}. Se vedi un grafico con prezzi diversi, sono storici. Basa SEMPRE l'analisi sul prezzo live $${x.price}.`;
  }

  // ── CONFIDENCE SCORE CONTEXT ───────────────────────────
  let confCtx='';
  if(dashContext.confidence){
    const cf=dashContext.confidence;
    confCtx=`

CONFLUENCE SCORE ATTUALE: ${cf.score}/100 — ${cf.bias}
${cf.summary}
Fattori principali:
• Momentum: ${cf.factors.momentum.label} (${cf.factors.momentum.score}/100)
• DXY: ${cf.factors.dxy.label} (${cf.factors.dxy.score}/100)
• Sessione: ${cf.factors.session.label} (${cf.factors.session.score}/100)
• Sentiment: ${cf.factors.sentiment.label} (${cf.factors.sentiment.score}/100)
Usa questo score per calibrare il peso trade: score>70 = full size, 50-70 = ridotto, <50 = micro o no trade.`;
  }

  // ── NEWS / CALENDAR CONTEXT (ALWAYS ACTIVE) ────────────
  let newsCtx='';
  if(dashContext.calendar?.length){
    const now=new Date();
    const soon=dashContext.calendar.filter(ev=>{
      const t=new Date(ev.time);
      const diffH=(t-now)/3600000;
      return ev.impact==='High' && diffH>-2 && diffH<24;
    }).slice(0,3);
    if(soon.length){
      newsCtx=`

NEWS AD ALTO IMPATTO NELLE PROSSIME 24H:
${soon.map(ev=>{
  const t=new Date(ev.time);
  const diffH=(t-new Date())/3600000;
  const timing=diffH<0?'GIÀ USCITA':diffH<2?'TRA MENO DI 2 ORE ⚠️':diffH<6?`tra ${Math.round(diffH)}h`:`${t.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})}`;
  return `• ${ev.event} (${ev.currency}) — ${timing}${ev.forecast?', prev: '+ev.forecast:''}`;
}).join('\n')}
STRATEGIA PRE-NEWS: riduci size o evita nuove entries 30 min prima di eventi ad alto impatto.`;
    } else {
      newsCtx=`\nNessun evento ad alto impatto nelle prossime 24h — condizioni normali per entrare.`;
    }
  } else {
    newsCtx=`\nCalendario economico non disponibile — verifica manualmente prima di operare.`;
  }

  // Analysis memory context
  let memCtx='';
  if(analysisMemory.entries?.length>0){
    const recent=analysisMemory.entries.slice(0,2).map(e=>`[${(e.date||'').slice(0,10)}] ${e.text}`).join('\n');
    memCtx=`\nMEMORIA OPERATIVITÀ SALVATA:\n${recent}`;
  }

  // MFKK score context
  let mfkkCtx='';
  if(dashContext.mfkk&&dashContext.mfkk.score>0){
    const m=dashContext.mfkk;
    mfkkCtx=`\nMFKK STRATEGY SCORE: ${m.score}/100 — ${m.bias} (${m.dir})\nConfluenze: CCI ${m.cciScore}/100 · MACD ${m.macdScore}/100 · ADX ${m.adxScore}/100${m.allThree&&m.strongSignals>=3?' — TUTTI E 3 ALLINEATI':''}\nUsa questo score nella valutazione: score>80=segnale forte, 60-80=buono, <60=attendi.`;
  }

  return `Sei TradeFlow AI, assistente trading istituzionale ${instrumentLabel(active)} e forex. Rispondi SEMPRE in italiano. Brutalmente onesto, operativo.
Profilo: ${P.name} | Rischio: ${P.risk}%/trade | Max DD: ${P.dd}% | TP1: ${P.tp1}R | TP2: ${P.tp2}R | Errori noti: ${e}${mktCtx}${confCtx}${mfkkCtx}${memCtx}${newsCtx}${k}${news}

REGOLE FONDAMENTALI:
1. PREZZO REALE: ${instrumentLabel(active)} vale ATTUALMENTE $${dashContext.prices?.[active]?.price||'~4400'}. Inizia ogni analisi citando il prezzo live della Dashboard. La verità assoluta è il prezzo live, non quello che vedi negli screenshot (che possono essere vecchi).
2. ANALISI STORICO (MT4/MT5): Quando analizzi uno screenshot dello storico (Cronologia):
   - Leggi SOLO trade reali (Buy/Sell).
   - IGNORA CATEGORICAMENTE ogni riga con scritto: Deposit, Withdrawal, Balance, Credit, Bonus, SC-CC, Transfer, Interest.
   - NON calcolare i depositi (es. +1000.00 Deposit) come profitto. Sono solo entrate di capitale. Il P/L deve basarsi solo sui trade chiusi.
3. Per TradingView: struttura, setup, manipulation score 1-10 (1=pulito, 10=manipolato).
4. Integra SEMPRE il Confluence Score attuale nel giudizio finale.
5. Se ci sono news importanti imminenti, segnalalo chiaramente.
6. Usa ### per sezioni.
`;
}

// ── MARKDOWN ───────────────────────────────────────────
function md(text){
  const d=document.createElement('div');
  (text||'').split('\n').forEach(ln=>{
    let el;
    if(ln.startsWith('### ')){el=document.createElement('div');el.className='mh3';el.textContent=ln.slice(4);}
    else if(ln.startsWith('- ')){el=document.createElement('div');el.className='mli';el.innerHTML=bold(ln.slice(2));}
    else if(!ln.trim()){el=document.createElement('div');el.style.height='5px';}
    else{el=document.createElement('div');el.className='mp';el.innerHTML=bold(ln);}
    d.appendChild(el);
  });
  return d;
}
function bold(t){return escapeHtml(t).replace(/\*\*([^*]+)\*\*/g,'<strong class="ms">$1</strong>');}
