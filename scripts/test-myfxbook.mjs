// MyFxBook server-side session + encrypted credentials (2026-09-24). No network, fake DB.
import assert from 'node:assert/strict';
import jwt from 'jsonwebtoken';
process.env.JWT_SECRET = 'test-secret-that-is-at-least-32-characters-long';
const { createMfxHandler, mfxSymbol, clearOutlookCache } = await import('../api/myfxbook.js');
const { openCred } = await import('../lib/mfx-vault.js');
const dbHandler = (await import('../api/db.js')).createHandler;

// Fake Turso: only the statements used by lib/mfx-vault.js and getUserData.
const rows = new Map();                      // `${user}|${doc}` -> payload
const db = { async execute(q) {
  const sql = typeof q === 'string' ? q : q.sql, a = q.args || [];
  if (sql.startsWith('INSERT INTO user_data')) { rows.set(`${a[1]}|${a[2]}`, a[3]); return { rows: [] }; }
  if (sql.startsWith('SELECT payload FROM user_data WHERE user_id=? AND doc_type=?')) {
    const p = rows.get(`${a[0]}|${a[1]}`); return { rows: p === undefined ? [] : [{ payload: p }] }; }
  if (sql.startsWith('SELECT doc_type, payload FROM user_data WHERE user_id=?')) {
    return { rows: [...rows].filter(([k]) => k.startsWith(a[0] + '|')).map(([k, payload]) => ({ doc_type: k.split('|')[1], payload }))
      .filter(r => !sql.includes("doc_type <> 'mfx_cred'") || r.doc_type !== 'mfx_cred') }; }
  if (sql.startsWith('DELETE FROM user_data WHERE user_id=? AND doc_type IN')) { for (const d of a.slice(1)) rows.delete(`${a[0]}|${d}`); return { rows: [] }; }
  if (sql.startsWith("DELETE FROM user_data WHERE user_id=? AND doc_type='mfx_cred'")) { rows.delete(`${a[0]}|mfx_cred`); return { rows: [] }; }
  throw Error('SQL non gestito nel fake: ' + sql);
} };

const token = jwt.sign({ id: 'alice', email: 'alice@example.test' }, process.env.JWT_SECRET, { algorithm: 'HS256' });
const handler = createMfxHandler(() => db);
async function call(body) {
  let out, status = 200;
  const res = { setHeader() {}, status(s) { status = s; return this; }, json(d) { out = d; return this; }, end() { return this; } };
  await handler({ method: 'POST', headers: { authorization: 'Bearer ' + token }, body }, res);
  return { status, body: out };
}

// Fake MyFxBook: la sessione "old" è scaduta, il login ne rilascia una nuova.
let logins = 0, outlookCalls = 0, currentSession = null;
globalThis.fetch = async url => {
  const u = new URL(url);
  const json = d => ({ ok: true, text: async () => JSON.stringify(d) });
  if (u.pathname.endsWith('/login.json')) {
    if (u.searchParams.get('password') !== 'pw-ok') return json({ error: true, message: 'Wrong password' });
    logins++; currentSession = 'sess-' + logins; return json({ error: false, session: currentSession });
  }
  if (u.pathname.endsWith('/get-community-outlook.json')) {
    outlookCalls++;
    if (u.searchParams.get('session') !== currentSession) return json({ error: true, message: 'Invalid session' });
    return json({ error: false, symbols: [
      { name: 'EURUSD', longPercentage: 35, shortPercentage: 65 },
      { name: 'XAUUSD', longPercentage: 62, shortPercentage: 38 },
      { name: 'GBPUSD', longPercentage: 55, shortPercentage: 45 }] });
  }
  if (u.pathname.endsWith('/logout.json')) return json({ error: false });
  throw Error('URL inattesa ' + url);
};

assert.equal(mfxSymbol('XAU'), 'XAUUSD'); assert.equal(mfxSymbol('eur/usd'), 'EURUSD');

// 1) nessun login → needsLogin, nessuna chiamata al sentiment inventata
let r = await call({ action: 'sentiment', asset: 'XAU' });
assert.equal(r.body.ok, false); assert.equal(r.body.needsLogin, true);

// 2) login sbagliato non salva nulla
r = await call({ action: 'login', email: 'a@x.test', password: 'bad', remember: true });
assert.equal(r.body.error, true); assert.equal(rows.size, 0);

// 3) login con "ricorda": sessione + credenziali cifrate, password mai in chiaro nel DB
r = await call({ action: 'login', email: 'a@x.test', password: 'pw-ok', remember: true });
assert.equal(r.body.ok, true); assert.equal(r.body.remembered, true);
const stored = rows.get('alice|mfx_cred');
assert.ok(stored && !stored.includes('pw-ok'), 'password cifrata a riposo');
assert.equal(openCred(stored).password, 'pw-ok');

// 4) get_user_data non restituisce mai le credenziali al browser
let ud; await dbHandler(() => db)({ method: 'POST', url: '/api/db', headers: { authorization: 'Bearer ' + token },
  body: { action: 'get_user_data' } }, { setHeader() {}, status() { return this; }, json(d) { ud = d; return this; } });
assert.ok(ud.ok, JSON.stringify(ud));
assert.ok(!ud.data.some(x => x.doc_type === 'mfx_cred'), 'mfx_cred mai esposto');
assert.ok(!JSON.stringify(ud).includes('pw-ok'));

// 5) sentiment per più simboli (una sola chiamata grazie alla cache)
r = await call({ action: 'sentiment', asset: 'XAU' }); assert.equal(r.body.longPct, 62);
r = await call({ action: 'sentiment', asset: 'EURUSD' }); assert.equal(r.body.shortPct, 65);
assert.equal(outlookCalls, 1, 'cambio coppia servito dalla cache, niente nuova richiesta');
r = await call({ action: 'sentiment', asset: 'US30' }); assert.equal(r.body.ok, false); assert.match(r.body.error, /US30/);

// 6) MyFxBook invalida la sessione → relogin automatico con le credenziali cifrate
currentSession = 'rotated-by-myfxbook';
clearOutlookCache();                                    // cache scaduta
const handler2 = createMfxHandler(() => db);
r = await (async () => { let out; await handler2({ method: 'POST', headers: { authorization: 'Bearer ' + token }, body: { action: 'sentiment', asset: 'GBPUSD' } },
  { setHeader() {}, status() { return this; }, json(d) { out = d; return this; } }); return { body: out }; })();
assert.equal(r.body.ok, true, JSON.stringify(r.body)); assert.equal(r.body.longPct, 55);
assert.equal(logins, 2, 'un solo relogin'); assert.equal(r.body.session, 'sess-2', 'nuova sessione restituita al client');
assert.equal(JSON.parse(rows.get('alice|mfx')).session, 'sess-2', 'nuova sessione salvata');

// 7) status e logout: il logout cancella sessione e credenziali
r = await call({ action: 'status' }); assert.equal(r.body.connected, true); assert.equal(r.body.remembered, true);
assert.ok(!JSON.stringify(r.body).includes('pw-ok'));
r = await call({ action: 'logout' }); assert.equal(r.body.ok, true);
assert.equal(rows.has('alice|mfx_cred'), false); assert.equal(rows.has('alice|mfx'), false);

// 8) login SENZA "ricorda": nessuna credenziale salvata
r = await call({ action: 'login', email: 'a@x.test', password: 'pw-ok', remember: false });
assert.equal(r.body.ok, true); assert.equal(rows.has('alice|mfx_cred'), false);

console.log('MyFxBook: sessione server, credenziali cifrate, relogin automatico, sentiment multi-coppia — passed');
