// Saves and loads knowledge base as a JSON file directly in GitHub repo
// Requires: GITHUB_TOKEN and GITHUB_REPO env vars in Vercel

const OWNER = process.env.GITHUB_OWNER || "alepunzi2895-alt";
const REPO  = process.env.GITHUB_REPO  || "tradeflow-ai";
const FILE  = "data/knowledge.json";
const TOKEN = process.env.GITHUB_TOKEN;

async function getFile() {
  const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`, {
    headers: {
      "Authorization": `Bearer ${TOKEN}`,
      "Accept": "application/vnd.github+json",
      "User-Agent": "TradeFlowAI",
    }
  });
  if (r.status === 404) return { content: null, sha: null };
  if (!r.ok) throw new Error(`GitHub GET failed: ${r.status}`);
  const d = await r.json();
  const content = JSON.parse(Buffer.from(d.content, "base64").toString("utf-8"));
  return { content, sha: d.sha };
}

async function saveFile(content, sha) {
  const body = {
    message: `Update knowledge base ${new Date().toISOString().slice(0,10)}`,
    content: Buffer.from(JSON.stringify(content, null, 2)).toString("base64"),
    ...(sha ? { sha } : {}),
  };
  const r = await fetch(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`, {
    method: "PUT",
    headers: {
      "Authorization": `Bearer ${TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "TradeFlowAI",
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.text();
    throw new Error(`GitHub PUT failed: ${r.status} — ${err.slice(0, 200)}`);
  }
  return await r.json();
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  if (!TOKEN) {
    return res.status(500).json({ error: "GITHUB_TOKEN non configurato nelle env vars di Vercel" });
  }

  try {
    // GET — load knowledge base
    if (req.method === "GET") {
      const { content, sha } = await getFile();
      return res.status(200).json({
        ok: true,
        kb: content?.kb || [],
        knowledge: content?.knowledge || [],
        sha,
        updatedAt: content?.updatedAt || null,
      });
    }

    // POST — save knowledge base
    if (req.method === "POST") {
      const { kb, knowledge, sha } = req.body || {};
      const { sha: currentSha } = await getFile();
      const content = {
        kb: kb || [],
        knowledge: knowledge || [],
        updatedAt: new Date().toISOString(),
        app: "TradeFlowAI",
      };
      await saveFile(content, currentSha || sha);
      return res.status(200).json({ ok: true, message: "Knowledge base salvata su GitHub" });
    }

    return res.status(405).json({ error: "Method not allowed" });
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
