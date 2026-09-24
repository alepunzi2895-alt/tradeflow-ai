// Rendering only. dashboard.js owns the single quote request and refresh clock.
// DXY/EURUSD/GBPUSD tolte dalla griglia su richiesta utente (2026-09-22): l'app non le
// trada, restavano solo valute in mezzo agli asset veri. Restano fetchate lato server
// (lib/market-quotes.js) perché updateCorrelation()/updateConfidence() in dashboard.js le
// leggono ancora da marketData per il fattore di correlazione — qui è solo la lista di cosa
// si RENDERIZZA, non cosa si fetcha.
(function(){
  // 2026-09-24 (richiesta utente): un'unica sezione "Quotazioni" divisa per gruppo. Gli strumenti
  // tradabili vengono dal registro (public/instruments.json) e diventano l'asset attivo al click;
  // le quotazioni di contesto (petrolio, Russell, VIX, rendimenti) aprono il punteggio macro.
  // S&P 500 e Nasdaq 100 non sono più doppioni: sono US500 e NAS100 del registro.
  const SWITCHABLE=new Set(['XAU','XAG','US30']);
  const GROUPS=[['commodities','Materie prime'],['indices','Indici e tassi'],['fx','Forex']];
  const MACRO={commodities:[['OIL','OIL',2,'$']],
    indices:[['RUT','RUSSELL 2000',2,''],['VIX','VIX',2,''],['US10Y','US 10Y',3,'%'],['US02Y','US 2Y',3,'%']],fx:[]};
  const CORE={commodities:[['XAU','XAU/USD',2,'$'],['XAG','XAG/USD',3,'$']],indices:[['US30','US30',2,'']],fx:[]};
  const groupOf=i=>i.type==='fx'?'fx':i.type==='index'?'indices':'commodities';
  const section=document.getElementById('market-quotes');
  const status=section.querySelector('.quote-status');
  const holder=section.querySelector('.price-strip');
  const wrap=document.createElement('div');wrap.className='quote-groups';
  const grids={};
  for(const [key,title] of GROUPS){
    const g=document.createElement('div');g.className='quote-group';g.dataset.group=key;
    const h=document.createElement('h3');h.className='quote-group-title';h.textContent=title;
    const grid=document.createElement('div');grid.className='price-strip quote-grid';
    g.append(h,grid);wrap.append(g);grids[key]=grid;
  }
  holder.replaceWith(wrap);
  const cells=new Map();
  function addCell(target,symbol,label,decimals,unit,before=null){
    if(cells.has(symbol))return;
    const switchable=SWITCHABLE.has(symbol);
    const cell=document.createElement('article');cell.className='pc pc-clickable';cell.dataset.quoteSymbol=symbol;
    cell.tabIndex=0;cell.setAttribute('role','button');
    cell.setAttribute('aria-label',switchable?'Passa a '+label:'Analisi '+label);
    cell.title=switchable?'Passa a '+label:'Analisi '+label;
    const name=document.createElement('div');name.className='pc-sym';name.textContent=label;
    const price=document.createElement('div');price.className='pc-val';price.textContent='—';
    const change=document.createElement('div');change.className='pc-chg';change.textContent='—';
    const source=document.createElement('div');source.className='pc-source';source.textContent='In attesa';
    cell.append(name,price,change,source);target.insertBefore(cell,before);
    cells.set(symbol,{cell,price,change,source,decimals,unit,last:null});
  }
  for(const [key] of GROUPS){
    for(const c of CORE[key])addCell(grids[key],...c);
    for(const c of MACRO[key])addCell(grids[key],...c);
  }
  // Strumenti non core del registro: dopo i core, prima delle quotazioni di contesto del gruppo.
  window.instrumentsReady?.then(list=>{
    for(const i of list.filter(x=>!x.core)){
      const key=groupOf(i),firstMacro=MACRO[key][0]?cells.get(MACRO[key][0][0])?.cell:null;
      SWITCHABLE.add(i.id);addCell(grids[key],i.id,i.label,i.decimals,i.unit||'',firstMacro||null);
    }
    if(typeof marketData!=='undefined'&&marketData)window.updatePriceStrip(marketData,{});
  });
  function activate(cell){
    const symbol=cell.dataset.quoteSymbol;
    if(SWITCHABLE.has(symbol)){ if(typeof window.switchAsset==='function') window.switchAsset(symbol); }
    else if(typeof window.openMacroScore==='function') window.openMacroScore(symbol, cell.querySelector('.pc-sym').textContent);
  }
  wrap.addEventListener('click',e=>{ const cell=e.target.closest('.pc-clickable'); if(cell) activate(cell); });
  wrap.addEventListener('keydown',e=>{
    if(e.key!=='Enter' && e.key!==' ')return;
    const cell=e.target.closest('.pc-clickable');
    if(!cell)return;
    e.preventDefault(); activate(cell);
  });
  let lastSnapshot=null;
  window.updatePriceStrip=function(prices={},meta={}){
    if(meta.timestamp)lastSnapshot=meta.timestamp;
    let available=0;
    for(const [symbol,ui] of cells){
      const fresh=prices[symbol];
      const valid=typeof fresh?.price==='number' && Number.isFinite(fresh.price) && fresh.price>0;
      if(valid){ui.last=fresh;available++;}
      const quote=valid?fresh:ui.last;
      ui.cell.classList.toggle('main',symbol===(window.activeAsset||'XAU'));
      ui.cell.classList.toggle('quote-stale',!valid);
      if(!quote){ui.price.textContent='—';ui.change.textContent='—';ui.source.textContent=meta.error?'Non disponibile':'In attesa';continue;}
      const formatted=quote.price.toLocaleString('it-IT',{useGrouping:'always',minimumFractionDigits:ui.decimals,maximumFractionDigits:ui.decimals});
      const prevPrice=ui.price.dataset.rawPrice?Number(ui.price.dataset.rawPrice):null;
      ui.price.textContent=ui.unit==='%'?formatted+'%':ui.unit+formatted;
      // Flash verde/rosso ad ogni variazione reale di prezzo — conferma visiva che il
      // simbolo si aggiorna davvero anche quando il valore cambia poco (es. yield, indici
      // fuori sessione) e il numero da solo non lo comunica (richiesta utente 2026-09-22).
      if(valid && prevPrice!==null && quote.price!==prevPrice){
        ui.cell.classList.remove('pc-flash-up','pc-flash-down');
        void ui.cell.offsetWidth; // riavvia l'animazione CSS anche su flash dello stesso segno
        ui.cell.classList.add(quote.price>prevPrice?'pc-flash-up':'pc-flash-down');
      }
      if(valid)ui.price.dataset.rawPrice=String(quote.price);
      const change=quote.change;
      ui.change.textContent=typeof change==='number'&&Number.isFinite(change)?(change>=0?'+':'')+change.toLocaleString('it-IT',{minimumFractionDigits:2,maximumFractionDigits:2})+'%':'—';
      ui.change.style.color=!valid||change==null?'var(--dim)':change>=0?'var(--green)':'var(--red)';
      ui.source.textContent=(valid?'':'Ultimo dato · ')+(quote._source||'TradingView');
      const label=ui.cell.querySelector('.pc-sym').textContent;
      ui.cell.title=(SWITCHABLE.has(symbol)?'Passa a '+label:'Analisi '+label)+' · Ricevuto: '+new Date(quote.received_at||lastSnapshot||Date.now()).toLocaleString('it-IT');
    }
    const time=lastSnapshot?new Date(lastSnapshot).toLocaleTimeString('it-IT'):'—';
    status.textContent=meta.error?'Fonte non disponibile · ultimi valori ricevuti alle '+time:
      'Aggiornamento ogni 5 s · ricevuto alle '+time+(available<cells.size?' · '+available+'/'+cells.size+' simboli aggiornati':'')+' · possibile ritardo della fonte';
    status.classList.toggle('quote-error',!!meta.error);
  };
})();
