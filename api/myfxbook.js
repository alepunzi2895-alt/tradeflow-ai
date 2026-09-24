import { requireUser } from '../lib/security.js';
import { vault } from '../lib/mfx-vault.js';
import { getDb } from './db.js';
// TradeFlow AI — api/myfxbook.js
// Proxy per le API ufficiali MyFxBook.
//
// 2026-09-24: sessione gestita LATO SERVER per utente (user_data 'mfx'), con relogin automatico
// quando MyFxBook la invalida (scade col tempo e può essere legata all'IP del login, che su
// Vercel cambia tra invocazioni: login + chiamata nella STESSA invocazione risolve entrambi).
// Il relogin usa le credenziali cifrate (lib/mfx-vault.js), salvate solo se l'utente sceglie
// "Ricorda l'accesso". La password non viene mai restituita al client.

const BASE = 'https://www.myfxbook.com/api';

async function fetchMfx(path, ms = 7000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(`${BASE}${path}`, { signal: ctrl.signal, headers: { 'Accept': 'application/json' } });
    clearTimeout(tid);
    const text = await r.text();
    // MyFxBook sometimes returns malformed JSON — try/catch
    try { return JSON.parse(text); }
    catch (e) { console.error('[myfxbook] JSON parse error:', text.slice(0, 200)); throw new Error('Risposta non valida da MyFxBook'); }
  } catch (e) {
    clearTimeout(tid);
    throw e;
  }
}

const isErr = d => d?.error === true || d?.error === 'true';

// Nomi usati da MyFxBook nel community outlook per gli asset dell'app (le coppie forex hanno
// già il nome giusto, es. EURUSD).
export function mfxSymbol(asset) {
  const a = String(asset || 'XAU').toUpperCase().replace(/[^A-Z0-9]/g, '');
  return ({ XAU: 'XAUUSD', XAG: 'XAGUSD', GOLD: 'XAUUSD', SILVER: 'XAGUSD' })[a] || a;
}

// Cache per utente del community outlook (tutti i simboli in una risposta): evita di martellare
// MyFxBook con un refresh ogni 30s da più tab. Best-effort, sopravvive solo tra invocazioni warm.
const outlookCache = new Map();
const OUTLOOK_TTL_MS = 60 * 1000;
export function clearOutlookCache() { outlookCache.clear(); }   // per i test

async function login(email, password) {
  const d = await fetchMfx(`/login.json?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`);
  if (isErr(d) || !d.session) return { ok: false, message: d.message || 'Login fallito. Verifica email e password MyFxBook.' };
  return { ok: true, session: d.session };
}

// Esegue call(session); se MyFxBook risponde errore di sessione e ci sono credenziali salvate,
// rifà il login, salva la nuova sessione e riprova una volta.
async function withSession(db, user, bodySession, call) {
  const stored = await vault.loadSession(db, user.id);
  let session = stored?.session || bodySession;
  let d = session ? await call(session) : { error: true, message: 'Sessione mancante' };
  if (!isErr(d)) return { d, session };
  const cred = await vault.loadCred(db, user.id);
  if (!cred) return { d, session, needsLogin: true };
  const lg = await login(cred.email, cred.password);
  if (!lg.ok) return { d: { error: true, message: lg.message }, session, needsLogin: true };
  await vault.saveSession(db, user.id, lg.session, cred.email);
  outlookCache.delete(user.id);
  d = await call(lg.session);
  return { d, session: lg.session, renewed: true };
}

// dbFactory iniettabile per i test (stesso pattern di api/db.js::createHandler).
export function createMfxHandler(dbFactory = getDb) {
  return async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Cache-Control', 'no-store');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: true, message: 'Method not allowed' });

  let body = {};
  try {
    body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body || {};
  } catch (e) {
    return res.status(400).json({ error: true, message: 'Invalid JSON' });
  }
  let user;
  try { user = requireUser(req, body); } catch (e) { return res.status(e.status || 401).json({ error: true, message: e.message }); }

  const { action, email, password, session, accountId } = body;

  try {
    const db = dbFactory();

    // ── LOGIN ──────────────────────────────────────────────
    if (action === 'login') {
      if (!email || !password) return res.status(400).json({ error: true, message: 'Email e password richiesti.' });
      const lg = await login(email, password);
      if (!lg.ok) return res.json({ error: true, message: lg.message });
      await vault.saveSession(db, user.id, lg.session, email);
      if (body.remember) await vault.saveCred(db, user.id, email, password);
      else await db.execute({ sql: "DELETE FROM user_data WHERE user_id=? AND doc_type='mfx_cred'", args: [user.id] });
      outlookCache.delete(user.id);
      return res.json({ ok: true, session: lg.session, email, remembered: !!body.remember });
    }

    // ── STATO (al caricamento pagina, anche da un altro dispositivo) ──
    if (action === 'status') {
      const s = await vault.loadSession(db, user.id);
      const remembered = await vault.hasCred(db, user.id);
      return res.json({ ok: true, connected: !!(s?.session || remembered), email: s?.email || null, session: s?.session || null, remembered });
    }

    // ── LOGOUT ─────────────────────────────────────────────
    if (action === 'logout') {
      const s = await vault.loadSession(db, user.id);
      if (s?.session) { try { await fetchMfx(`/logout.json?session=${encodeURIComponent(s.session)}`, 4000); } catch (_) {} }
      await vault.clear(db, user.id);
      outlookCache.delete(user.id);
      return res.json({ ok: true });
    }

    // ── SENTIMENT (community outlook) per qualunque simbolo ──
    if (action === 'sentiment' || action === 'outlook') {
      const symbol = mfxSymbol(body.symbol || body.asset);
      let all = outlookCache.get(user.id);
      let renewed = false, newSession = null;
      if (!all || Date.now() - all.at > OUTLOOK_TTL_MS) {
        const r = await withSession(db, user, session, s => fetchMfx(`/get-community-outlook.json?session=${encodeURIComponent(s)}`));
        if (isErr(r.d)) {
          return res.json({ ok: false, needsLogin: !!r.needsLogin,
            error: r.needsLogin ? 'Collega MyFxBook (tab MyFxBook) per il sentiment retail' : `MyFxBook non disponibile (${r.d.message || 'errore'})` });
        }
        all = { at: Date.now(), symbols: Array.isArray(r.d.symbols) ? r.d.symbols : [] };
        outlookCache.set(user.id, all);
        renewed = !!r.renewed; newSession = r.session;
      }
      const sym = all.symbols.find(s => s.name === symbol || (symbol === 'XAUUSD' && s.name === 'GOLD'));
      if (action === 'outlook') return res.json({ ok: true, outlook: { symbols: all.symbols } });
      if (!sym) return res.json({ ok: false, error: `MyFxBook non pubblica il sentiment per ${symbol}`, symbol,
        available: all.symbols.map(s => s.name).slice(0, 80) });
      const longPct = Number(sym.longPercentage), shortPct = Number(sym.shortPercentage);
      return res.json({ ok: true, symbol, longPct, shortPct, updatedAt: new Date(all.at).toISOString(),
        ...(renewed ? { session: newSession } : {}) });
    }

    // ── ACCOUNTS / HISTORY / OPEN (con relogin automatico) ──
    if (action === 'accounts') {
      const r = await withSession(db, user, session, s => fetchMfx(`/get-my-accounts.json?session=${encodeURIComponent(s)}`, 8000));
      if (isErr(r.d)) return res.json({ error: true, needsLogin: !!r.needsLogin, message: r.d.message || 'Sessione scaduta. Rieffettua il login.' });
      const raw = Array.isArray(r.d.accounts) ? r.d.accounts : [];
      const accounts = raw.map(a => ({
        id: String(a.id || ''),
        name: a.name || 'Account',
        balance: a.balance || 0,
        equity: a.equity || 0,
        gain: a.gain || 0,
        drawdown: a.drawdown || 0,
        currency: a.currency || 'USD',
        broker: a.broker || '',
        server: typeof a.server === 'object' ? (a.server?.name || '') : (a.server || ''),
        deposits: a.deposits || 0,
        profit: a.profit || 0,
        wonTrades: a.wonTrades || 0,
        lostTrades: a.lostTrades || 0,
        totalTrades: (a.wonTrades || 0) + (a.lostTrades || 0),
        profitFactor: a.profitFactor || 0,
        bestTrade: a.bestTrade || 0,
        worstTrade: a.worstTrade || 0,
        lastUpdateDate: a.lastUpdateDate || '',
      }));
      return res.json({ ok: true, accounts, ...(r.renewed ? { session: r.session } : {}) });
    }

    if (action === 'history' || action === 'open') {
      if (!accountId) return res.status(400).json({ error: true, message: 'accountId richiesto.' });
      const path = action === 'history' ? '/get-history.json' : '/get-open-trades.json';
      const r = await withSession(db, user, session, s => fetchMfx(`${path}?session=${encodeURIComponent(s)}&id=${encodeURIComponent(accountId)}`, 8000));
      if (isErr(r.d)) return res.json({ error: true, needsLogin: !!r.needsLogin, message: r.d.message || 'Impossibile caricare i dati MyFxBook.' });
      const extra = r.renewed ? { session: r.session } : {};
      return action === 'history'
        ? res.json({ ok: true, history: r.d.history || [], ...extra })
        : res.json({ ok: true, openTrades: r.d.openTrades || [], ...extra });
    }

    return res.status(400).json({ error: true, message: `Azione "${action}" non supportata.` });

  } catch (e) {
    console.error('[myfxbook] error:', e.message);
    if (e.name === 'AbortError') return res.status(504).json({ error: true, message: 'MyFxBook non risponde (timeout). Riprova.' });
    return res.status(500).json({ error: true, message: 'Errore server: ' + e.message });
  }
  };
}

export default createMfxHandler();
