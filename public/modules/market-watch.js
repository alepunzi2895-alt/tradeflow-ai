// Rendering only. dashboard.js owns the single quote request and refresh clock.
// DXY/EURUSD/GBPUSD tolte dalla griglia su richiesta utente (2026-09-22): l'app non le
// trada, restavano solo valute in mezzo agli asset veri. Restano fetchate lato server
// (lib/market-quotes.js) perché updateCorrelation()/updateConfidence() in dashboard.js le
// leggono ancora da marketData per il fattore di correlazione — qui è solo la lista di cosa
// si RENDERIZZA, non cosa si fetcha.
(function(){
  const SWITCHABLE=new Set(['XAU','XAG','US30']);   // + gli strumenti del registro (forex/indici), aggiunti sotto
  const instruments=[
    ['XAU','XAU/USD',2,'$'],['XAG','XAG/USD',3,'$'],['US30','US30',2,''],
    ['OIL','OIL',2,'$'],['US10Y','US 10Y',3,'%'],['US02Y','US 2Y',3,'%'],
    ['VIX','VIX',2,''],['SPX','S&P 500',2,''],['NDX','NASDAQ 100',2,''],['RUT','RUSSELL 2000',2,'']
  ];
  const section=document.getElementById('market-quotes');
  const grid=section.querySelector('.price-strip'),status=section.querySelector('.quote-status');
  const cells=new Map();
  // Tutte le quotazioni sono cliccabili: le 3 scambiabili passano l'asset attivo (switchAsset,
  // stesso meccanismo dei tab #asset-seg), le altre aprono il loro punteggio macro dedicato
  // (macro-score.js) — nessun handler duplicato, solo due azioni diverse sullo stesso pattern.
  const mainCount=instruments.length;
  function addCell(target,symbol,label,decimals,unit){
    const switchable=SWITCHABLE.has(symbol);
    const cell=document.createElement('article');cell.className='pc pc-clickable';cell.dataset.quoteSymbol=symbol;
    cell.tabIndex=0;cell.setAttribute('role','button');
    cell.setAttribute('aria-label',switchable?'Passa a '+label:'Analisi '+label);
    cell.title=switchable?'Passa a '+label:'Analisi '+label;
    const name=document.createElement('div');name.className='pc-sym';name.textContent=label;
    const price=document.createElement('div');price.className='pc-val';price.textContent='—';
    const change=document.createElement('div');change.className='pc-chg';change.textContent='—';
    const source=document.createElement('div');source.className='pc-source';source.textContent='In attesa';
    cell.append(name,price,change,source);target.append(cell);
    cells.set(symbol,{cell,price,change,source,decimals,unit,last:null});
  }
  for(const [symbol,label,decimals,unit] of instruments)addCell(grid,symbol,label,decimals,unit);
  // Seconda griglia (2026-09-24): forex major e indici dal registro strumenti, tutti
  // selezionabili come asset attivo. Stesso snapshot quotazioni, nessuna richiesta in più.
  window.instrumentsReady?.then(list=>{
    const extra=list.filter(i=>!i.core);
    if(!extra.length||document.getElementById('fx-quotes'))return;
    const sec=document.createElement('section');sec.className='desk-section';sec.id='fx-quotes';
    sec.setAttribute('aria-labelledby','fx-quotes-title');
    sec.innerHTML='<header class="workspace-heading"><h2 id="fx-quotes-title">Forex e indici</h2><p>Clicca uno strumento per renderlo l’asset attivo (grafico e sentiment)</p></header><div class="price-strip quote-grid"></div>';
    // Sotto il pannello del sistema (orbite): la parte alta della dashboard resta invariata.
    (document.getElementById('orbit-hero')||section).after(sec);
    const g2=sec.querySelector('.price-strip');
    g2.addEventListener('click',e=>{ const cell=e.target.closest('.pc-clickable'); if(cell) activate(cell); });
    g2.addEventListener('keydown',e=>{ if(e.key!=='Enter'&&e.key!==' ')return; const cell=e.target.closest('.pc-clickable'); if(!cell)return; e.preventDefault(); activate(cell); });
    for(const i of extra){SWITCHABLE.add(i.id);addCell(g2,i.id,i.label,i.decimals,i.unit||'');}
    if(typeof marketData!=='undefined'&&marketData)window.updatePriceStrip(marketData,{});
  });
  function activate(cell){
    const symbol=cell.dataset.quoteSymbol;
    if(SWITCHABLE.has(symbol)){ if(typeof window.switchAsset==='function') window.switchAsset(symbol); }
    else if(typeof window.openMacroScore==='function') window.openMacroScore(symbol, cell.querySelector('.pc-sym').textContent);
  }
  grid.addEventListener('click',e=>{ const cell=e.target.closest('.pc-clickable'); if(cell) activate(cell); });
  grid.addEventListener('keydown',e=>{
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
      if(valid){ui.last=fresh;if(grid.contains(ui.cell))available++;}
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
      'Aggiornamento ogni 5 s · ricevuto alle '+time+(available<mainCount?' · '+available+'/'+mainCount+' simboli aggiornati':'')+' · possibile ritardo della fonte';
    status.classList.toggle('quote-error',!!meta.error);
  };
})();
