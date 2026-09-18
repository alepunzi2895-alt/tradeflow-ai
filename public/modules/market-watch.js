(function(){
  const symbols=['XAU','XAG','US30','EURUSD','GBPUSD','DXY','OIL','US10Y','US02Y','VIX','SPX','NDX','RUT'];
  const section=document.createElement('section');section.className='desk-section market-watch';
  section.innerHTML='<header class="workspace-heading"><h2>Mercati in orbita</h2><p>Quotazioni dei simboli supportati · valuta nativa · fonte indicata per ogni strumento.</p></header><div class="watch-grid"></div><p class="data-note" role="status"></p>';
  document.getElementById('orbit-hero').after(section);
  let busy=false;
  const grid=section.querySelector('.watch-grid'),status=section.querySelector('[role=status]');
  const cells=new Map();symbols.forEach(symbol=>{const cell=document.createElement('article');cell.className='watch-cell';const name=document.createElement('span');name.textContent=symbol;const price=document.createElement('strong');price.textContent='—';const source=document.createElement('small');source.textContent='In attesa della fonte';cell.append(name,price,source);grid.append(cell);cells.set(symbol,{price,source});});
  async function refresh(){
    if(busy||document.hidden)return;busy=true;
    try{
      const response=await fetchJSON('/api/market?type=prices',9500);
      if(!response?.ok){status.textContent='Aggiornamento non riuscito. I valori eventualmente presenti appartengono all’ultima ricezione.';return;}
      for(const symbol of symbols){const quote=response.prices?.[symbol],cell=cells.get(symbol);const price=Number(quote?.price);cell.price.textContent=quote&&Number.isFinite(price)&&price>0?price.toLocaleString('it-IT',{maximumFractionDigits:/^(EURUSD|GBPUSD)$/.test(symbol)?5:3}):'—';cell.source.textContent=quote?quote._source||response.source||'Fonte non indicata':'Non disponibile';}
      status.textContent='Ricevuto alle '+new Date().toLocaleTimeString('it-IT')+' · le fonti possono fornire quotazioni ritardate. OIL da CL=F, se indicato, è un future.';
    }finally{busy=false;}
  }
  refresh();setInterval(refresh,30000);
})();
