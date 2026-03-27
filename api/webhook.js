// TradingView Webhook endpoint
// Receives indicator values from TradingView alerts and stores them on GitHub

const OWNER = process.env.GITHUB_OWNER || "alepunzi2895-alt";
const REPO  = process.env.GITHUB_REPO  || "tradeflow-ai";
const FILE  = "data/indicators_live.json";
const TOKEN = process.env.GITHUB_TOKEN;

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