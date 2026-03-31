// TradeFlow AI — modules/chat.js

// ── CHAT ───────────────────────────────────────────────
const cm=document.getElementById('chat-msgs');
let history=S.get(K.chat,[]);

function addBubble(role,content,dataUrl){
  const w=document.createElement('div');w.className=`bw ${role==='user'?'u':'b'}`;
  if(role!=='user'){
    const m=document.createElement('div');m.className='bmeta';
    m.innerHTML=`<svg class="bico" viewBox="0 0 32 32" fill="none"><path d="M4 20 Q10 8 16 14 Q22 20 28 6" stroke="url(#gh)" stroke-width="2.5" stroke-linecap="round" fill="none"/><path d="M24 6 L28 6 L28 10" stroke="url(#gh)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><defs><linearGradient id="gh" x1="4" y1="20" x2="28" y2="6" gradientUnits="userSpaceOnUse"><stop offset="0%" stop-color="#8b5e1a"/><stop offset="100%" stop-color="#f0d080"/></linearGradient></defs></svg><span class="btm">TradeFlow AI · ${nowT()}</span>`;
    w.appendChild(m);
  }
  const b=document.createElement('div');b.className=`bubble ${role==='user'?'u':'b'}`;
  if(dataUrl){const i=document.createElement('img');i.src=dataUrl;i.className='chart';b.appendChild(i);}
  if(role==='user'){b.append(document.createTextNode(content||''));}
  else{
    b.appendChild(md(content));
    const sc=(content||'').match(/MANIPULATION SCORE[:\s]*(\d+)/i);
    if(sc){
      const s=parseInt(sc[1]);
      const col=s<=3?'var(--green)':s<=6?'var(--yellow)':'var(--red)';
      const lbl=s<=3?'PULITO':s<=6?'MISTO':'MANIPOLATO';
      const badge=document.createElement('div');badge.className='sbadge';
      badge.style.cssText=`background:${col}12;border:1px solid ${col}35`;
      badge.innerHTML=`<div class="sdot" style="background:${col};box-shadow:0 0 5px ${col}"></div><span class="stxt" style="color:${col}">MANIP ${s}/10 · ${lbl}</span>`;
      b.appendChild(badge);
    }
  }
  w.appendChild(b);cm.appendChild(w);cm.scrollTop=cm.scrollHeight;
}

function showDots(){const d=document.createElement('div');d.className='dots';d.id='dots';d.innerHTML='<div class="dot"></div><div class="dot"></div><div class="dot"></div>';cm.appendChild(d);cm.scrollTop=cm.scrollHeight;}
function hideDots(){document.getElementById('dots')?.remove();}

async function send(){
  if(loading)return;
  const inp=document.getElementById('minput');
  const text=inp.value.trim()||(pendingImg?'Analizza questo screenshot. Setup, manipulation score, azioni operative se MT5, coach psicologico.':'');
  if(!text&&!pendingImg)return;
  const curImg=pendingImg;pendingImg=null;inp.value='';inp.style.height='38px';clearImg();
  addBubble('user',text,curImg?.dataUrl||null);
  history.push({role:'user',content:text});
  const recent=history.slice(-6);
  const apiMsgs=recent.map((m,i)=>{
    const isLast=i===recent.length-1;
    if(m.role==='user'){
      if(isLast&&curImg?.b64)return{role:'user',content:[{type:'image',source:{type:'base64',media_type:'image/jpeg',data:curImg.b64}},{type:'text',text:text||'Analizza.'}]};
      return{role:'user',content:m.content||'continua'};
    }
    return{role:'assistant',content:m.content||'continua'};
  });
  loading=true;document.getElementById('bsend').disabled=true;showDots();
  try{
    const reply=await api(apiMsgs);
    hideDots();addBubble('assistant',reply);
    history.push({role:'assistant',content:reply});
    S.set(K.chat,history.slice(-50).map(m=>({role:m.role,content:m.content})));
    autoLearn(reply);
  }catch(e){hideDots();addBubble('assistant',`⚠️ ${e.message}`);}
  loading=false;document.getElementById('bsend').disabled=false;
}

// ── QUICK CHIPS ────────────────────────────────────────
const QUICK=[
  {i:'📊',l:'Bias H4',t:() => `Bias ${window.activeAsset||'XAU'}/USD H4 con prezzo live. Struttura + manipulation score.`},
  {i:'🔗',l:'DXY',t:() => `Analisi correlazione DXY/${window.activeAsset||'XAU'} live. Come impatta il dollaro?`},
  {i:'🎯',l:'Setup H1',t:() => `Setup ${window.activeAsset||'XAU'}/USD H1 con entry, SL, TP1 1.5R, TP2 3R e manipulation score.`},
  {i:'📰',l:'News',t:() => `News macro ad alto impatto oggi su ${window.activeAsset||'XAU'}/USD. Orari, previsioni, strategia.`},
  {i:'😰',l:'Revenge',t:() => 'Ho preso un SL e voglio rientrare subito. Protocollo anti-revenge.'},
  {i:'🧘',l:'Pre-trade',t:() => 'Protocollo pre-trade 3 minuti per stato mentale ottimale.'},
];
function initChips(){
  const c=document.getElementById('qi');
  if(c) c.innerHTML = '';
  QUICK.forEach(q=>{const b=document.createElement('button');b.className='chip';b.textContent=`${q.i} ${q.l}`;b.onclick=()=>{document.getElementById('minput').value=q.t();document.getElementById('minput').focus();switchTab('analysis');};c?.appendChild(b);});
}

// ── IMAGE ──────────────────────────────────────────────
function setImg(data){pendingImg=data;document.getElementById('imgthumb').src=data.dataUrl;document.getElementById('imgprev').classList.add('on');closeOvl('imgsheet');}
function clearImg(){pendingImg=null;document.getElementById('imgprev').classList.remove('on');}
document.getElementById('bimg').onclick=()=>openOvl('imgsheet');
document.getElementById('imgclear').onclick=clearImg;
document.getElementById('sdrop').onclick=()=>document.getElementById('file-in').click();
document.getElementById('file-in').onchange=async e=>{const f=e.target.files?.[0];if(f)setImg(await compress(f));e.target.value='';};
document.getElementById('btn-url').onclick=async()=>{const u=document.getElementById('url-in').value.trim();if(!u)return;try{const r=await fetch(u);const bl=await r.blob();setImg(await compress(new File([bl],'i.jpg',{type:bl.type||'image/jpeg'})));}catch{setImg({dataUrl:u,b64:null,type:'image/jpeg',urlOnly:true});}};
document.getElementById('btn-sc').onclick=()=>closeOvl('imgsheet');
window.addEventListener('paste',async e=>{const it=Array.from(e.clipboardData?.items||[]).find(x=>x.type.startsWith('image/'));if(!it)return;e.preventDefault();setImg(await compress(it.getAsFile()));switchTab('analysis');});

// ── NEWS TOGGLE ────────────────────────────────────────
document.getElementById('bnews').onclick=()=>{
  newsMode=!newsMode;
  document.getElementById('bnews').classList.toggle('news-on',newsMode);
  if(newsMode)addBubble('assistant',`📰 **Modalità News attiva** — Le analisi includeranno il contesto macro e gli eventi ad alto impatto del giorno su ${window.activeAsset||'XAU'}/USD.`);
};
