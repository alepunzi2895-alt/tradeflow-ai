import { createClient } from "@libsql/client";
import bcrypt from "bcryptjs";

const url = "https://tradeflow-ai-therealmfkk.aws-eu-west-1.turso.io";
const token = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJnaWQiOiIzMzQzZDlkNy04ZmE3LTQ4NTktOGRhZS1mNjczN2E0YjQ4ZmQiLCJpYXQiOjE3NzUwMTIwMjQsInJpZCI6ImU3YmY2YmE1LTEwZjUtNDRmYy04MTdmLWFiOGU2OTg3NDg5YyJ9.pMLtpJVZfvg_BUhEBETgbzGOITzllXtCUgg39TE5vHgBkOwzHDOFKT9kowhdWdCd1rysxoZ_aH1W_lIMCCe9Ag";

const db = createClient({ url, authToken: token });

async function run() {
  try {
    const email = "ale.punzi@email.it";
    const newPass = "Gianni95.";
    
    console.log(`Hashing password for ${email}...`);
    const hashed = await bcrypt.hash(newPass, 10);
    
    console.log(`Updating database...`);
    const res = await db.execute({
      sql: "UPDATE users SET password=? WHERE email=?",
      args: [hashed, email]
    });
    
    if (res.rowsAffected > 0) {
      console.log(`Successfully updated password for ${email}`);
    } else {
      console.log(`User ${email} not found!`);
    }
  } catch(e) {
    console.log("Error: " + e.message);
  }
}
run();
