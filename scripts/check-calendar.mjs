fetch("https://tradeflow-ai-delta.vercel.app/api/market?type=calendar")
  .then(r => r.json())
  .then(d => console.log(JSON.stringify(d, null, 2)))
  .catch(console.error);
