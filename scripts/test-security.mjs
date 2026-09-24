import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import jwt from 'jsonwebtoken';
import {createClient} from '@libsql/client';
import {createHandler} from '../api/db.js';
import {requireUser,requireOperator,rateLimit} from '../lib/security.js';
import * as jobs from '../lib/backtest-jobs.js';
import * as labs from '../lib/lab-strategies.js';

process.env.JWT_SECRET='unit-test-secret-only-never-for-deployment';
process.env.MT5_BOT_SECRET='unit-test-service';
process.env.ADMIN_USER_IDS='alice';
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'tradeflow-tests-'));
const db=createClient({url:pathToFileURL(path.join(temp,'test.db')).href});
const schema=fs.readFileSync('scripts/setup-turso.mjs','utf8');
for(const match of schema.matchAll(/`([^`]+)`/g)) if(match[1].trim().startsWith('CREATE TABLE')) await db.execute(match[1]);
await db.execute('ALTER TABLE users ADD COLUMN password TEXT');
await db.execute('CREATE TABLE user_data(id TEXT PRIMARY KEY,user_id TEXT,doc_type TEXT,payload TEXT,updated_at TEXT,UNIQUE(user_id,doc_type))');
for(const id of ['alice','bob'])await db.execute({sql:'INSERT INTO users(id,email) VALUES (?,?)',args:[id,id+'@example.test']});
const token=id=>jwt.sign({id,email:id+'@example.test'},process.env.JWT_SECRET);
const handler=createHandler(()=>db);
async function call(action,body={},id,method='POST',url='/api/db'){
  let status=200,data,headers={};
  const req={method,url,body:{action,...body},headers:{host:'localhost',...(id?{authorization:'Bearer '+token(id)}:{})}};
  const res={setHeader(k,v){headers[k]=v;},status(s){status=s;return this;},json(v){data=v;return this;},end(){}};
  await handler(req,res);return {status,data,headers};
}
// The release smoke check must detect an unavailable login before reporting success.
const configuredJwt=process.env.JWT_SECRET;
for(const secret of [undefined,'too-short']){
  if(secret===undefined)delete process.env.JWT_SECRET;else process.env.JWT_SECRET=secret;
  assert.equal((await call(undefined,{},undefined,'GET')).status,503,'gateway reports invalid auth configuration');
  assert.equal((await call('login',{email:'probe@example.test',password:'not-a-real-password'})).status,503);
}
process.env.JWT_SECRET=configuredJwt;
assert.equal((await call(undefined,{},undefined,'GET')).status,200);
for(const action of ['get_trades','save_trade','get_user_data','save_user_data','auto_trade_set','score_push','mt5_get','backtest_cmd_push','history_cmd_push','worker_status_get','profile_cmd_push','profiles_get','spec_cmd_push','spec_runs_get','lab_promote','lab_strategy_set','lab_strategies_get','patch_db'])assert.equal((await call(action)).status,401,action);
assert.equal((await call('admin_reset',{email:'alice@example.test',password:'attacker'})).status,410);
assert.equal((await call('mt5_command_push',{command:{direction:'buy'}},'alice')).status,410);
assert.equal((await call('auto_trade_set',{enabled:true},'bob')).status,403);
assert.equal((await call('mt5_get',{},'bob')).status,403);
await db.execute({sql:'INSERT INTO system_readers(user_id) VALUES (?)',args:['bob']});
assert.equal((await call('mt5_get',{},'bob')).status,200,'explicit readers can see system data');
assert.equal((await call('auto_trade_set',{enabled:true},'bob')).status,403,'system read access never grants trading control');
assert.equal((await call('save_user_data',{doc_type:'system_readers',payload:'{}'},'bob')).status,400,'read access cannot be self-granted via blob storage');
assert.equal((await call('auto_trade_get',{},'alice')).data.enabled,false);
assert.equal((await call('save_user_data',{user_id:'bot-config',doc_type:'auto_trade',payload:'{}'},'alice')).status,403);
assert.equal((await call('save_user_data',{doc_type:'auto_trade',payload:'{}'},'alice')).status,400);
assert.equal((await call('score_push',{score:Infinity},'alice')).status,400);
assert.equal((await call('save_trade',{id:'trade-a',direction:'BUY',pnl:5},'alice')).status,200);
assert.equal((await call('save_trade',{id:'trade-a',direction:'SELL',pnl:999},'bob')).status,403);
await call('delete_trade',{id:'trade-a'},'bob');
assert.equal((await call('get_trades',{},'alice')).data.trades.length,1);
await call('delete_trade',{id:'trade-a'},'alice');
assert.equal((await call('get_trades',{},'alice')).data.trades.length,0);
const imported={account_id:'account1',trades:[{id:'mfx:alice:account1:1',symbol:'XAUUSD',direction:'BUY',pnl:8}]};
assert.equal((await call('replace_imported_trades',imported,'alice')).status,200);
assert.equal((await call('replace_imported_trades',imported,'alice')).status,200);
assert.equal((await call('get_trades',{},'alice')).data.trades.length,1);
assert.equal((await call('replace_imported_trades',{...imported,trades:[{id:'bad',direction:'BUY'}]},'alice')).status,400);
assert.equal((await call('get_trades',{},'alice')).data.trades.length,1,'failed import rolls back');
await call('kb_save',{kb:[{name:'test',summary:'safe'}]},'alice');
assert.equal((await call(undefined,{},'alice','GET','/api/kb')).data.kb.length,1);
assert.equal((await call(undefined,{},'bob','GET','/api/kb')).data.kb.length,0);
const session=await call('session',{},'alice');
assert.match(session.headers['Set-Cookie'],/HttpOnly; SameSite=Strict/);
assert.equal(requireUser({headers:{cookie:session.headers['Set-Cookie'],host:'localhost'}}).id,'alice');
assert.throws(()=>requireUser({headers:{authorization:'Bearer '+token('alice'),host:'localhost',origin:'https://evil.example'}}),/Origine/);
assert.throws(()=>requireOperator({id:'bob',email:'alice@example.test'}),/riservata/);
await rateLimit(db,'test',1,3600);await assert.rejects(rateLimit(db,'test',1,3600),/Troppe/);
const queued=await jobs.enqueue(db,{user_id:'alice',strategy_id:'S17_CONVERGENCE_SCALP'});
const claims=await Promise.all([jobs.claim(db),jobs.claim(db)]);
assert.equal(claims.filter(c=>c.command).length,1,'atomic lease');
const cmd=claims.find(c=>c.command).command;
assert.equal(cmd.request_id,queued.request_id);
await assert.rejects(jobs.complete(db,{...cmd,lease_token:'stale',result:{}}),/lease/);
await jobs.complete(db,{...cmd,result:{full:{pf:1.2}}});
assert.equal((await jobs.result(db,{request_id:cmd.request_id,user_id:'alice'})).data.full.pf,1.2);
assert.equal((await jobs.result(db,{request_id:cmd.request_id,user_id:'bob'})).data,null);
await assert.rejects(jobs.complete(db,{...cmd,result:{}}),/completata/);
// Storici MT5 on-demand: validazione, stessa coda, kind/params al worker, heartbeat.
await assert.rejects(jobs.enqueueHistory(db,{user_id:'alice',instrument:'FOOBAR',tf:'H1',days:365}),/registro/);
await assert.rejects(jobs.enqueueHistory(db,{user_id:'alice',instrument:'EURUSD',tf:'H2',days:365}),/Timeframe/);
await assert.rejects(jobs.enqueueHistory(db,{user_id:'alice',instrument:'EURUSD',tf:'H1',days:99999}),/Periodo/);
const hq=await jobs.enqueueHistory(db,{user_id:'alice',instrument:'eurusd',tf:'m15',days:730});
const hc=(await jobs.claim(db)).command;
assert.equal(hc.request_id,hq.request_id);assert.equal(hc.kind,'history');
assert.deepEqual(hc.params,{instrument:'EURUSD',tf:'M15',days:730});
await jobs.complete(db,{...hc,result:{instrument:'EURUSD',tf:'M15',bars:49535}});
assert.equal((await jobs.result(db,{request_id:hq.request_id,user_id:'alice'})).data.bars,49535);
await jobs.workerStatusPush(db,{host:'vps',history:{datasets:{EURUSD_M15:{bars:49535}}}});
assert.equal((await jobs.workerStatusGet(db)).data.history.datasets.EURUSD_M15.bars,49535);
// Schede strumento: una sola richiesta in coda alla volta, pubblicazione validata, lettura.
const p1=await jobs.enqueueProfile(db,{user_id:'alice'}),p2=await jobs.enqueueProfile(db,{user_id:'alice'});
assert.equal(p2.request_id,p1.request_id);assert.equal(p2.already,true);
const pc=(await jobs.claim(db)).command;assert.equal(pc.kind,'profile');
await assert.rejects(jobs.profilesPush(db,{profiles:{}}),/mancanti/);
await jobs.profilesPush(db,{profiles:{generated_at:'2026-09-24T18:00:00Z',instruments:{XAU:{id:'XAU'}}}});
assert.equal((await jobs.profilesGet(db)).data.instruments.XAU.id,'XAU');
// Composer: specifica ripulita (niente campi extra, limiti), in coda come kind='spec'.
const goodSpec={name:'Pullback',instrument:'xau',tf:'h1',direction:'long',evil:'<script>',
  rules:[{left:'ema',period:20,op:'crossUp',right:'ema',value:0,rightPeriod:50,hack:1}],
  exit:{stop:{type:'atr',mult:1.5,period:14},take_r:2,partial:{at_r:1,fraction:.5},time_stop_bars:48}};
for(const [bad,re] of [[{...goodSpec,tf:'H2'},/Timeframe/],[{...goodSpec,rules:[]},/regole/],[{...goodSpec,rules:[{...goodSpec.rules[0],left:'eval'}]},/Regola/],
  [{...goodSpec,exit:{...goodSpec.exit,take_r:500}},/Target/],[{...goodSpec,session:{from:14,to:10}},/Sessione/],[{...goodSpec,instrument:'FOO'},/registro/]])
  await assert.rejects(jobs.enqueueSpec(db,{user_id:'alice',spec:bad}),re);
const sq=await jobs.enqueueSpec(db,{user_id:'alice',spec:goodSpec});
assert.equal(sq.spec.evil,undefined);assert.equal(sq.spec.rules[0].hack,undefined);assert.equal(sq.spec.instrument,'XAU');assert.equal(sq.spec.tf,'H1');
const sc=(await jobs.claim(db)).command;assert.equal(sc.kind,'spec');assert.equal(sc.params.exit.partial.fraction,.5);
await jobs.complete(db,{...sc,result:{verdict:'BOCCIATA',full:{n:107,pf:.838},holdout:{pf:.63},net_r:-10}});
const runs=(await jobs.specRuns(db,{user_id:'alice'})).runs;assert.equal(runs[0].summary.verdict,'BOCCIATA');
assert.equal((await jobs.specRuns(db,{user_id:'bob'})).runs.length,0,'storico per utente');
// Promozione sul bot: solo validazioni proprie, completate e con esito adeguato; limiti di lotto e di numero.
await assert.rejects(labs.promote(db,{user_id:'alice',request_id:sq.request_id,lot:.02}),/BOCCIATA/);
await assert.rejects(labs.promote(db,{user_id:'bob',request_id:sq.request_id,lot:.02}),/non trovata/);
async function passedSpec(user,partial=false){const q=await jobs.enqueueSpec(db,{user_id:user,spec:{...goodSpec,exit:{...goodSpec.exit,partial:partial?{at_r:1,fraction:.5}:null}}});
  const c=(await jobs.claim(db)).command;await jobs.complete(db,{...c,result:{verdict:'CANDIDATA DEMO',full:{n:150,pf:1.4,wr:52},holdout:{pf:1.3},costs2:{pf:1.2},avg_r:.2}});return q.request_id;}
const pending=await jobs.enqueueSpec(db,{user_id:'alice',spec:goodSpec});
await assert.rejects(labs.promote(db,{user_id:'alice',request_id:pending.request_id,lot:.02}),/non completata/);
await jobs.claim(db);
const withPartial=await passedSpec('alice',true);
await assert.rejects(labs.promote(db,{user_id:'alice',request_id:withPartial,lot:.01}),/almeno 0,02/);
await assert.rejects(labs.promote(db,{user_id:'alice',request_id:withPartial,lot:.5}),/Lotto/);
const pr=await labs.promote(db,{user_id:'alice',request_id:withPartial,lot:.02,spec:{evil:1},expected:{pf:99}});
assert.equal(pr.item.expected.pf,1.4,'numeri attesi dal DB, non dalla richiesta');assert.equal(pr.item.spec.instrument,'XAU');assert.match(pr.item.id,/^LAB_[0-9A-F]{6}$/);
await assert.rejects(labs.promote(db,{user_id:'alice',request_id:withPartial,lot:.02}),/già sul bot/);
await labs.promote(db,{user_id:'alice',request_id:await passedSpec('alice'),lot:.01});
await labs.promote(db,{user_id:'alice',request_id:await passedSpec('alice'),lot:.01});
await assert.rejects(labs.promote(db,{user_id:'alice',request_id:await passedSpec('alice'),lot:.01}),/Al massimo 3/);
assert.equal((await labs.autopause(db,{id:pr.item.id,reason:'PF live 0,6 dopo 20 trade'})).changed,true);
const listed=(await labs.list(db)).items.find(x=>x.id===pr.item.id);assert.equal(listed.status,'paused');assert.equal(listed.paused_by,'bot');
await labs.setStatus(db,{id:pr.item.id,status:'retired'});
await assert.rejects(labs.setStatus(db,{id:pr.item.id,status:'active'}),/ritirata/);
assert.equal((await call('strategy_registry',{},'alice')).data.data.strategies.S20_FIB_CONFLUENCE.status,'disabled');
db.close();try{for(const name of ['test.db','test.db-shm','test.db-wal'])fs.rmSync(path.join(temp,name),{force:true});fs.rmdirSync(temp);}catch(e){if(!['EPERM','EBUSY'].includes(e.code))throw e;}console.log('Security, ownership, import rollback, KB isolation, quotas and atomic jobs: passed');
