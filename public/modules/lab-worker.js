importScripts('/modules/lab-engine.js?v=audit1');
self.onmessage=({data:{candles,config,mode}})=>{
  try {
    const normalized=LabEngine.normalize(candles);
    const result=mode==='indicators'
      ?Object.fromEntries(Object.keys(LabEngine.catalog).map(k=>[k,LabEngine.indicator(normalized,k,14).at(-1)]))
      :LabEngine.run(normalized,config);
    self.postMessage({ok:true,result});
  } catch(e){self.postMessage({ok:false,error:e.message});}
};
