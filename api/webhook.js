// TradingView Webhook endpoint
// Receives indicator values from TradingView alerts and stores them on GitHub + Turso

const OWNER = process.env.GITHUB_OWNER || "alepunzi2895-alt";
const REPO  = process.env.GITHUB_REPO  || "tradeflow-ai";
const FILE  = "data/indicators_live.json";
const TOKEN = process.env.GITHUB_TOKEN;

// ── Turso: persist signal (fire-and-forget) ───────────────────────────────
async function saveSignalToDb(data) {
  const url = process.env.TURSO_DB_URL;
  const token = process.env.TURSO_AUTH_TOKEN;
  if (!url || !token) return;
  try {
    await fetch(`${process.env.VERCEL_URL ? 'https://'+process.env.VERCEL_URL : ''}/api/db`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save_signal",
        symbol: data.symbol,
        timeframe: data.tf,
        type: data.macd > data.signal ? "BULLISH" : data.macd < data.signal ? "BEARISH" : "NEUTRAL",
        strength: null,
        source: "tradingview_webhook",
        cci: data.cci,
        macd: data.macd,
        macd_signal: data.signal,
        adx: data.adx,
        di_plus: data.di_plus,
        di_minus: data.di_minus,
        price: data.price,
      }),
    });
  } catch (e) { console.log("Turso signal save skipped:", e.message); }
}

async function getFileSha() {
  try {
    const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`, {
      headers: { "Authorization": `Bearer ${TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TradeFlowAI" }
    });
    if (r.status === 404) return null;
    const d = await r.json();
    return d.sha || null;
  } catch { return null; }
}

async function saveToGitHub(data, sha) {
  const body = {
    message: `Live indicators update ${new Date().toISOString().slice(0,19)}`,
    content: Buffer.from(JSON.stringify(data, null, 2)).toString("base64"),
    ...(sha ? { sha } : {})
  };
  const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`, {
    method: "PUT",
    headers: { "Authorization": `Bearer ${TOKEN}`, "Accept": "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "TradeFlowAI" },
    body: JSON.stringify(body)
  });
  return r.ok;
}

// Simple in-memory cache (survives within same Vercel instance)
let memCache = null;

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  // GET — return latest cached indicator values
  if (req.method === "GET") {
    if (memCache) {
      return res.status(200).json({ ok: true, source: "cache", ...memCache });
    }
    // Try GitHub
    try {
      const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`, {
        headers: { "Authorization": `Bearer ${TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TradeFlowAI" }
      });
      if (r.ok) {
        const d = await r.json();
        const content = JSON.parse(Buffer.from(d.content, "base64").toString("utf-8"));
        memCache = content;
        return res.status(200).json({ ok: true, source: "github", ...content });
      }
    } catch {}
    return res.status(200).json({ ok: false, error: "Nessun dato disponibile. Configura l'alert su TradingView." });
  }

  // POST — receive webhook from TradingView
  if (req.method === "POST") {
    try {
      let body = req.body;
      // TradingView sends plain text sometimes
      if (typeof body === "string") {
        try { body = JSON.parse(body); } catch {
          return res.status(400).json({ ok: false, error: "JSON non valido" });
        }
      }

      // Expected fields from TradingView alert:
      // cci, macd, signal (macd signal), adx, di_plus, di_minus, price, tf, symbol
      const now = new Date().toISOString();
      const data = {
        timestamp: now,
        symbol:   body.symbol   || "XAUUSD",
        tf:       body.tf       || body.timeframe || "1h",
        price:    parseFloat(body.price   || body.close || 0),
        cci:      parseFloat(body.cci     || 0),
        macd:     parseFloat(body.macd    || 0),
        signal:   parseFloat(body.signal  || body.macd_signal || 0),
        adx:      parseFloat(body.adx     || 0),
        di_plus:  parseFloat(body.di_plus || body.dip || 0),
        di_minus: parseFloat(body.di_minus|| body.dim || 0),
        histogram:parseFloat(body.histogram || 0),
        source:   "tradingview_webhook"
      };

      // Save to memory cache immediately
      memCache = data;

      // Save to GitHub async (don't wait)
      if (TOKEN) {
        getFileSha().then(sha => saveToGitHub(data, sha)).catch(e => console.log("GitHub save failed:", e.message));
      }

      // Save signal to Turso async (don't wait)
      saveSignalToDb(data).catch(() => {});

      console.log(`Webhook received: TF=${data.tf} Price=${data.price} CCI=${data.cci} MACD=${data.macd}/${data.signal} ADX=${data.adx}`);
      return res.status(200).json({ ok: true, received: data });

    } catch (err) {
      return res.status(500).json({ ok: false, error: err.message });
    }
  }

  return res.status(405).json({ error: "Method not allowed" });
}
