// Administrative local command. Grants account visibility only, never trading controls.
import 'dotenv/config';
import {getDb} from '../api/db.js';
import {ensureSystemReaders} from '../lib/security.js';
const args=process.argv.slice(2);
if(args.length!==2 || args[0]!=='--user-id' || !args[1])throw Error('Usage: node scripts/grant-system-read.mjs --user-id <verified account ID>');
const userId=args[1], db=getDb();
try {
  const user=await db.execute({sql:'SELECT id FROM users WHERE id=?',args:[userId]});
  if(user.rows.length!==1)throw Error('Account non trovato');
  await ensureSystemReaders(db);
  await db.execute({sql:'INSERT INTO system_readers(user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING',args:[userId]});
  console.log('System read access enabled for user '+userId);
} finally {db.close();}
