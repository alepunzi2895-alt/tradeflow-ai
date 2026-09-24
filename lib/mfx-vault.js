// Credenziali MyFxBook cifrate lato server (2026-09-24, richiesta utente: "non richiedermela ogni volta").
// La password non torna MAI al browser: vive solo in user_data doc_type 'mfx_cred', cifrata con
// AES-256-GCM. Chiave = HKDF-SHA256 di MFX_ENC_KEY (se impostata) altrimenti JWT_SECRET, con info
// dedicata: le credenziali non sono decifrabili con il solo contenuto del DB.
// Salvataggio solo con consenso esplicito ("Ricorda l'accesso" nel form di login).
import { createCipheriv, createDecipheriv, hkdfSync, randomBytes } from 'node:crypto';
import { jwtSecret } from './security.js';

export const CRED_DOC = 'mfx_cred';
export const SESSION_DOC = 'mfx';

function key() {
  const secret = process.env.MFX_ENC_KEY || jwtSecret();
  return Buffer.from(hkdfSync('sha256', secret, 'tradeflow-mfx', 'mfx-cred-v1', 32));
}

export function sealCred(email, password) {
  const iv = randomBytes(12);
  const c = createCipheriv('aes-256-gcm', key(), iv);
  const ct = Buffer.concat([c.update(String(password), 'utf8'), c.final()]);
  return JSON.stringify({ v: 1, email, iv: iv.toString('base64'), tag: c.getAuthTag().toString('base64'), ct: ct.toString('base64') });
}

export function openCred(payload) {
  if (!payload) return null;
  try {
    const p = JSON.parse(payload);
    const d = createDecipheriv('aes-256-gcm', key(), Buffer.from(p.iv, 'base64'));
    d.setAuthTag(Buffer.from(p.tag, 'base64'));
    const password = Buffer.concat([d.update(Buffer.from(p.ct, 'base64')), d.final()]).toString('utf8');
    return { email: p.email, password };
  } catch { return null; }          // chiave cambiata o payload corrotto → serve un nuovo login
}

async function upsert(db, userId, docType, payload) {
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [`${userId}:${docType}`, userId, docType, payload],
  });
}

async function read(db, userId, docType) {
  const r = await db.execute({ sql: 'SELECT payload FROM user_data WHERE user_id=? AND doc_type=?', args: [userId, docType] });
  return r.rows[0]?.payload ?? null;
}

export const vault = {
  async saveCred(db, userId, email, password) { await upsert(db, userId, CRED_DOC, sealCred(email, password)); },
  async loadCred(db, userId) { return openCred(await read(db, userId, CRED_DOC)); },
  async hasCred(db, userId) { return !!(await read(db, userId, CRED_DOC)); },
  async saveSession(db, userId, session, email) { await upsert(db, userId, SESSION_DOC, JSON.stringify({ session, email })); },
  async loadSession(db, userId) { try { return JSON.parse(await read(db, userId, SESSION_DOC) || 'null'); } catch { return null; } },
  async clear(db, userId) {
    await db.execute({ sql: 'DELETE FROM user_data WHERE user_id=? AND doc_type IN (?, ?)', args: [userId, CRED_DOC, SESSION_DOC] });
  },
};
