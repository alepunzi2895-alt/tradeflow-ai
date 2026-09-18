// Rendering only. dashboard.js owns the single quote request and refresh clock.
(function(){
  const instruments=[
    ['XAU','XAU/USD',2,'$'],['XAG','XAG/USD',3,'$'],['US30','US30',2,''],
    ['DXY','DXY',3,''],['EURUSD','EUR/USD',5,'$'],['GBPUSD','GBP/USD',5,'$'],
    ['OIL','OIL',2,'$'],['US10Y','US 10Y',3,'%'],['US02Y','US 2Y',3,'%'],
    ['VIX','VIX',2,''],['SPX','S&P 500',2,''],['NDX','NASDAQ 100',2,''],['RUT','RUSSELL 2000',2,'']
  ];
  const section=document.getElementById('market-quotes');
  const grid=section.querySelector('.price-strip'),status=section.querySelector('.quote-status');
  const cells=new Map();
  for(const [symbol,label,decimals,unit] of instruments){
    const cell=document.createElement('article');cell.className='pc';cell.dataset.quoteSymbol=symbol;
    const name=document.createElement('div');name.className='pc-sym';name.textContent=label;
    const price=document.createElement('div');price.className='pc-val';price.textContent='—';
    const change=document.createElement('div');change.className='pc-chg';change.textContent='—';
    const source=document.createElement('div');source.className='pc-source';source.textContent='In attesa';
    cell.append(name,price,change,source);grid.append(cell);
    cells.set(symbol,{cell,price,change,source,decimals,unit,last:null});
  }
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
      ui.price.textContent=ui.unit==='%'?formatted+'%':ui.unit+formatted;
      const change=quote.change;
      ui.change.textContent=typeof change==='number'&&Number.isFinite(change)?(change>=0?'+':'')+change.toLocaleString('it-IT',{minimumFractionDigits:2,maximumFractionDigits:2})+'%':'—';
      ui.change.style.color=!valid||change==null?'var(--dim)':change>=0?'var(--green)':'var(--red)';
      ui.source.textContent=(valid?'':'Ultimo dato · ')+(quote._source||'TradingView');
      ui.cell.title='Ricevuto: '+new Date(quote.received_at||lastSnapshot||Date.now()).toLocaleString('it-IT');
    }
    const time=lastSnapshot?new Date(lastSnapshot).toLocaleTimeString('it-IT'):'—';
    status.textContent=meta.error?'Fonte non disponibile · ultimi valori ricevuti alle '+time:
      'Aggiornamento ogni 5 s · ricevuto alle '+time+(available<instruments.length?' · '+available+'/'+instruments.length+' simboli aggiornati':'')+' · possibile ritardo della fonte';
    status.classList.toggle('quote-error',!!meta.error);
  };
})();
