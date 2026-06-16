// TradeFlow AI — modules/chat.js

// ── CHAT ───────────────────────────────────────────────
const cm=document.getElementById('chat-msgs');
let history=S.get(K.chat,[]);

function addBubble(role,content,dataUrl){
  const w=document.createElement('div');w.className=`bw ${role==='user'?'u':'b'}`;
  w.dataset.role=role; w.dataset.content=content||'';

  // Delete button
  const del=document.createElement('button');del.className='msg-del';del.textContent='×';del.title='Elimina';
  del.onclick=()=>{
    w.remove();
    history=Array.from(cm.querySelectorAll('.bw')).map(el=>({role:el.dataset.role,content:el.dataset.content||''}));
    S.set(K.chat,history.slice(-50));
    window.dbSaveUserData&&window.dbSaveUserData('chat',history.slice(-50));
  };
  w.appendChild(del);

  const b=document.createElement('div');b.className=`bubble ${role==='user'?'u':'b'}`;
  if(dataUrl){const i=document.createElement('img');i.src=dataUrl;i.className='chart';b.appendChild(i);}
  
  if(role==='user'){b.append(document.createTextNode(content||''));}
  else{
    // Assistant metadata for premium look
    const m=document.createElement('div');
    m.style.cssText='font-size:9px;color:var(--g);font-weight:700;margin-bottom:6px;letter-spacing:0.1em;text-transform:uppercase';
    m.innerHTML=`TradeFlow AI · ${nowT()}`;
    b.appendChild(m);
    
    b.appendChild(md(content));
    
    const sc=(content||'').match(/MANIPULATION SCORE[:\s]*(\d+)/i);
    if(sc){
      const s=parseInt(sc[1]);
      const col=s<=3?'var(--green)':s<=6?'var(--yellow)':'var(--red)';
      const lbl=s<=3?'PULITO':s<=6?'MISTO':'MANIPOLATO';
      const badge=document.createElement('div');
      badge.style.cssText=`margin-top:12px;padding:10px;background:rgba(255,255,255,0.03);border:1px solid ${col}44;border-radius:10px;display:flex;align-items:center;gap:8px;font-size:11px;font-weight:700;color:${col}`;
      badge.innerHTML=`<div style="width:6px;height:6px;background:${col};border-radius:50%;box-shadow:0 0 8px ${col}"></div>MANIP ${s}/10 · ${lbl}`;
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
    window.dbSaveUserData && window.dbSaveUserData('chat', history.slice(-50).map(m=>({role:m.role,content:m.content})));
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

// Libreria Foto — sistema gallery picker (no capture = scelta libera)
document.getElementById('sdrop').onclick=()=>document.getElementById('file-in').click();
document.getElementById('file-in').onchange=async e=>{const f=e.target.files?.[0];if(f)setImg(await compress(f));e.target.value='';};

// Fotocamera — capture diretto
document.getElementById('sdrop-cam').onclick=()=>document.getElementById('file-in-cam').click();
document.getElementById('file-in-cam').onchange=async e=>{const f=e.target.files?.[0];if(f)setImg(await compress(f));e.target.value=''};

// URL import
document.getElementById('btn-url').onclick=async()=>{const u=document.getElementById('url-in').value.trim();if(!u)return;try{const r=await fetch(u);const bl=await r.blob();setImg(await compress(new File([bl],'i.jpg',{type:bl.type||'image/jpeg'})));}catch{setImg({dataUrl:u,b64:null,type:'image/jpeg',urlOnly:true});}};
document.getElementById('btn-sc').onclick=()=>closeOvl('imgsheet');

// PASTE handler — desktop + mobile
window.addEventListener('paste',async e=>{
  const items=Array.from(e.clipboardData?.items||[]);
  const imgItem=items.find(x=>x.type.startsWith('image/'));
  if(!imgItem)return;
  e.preventDefault();
  setImg(await compress(imgItem.getAsFile()));
  switchTab('analysis');
});

// Also listen on the textarea specifically (iOS Safari workaround)
document.getElementById('minput').addEventListener('paste',async e=>{
  const items=Array.from(e.clipboardData?.items||[]);
  const imgItem=items.find(x=>x.type.startsWith('image/'));
  if(!imgItem)return;
  e.preventDefault();
  setImg(await compress(imgItem.getAsFile()));
});

// DRAG & DROP on chat area
const chatPanel=document.getElementById('tp-analysis');
if(chatPanel){
  chatPanel.addEventListener('dragover',e=>{e.preventDefault();e.stopPropagation();chatPanel.style.outline='2px dashed var(--g)';chatPanel.style.outlineOffset='-4px';});
  chatPanel.addEventListener('dragleave',e=>{e.preventDefault();chatPanel.style.outline='none';});
  chatPanel.addEventListener('drop',async e=>{
    e.preventDefault();e.stopPropagation();chatPanel.style.outline='none';
    const f=e.dataTransfer?.files?.[0];
    if(f&&f.type.startsWith('image/')){setImg(await compress(f));}
  });
}

// ── NEWS TOGGLE (always on by default) ─────────────────
document.getElementById('bnews').classList.add('news-on');
document.getElementById('bnews').onclick=()=>{
  newsMode=!newsMode;
  document.getElementById('bnews').classList.toggle('news-on',newsMode);
};
