import jwt from 'jsonwebtoken';
import { timingSafeEqual, createHash } from 'node:crypto';

export function fail(status, message) { return Object.assign(new Error(message), { status }); }
export function jwtSecret() {
  const secret = process.env.JWT_SECRET;
  if (!secret || secret.length < 32) throw fail(503, 'JWT_SECRET non configurato (minimo 32 caratteri)');
  return secret;
}
export function serviceAuthorized(req, body = {}) {
  const expected = process.env.MT5_BOT_SECRET;
  const supplied = req.headers?.['x-bot-secret'] || body.secret;
  if (!expected || !supplied || typeof supplied !== 'string') return false;
  const a = Buffer.from(expected), b = Buffer.from(supplied);
  return a.length === b.length && timingSafeEqual(a, b);
}
export function requireUser(req, body = {}) {
  const bearer = req.headers?.authorization?.match(/^Bearer (.+)$/i)?.[1];
  const cookie = req.headers?.cookie?.split(';').map(x => x.trim()).find(x => x.startsWith('tf_session='))?.slice(11);
  const token = bearer || cookie || body.token;
  if (!token) throw fail(401, 'Accesso richiesto');
  const secret = jwtSecret();
  let user;
  try { user = jwt.verify(token, secret, { algorithms: ['HS256'] }); }
  catch { throw fail(401, 'Sessione scaduta: accedi nuovamente'); }
  if (!user.id || !user.email) throw fail(401, 'Sessione non valida');
  // SameSite cookie plus same-origin check for browser requests.
  const origin = req.headers?.origin;
  if (origin && new URL(origin).host !== req.headers?.host) throw fail(403, 'Origine non consentita');
  return user;
}
export function requireOperator(user) {
  const ids = (process.env.ADMIN_USER_IDS || '').split(',').map(x => x.trim()).filter(Boolean);
  // Use immutable IDs; a profile email must never grant operator rights.
  if (!ids.includes(user.id)) throw fail(403, 'Operazione riservata: configurare ADMIN_USER_IDS');
  return user;
}
export async function ensureSystemReaders(db) {
  await db.execute('CREATE TABLE IF NOT EXISTS system_readers (user_id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)');
}
export async function requireSystemReader(db, user) {
  const operators=(process.env.ADMIN_USER_IDS||'').split(',').map(id=>id.trim());
  if(operators.includes(user.id))return user;
  await ensureSystemReaders(db);
  const result=await db.execute({sql:'SELECT user_id FROM system_readers WHERE user_id=?',args:[user.id]});
  if(!result.rows.length)throw fail(403,'Questo account non è abilitato alla lettura del sistema MT5');
  return user;
}
export function setSession(req, res, token) {
  const secure = req.headers?.['x-forwarded-proto'] === 'https' || process.env.VERCEL;
  res.setHeader('Set-Cookie', `tf_session=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${token ? 2592000 : 0}${secure ? '; Secure' : ''}`);
  res.setHeader('Cache-Control', 'no-store');
}
export async function rateLimit(db, key, limit, seconds) {
  await db.execute('CREATE TABLE IF NOT EXISTS api_limits (id TEXT PRIMARY KEY, n INTEGER NOT NULL, expires INTEGER NOT NULL)');
  const now = Math.floor(Date.now() / 1000);
  const id = createHash('sha256').update(key).digest('hex');
  const r = await db.execute({ sql: `INSERT INTO api_limits(id,n,expires) VALUES (?,1,?)
    ON CONFLICT(id) DO UPDATE SET n=CASE WHEN expires<=? THEN 1 ELSE n+1 END,
    expires=CASE WHEN expires<=? THEN excluded.expires ELSE expires END RETURNING n`, args: [id, now + seconds, now, now] });
  if (Number(r.rows[0].n) > limit) throw fail(429, 'Troppe richieste: riprova tra poco');
}
export function parseBody(req) {
  if (JSON.stringify(req.body || {}).length > 2_000_000) throw fail(413, 'Richiesta troppo grande');
  try {
    const body = typeof req.body === 'string' ? JSON.parse(req.body) : (req.body || {});
    if (!body || Array.isArray(body) || typeof body !== 'object') throw Error();
    return body;
  } catch { throw fail(400, 'JSON non valido'); }
}
