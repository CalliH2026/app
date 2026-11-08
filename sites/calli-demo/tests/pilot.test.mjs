import assert from 'node:assert/strict';
import test from 'node:test';
import {handle} from '../dist/worker.js';
const origin='https://calli-demo.example';
const valid={email:'teacher@example.org',school:'Test School',role:'teacher',consent:true,website:'',language:'en'};
const req=(body=valid,headers={})=>new Request(origin+'/pilot/interest',{method:'POST',headers:{origin,'content-type':'application/json',...headers},body:JSON.stringify(body)});
function db({count=0,fail=false}={}) {
  const calls=[];
  const DB={prepare(sql) {
    if (fail) throw Error('database');
    return {bind(...args) {
      return {
        async first() {return {count};},
        async run() {calls.push({sql,args});return {success:true,meta:{changes:1}};}
      };
    }};
  }};
  return {calls,DB};
}
test('pilot interest persists normalized bounded fields and explicit consent',async()=>{const d=db();const r=await handle(req({...valid,email:' Teacher@Example.org '}),d);assert.equal(r.status,201);assert.equal(d.calls.length,1);assert.ok(d.calls[0].args.includes('teacher@example.org'));assert.match(d.calls[0].sql,/ON CONFLICT/);assert.equal(r.headers.get('cache-control'),'no-store');assert.equal(r.headers.get('set-cookie'),null);});
test('pilot rejects bad input, foreign origin, honeypot, excess fields and oversized streamed input',async()=>{for(const [body,headers,status] of [[{...valid,consent:false},{},400],[{...valid,email:'bad'},{},400],[{...valid,school:''},{},400],[{...valid,role:'unknown'},{},400],[{...valid,website:'bot'},{},400],[{...valid,student:'do not collect'},{},400],[valid,{origin:'https://elsewhere.example'},403],[{...valid,school:'x'.repeat(5000)},{},413]]){const d=db();assert.equal((await handle(req(body,headers),d)).status,status);assert.equal(d.calls.length,0);}});
test('pilot reports unavailable storage and rate cap instead of pretending to save',async()=>{assert.equal((await handle(req(),{})).status,503);assert.equal((await handle(req(),db({fail:true}))).status,503);assert.equal((await handle(req(),db({count:250}))).status,429);});
test('pilot has no public reader; does not open product writes',async()=>{const r=await handle(new Request(origin+'/pilot/interest'),{});assert.equal(r.status,405);assert.equal(r.headers.get('allow'),'POST');assert.equal((await handle(new Request(origin+'/api/outings',{method:'POST',body:'{}'}),{})).status,405);});

test('real SQLite migration stores once, parameterizes text, and keeps contacts private',async()=>{
  const {DatabaseSync}=await import('node:sqlite');
  const {readFileSync}=await import('node:fs');
  const sqlite=new DatabaseSync(':memory:');
  sqlite.exec(readFileSync(new URL('../drizzle/0001_pilot_interest.sql',import.meta.url),'utf8'));
  const DB={prepare(sql){return {bind(...args){const stmt=sqlite.prepare(sql);return {async first(){return stmt.get(...args);},async run(){const result=stmt.run(...args);return {success:true,meta:{changes:result.changes}};}};}};}};
  const body={...valid,school:"School's name; DROP TABLE pilot_interest;"};
  for(let i=0;i<2;i++) assert.equal((await handle(req(body),{DB})).status,201);
  const rows=sqlite.prepare('SELECT * FROM pilot_interest').all();
  assert.equal(rows.length,1);assert.equal(rows[0].email,valid.email);assert.equal(rows[0].school,body.school);assert.equal(rows[0].consent_version,'pilot-v1');
  assert.equal((await handle(new Request(origin+'/pilot/interest'),{DB})).status,405);
  sqlite.close();
});

test('returning visitors receive a versioned landing stylesheet',async()=>{
  const server=(await import('../dist/server/index.js')).default;
  for(const path of ['/','/fr']) {
    const html=await (await server.fetch(new Request(origin+path))).text();
    assert.match(html,/href="\/styles\.css\?v=[a-f0-9]{12}"/);
  }
});
