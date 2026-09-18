// Stable controls live outside the strategy engine's one-second render target.
(function(){
  const dashboard=document.getElementById('dash-panel');
  function heading(title,copy){const el=document.createElement('header');el.className='workspace-heading';const h=document.createElement('h2');h.textContent=title;const p=document.createElement('p');p.textContent=copy;el.append(h,p);return el;}
  function group(id,title,copy,selectors){
    const section=document.createElement('section');section.id=id;section.className='desk-section';
    const nodes=selectors.map(s=>dashboard.querySelector(s)).filter(Boolean);if(!nodes.length)return;
    nodes[0].before(section);section.append(heading(title,copy));const grid=document.createElement('div');grid.className='desk-grid';section.append(grid);nodes.forEach(n=>grid.append(n));
  }
  group('market-overview','Lettura del mercato','Confluenze, sentiment e prossimi eventi.',['#conf-card','#sent-card','.cal-card']);
  group('strategy-lab','Setup e segnali','Approfondisci i fattori prima di valutare un ingresso.',['.mfkk-card','#layout-strategy-cards']);
  const factors=document.getElementById('conf-factors');
  if(factors){const d=document.createElement('details');d.className='confidence-drivers';d.innerHTML='<summary>Esamina i fattori del punteggio</summary>';factors.before(d);d.append(factors);}
  const lab=document.getElementById('strategy-lab');
  if(lab){const grid=lab.querySelector('.desk-grid');const details=document.createElement('details');details.className='desk-details';details.innerHTML='<summary>Apri analisi tecnica e setup</summary>';lab.append(details);details.append(grid);}
  const target=document.getElementById('se-content');
  if(target){
    const nav=document.createElement('nav');nav.className='desk-tabs';nav.setAttribute('aria-label','Viste strategie');
    [['live','Operatività'],['catalog','Strategie'],['diagnostics','Diagnostica']].forEach(([key,label])=>{const b=document.createElement('button');b.textContent=label;b.dataset.seView=key;b.setAttribute('aria-pressed',String(SE_UI.view===key));nav.append(b);});
    target.before(nav);
    nav.addEventListener('click',e=>{const b=e.target.closest('[data-se-view]');if(!b)return;SE_UI.view=b.dataset.seView;seUiSave();nav.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));if(seLastViewArgs)seRender(...seLastViewArgs);});
  }
  document.addEventListener('click',e=>{if(e.target.closest('[data-action="toggle-blocked-inline"],[data-action="toggle-indicators"]')&&seLastViewArgs)seRender(...seLastViewArgs);});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.ovl.on').forEach(el=>el.classList.remove('on'));});
})();
