export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  const { action, session, email, password, accountId } = req.body || {};

  try {
    let url = "";
    if (action === "login") {
      url = `https://www.myfxbook.com/api/login.json?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`;
    } else if (action === "accounts") {
      url = `https://www.myfxbook.com/api/get-my-accounts.json?session=${session}`;
    } else if (action === "history") {
      url = `https://www.myfxbook.com/api/get-history.json?session=${session}&id=${accountId}`;
    } else if (action === "stats") {
      url = `https://www.myfxbook.com/api/get-data-daily.json?session=${session}&id=${accountId}&start=2024-01-01&end=2099-01-01`;
    } else {
      return res.status(400).json({ error: "Action non valida" });
    }

    const response = await fetch(url);
    const data = await response.json();
    return res.status(200).json(data);
  } catch (err) {
    return res.status(500).json({ error: err.message });
  }
}
