// Using native fetch in Node 24+

const BASE_URL = 'https://tradeflow-ai-delta.vercel.app';

async function testAll() {
  console.log('--- STARTING CONSOLIDATED API TESTS ---');

  // 1. Test Price Hub (Legacy endpoint /api/price)
  try {
    const res = await fetch(`${BASE_URL}/api/price?asset=XAU`);
    const data = await res.json();
    console.log('✅ Price Hub (XAU):', data.price ? 'Value: ' + data.price : 'Failed: ' + JSON.stringify(data));
  } catch (e) {
    console.log('❌ Price Hub failed:', e.message);
  }

  // 2. Test Candles (Legacy endpoint /api/candles)
  try {
    const res = await fetch(`${BASE_URL}/api/candles?asset=XAU&range=1d&interval=1h`);
    const data = await res.json();
    console.log('✅ Candles Hub:', data.ok ? 'Count: ' + data.count : 'Failed: ' + JSON.stringify(data));
  } catch (e) {
    console.log('❌ Candles Hub failed:', e.message);
  }

  // 3. Test Market / Analysis (Legacy endpoint /api/market)
  try {
    const res = await fetch(`${BASE_URL}/api/market?type=prices`);
    const data = await res.json();
    console.log('✅ Analysis Hub (Market):', data.ok ? 'Prices: ' + Object.keys(data.prices).join(',') : 'Failed: ' + JSON.stringify(data));
  } catch (e) {
    console.log('❌ Analysis Hub failed:', e.message);
  }

  // 4. Test Indicators (Legacy endpoint /api/indicators)
  try {
    const res = await fetch(`${BASE_URL}/api/indicators?asset=XAU&tf=1h`);
    const data = await res.json();
    console.log('✅ Analysis Hub (Indicators):', data.ok ? 'MACD: ' + data.macd.macd : 'Failed: ' + JSON.stringify(data));
  } catch (e) {
    console.log('❌ Indicators Hub failed:', e.message);
  }

  // 5. Test DB / Auth (Legacy endpoint /api/auth)
  try {
    const res = await fetch(`${BASE_URL}/api/db`, { method: 'GET' });
    const data = await res.json();
    console.log('✅ DB Hub Health:', data.ok ? 'Service: ' + data.service : 'Failed: ' + JSON.stringify(data));
  } catch (e) {
    console.log('❌ DB Hub health failed:', e.message);
  }

  console.log('--- TESTS COMPLETED ---');
}

testAll();
