// TradeFlow AI — modules/instruments.js
// Registro strumenti nel browser. Fonte unica: /instruments.json (stesso file letto da
// lib/instruments.js lato server e dagli script Python). I 3 strumenti "core" sono inline
// così etichette/grafico funzionano anche prima che il registro completo sia arrivato.
(function(){
  const CORE=[
    {id:'XAU',label:'XAU/USD',name:'Oro',type:'metal',core:true,decimals:2,unit:'$',chart:'OANDA:XAUUSD',mfx:'XAUUSD'},
    {id:'XAG',label:'XAG/USD',name:'Argento',type:'metal',core:true,decimals:3,unit:'$',chart:'OANDA:XAGUSD',mfx:'XAGUSD'},
    {id:'US30',label:'US30',name:'Dow Jones 30',type:'index',core:true,decimals:2,unit:'',chart:'OANDA:US30USD',mfx:'US30'},
  ];
  let list=CORE.slice();
  const byId=()=>new Map(list.map(i=>[i.id,i]));
  let map=byId();
  window.instrumentOf=id=>map.get(String(id||'XAU').toUpperCase())||null;
  window.instrumentLabel=id=>window.instrumentOf(id)?.label||String(id||'XAU');
  // Simbolo "compatto" (XAUUSD, EURUSD, US30) per journal/AI/MyFxBook.
  window.instrumentPair=id=>{const i=window.instrumentOf(id);return i?.mfx||(i?i.label.replace('/',''):String(id||'XAU'));};
  window.isCoreAsset=id=>!!window.instrumentOf(id)?.core;
  window.instrumentList=()=>list.slice();
  window.instrumentsReady=fetch('/instruments.json',{cache:'no-cache'})
    .then(r=>r.ok?r.json():null)
    .then(d=>{if(Array.isArray(d?.instruments)&&d.instruments.length){list=d.instruments;map=byId();}return list;})
    .catch(()=>list);
})();
