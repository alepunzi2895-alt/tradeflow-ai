import { createClient } from "@libsql/client";

const url = "https://tradeflow-ai-therealmfkk.aws-eu-west-1.turso.io";
const token = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJnaWQiOiIzMzQzZDlkNy04ZmE3LTQ4NTktOGRhZS1mNjczN2E0YjQ4ZmQiLCJpYXQiOjE3NzUwMTIwMjQsInJpZCI6ImU3YmY2YmE1LTEwZjUtNDRmYy04MTdmLWFiOGU2OTg3NDg5YyJ9.pMLtpJVZfvg_BUhEBETgbzGOITzllXtCUgg39TE5vHgBkOwzHDOFKT9kowhdWdCd1rysxoZ_aH1W_lIMCCe9Ag";

const db = createClient({ url, authToken: token });

async function run() {
  try {
    await db.execute("ALTER TABLE users ADD COLUMN password TEXT");
    console.log("Col password added.");
  } catch(e) {
    console.log("Col password might exist: " + e.message);
  }
  
  try {
    await db.execute("CREATE TABLE IF NOT EXISTS user_data (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, doc_type TEXT NOT NULL, payload TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))");
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_data_type ON user_data(user_id, doc_type)");
    console.log("user_data table created.");
  } catch(e) {
    console.log("user_data table error: " + e.message);
  }
}
run();
