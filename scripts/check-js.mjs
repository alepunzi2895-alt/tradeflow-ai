import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
for(const dir of ['api','lib','public/modules'])for(const file of fs.readdirSync(dir))if(file.endsWith('.js'))execFileSync(process.execPath,['--check',path.join(dir,file)],{stdio:'inherit'});
for(const file of ['public/app.js','standalone-server.js'])execFileSync(process.execPath,['--check',file],{stdio:'inherit'});
console.log('JavaScript syntax passed');
