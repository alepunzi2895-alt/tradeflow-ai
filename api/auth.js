// TradeFlow AI — api/auth.js
import { createClient } from "@libsql/client";
import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";

const JWT_SECRET = process.env.JWT_SECRET || "tradeflow-fallback-secret-key-1234";

function getDb() {
  let url = process.env.TURSO_DB_URL;
  const token = process.env.TURSO_AUTH_TOKEN;
  if (!url || !token) throw new Error("TURSO_DB_URL or TURSO_AUTH_TOKEN missing");
  if (url.startsWith("libsql://")) url = url.replace("libsql://", "https://");
  return createClient({ url, authToken: token });
}

function uuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  if (req.method === "OPTIONS") return res.status(200).end();

  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { return res.status(400).json({ error: "Invalid JSON" }); }
  }

  const { action, email, password, name, current_user_id } = body;
  if (!action || !email || !password) return res.status(400).json({ error: "action, email and password required" });

  try {
    const db = getDb();

    if (action === "register") {
      // Check if user already exists
      const existing = await db.execute({ sql: "SELECT id FROM users WHERE email=?", args: [email] });
      if (existing.rows.length > 0) {
        return res.status(400).json({ ok: false, error: "Email già registrata." });
      }

      // We might migrate an existing local user if current_user_id is passed, or generate a new one
      const userId = current_user_id || uuid();
      const hashed = await bcrypt.hash(password, 10);

      // Insert or update (if migrating anon user)
      await db.execute({
        sql: `INSERT INTO users (id, name, email, password, risk, max_dd, tp1, tp2, currency)
              VALUES (?, ?, ?, ?, 2, 6, 1.5, 3.0, 'USD')
              ON CONFLICT(id) DO UPDATE SET
                email=excluded.email,
                password=excluded.password,
                name=COALESCE(excluded.name, name)`,
        args: [userId, name || "Trader", email, hashed]
      });

      const token = jwt.sign({ id: userId, email }, JWT_SECRET, { expiresIn: "30d" });
      return res.status(200).json({ ok: true, user: { id: userId, email, name: name || "Trader" }, token });

    } else if (action === "login") {
      const result = await db.execute({ sql: "SELECT * FROM users WHERE email=?", args: [email] });
      if (result.rows.length === 0) {
        return res.status(401).json({ ok: false, error: "Credenziali non valide." });
      }

      const user = result.rows[0];
      if (!user.password) {
        return res.status(401).json({ ok: false, error: "Account senza password. Impossibile accedere." });
      }

      const match = await bcrypt.compare(password, user.password);
      if (!match) {
        return res.status(401).json({ ok: false, error: "Credenziali non valide." });
      }

      const token = jwt.sign({ id: user.id, email }, JWT_SECRET, { expiresIn: "30d" });
      return res.status(200).json({
        ok: true,
        user: { id: user.id, email: user.email, name: user.name },
        token
      });

    } else {
      return res.status(400).json({ ok: false, error: `Invalid action: ${action}` });
    }

  } catch (e) {
    console.error("[auth.js] Error:", e.stack);
    return res.status(500).json({ ok: false, error: "Server error during authentication." });
  }
}
