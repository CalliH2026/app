import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const ctx={window:{}};
vm.runInNewContext(readFileSync(new URL('../vendor/mvp/static/report-tools.js',import.meta.url),'utf8'),ctx);
const render=ctx.window.renderReportTool;
test('truncated JSON is never presented as the readable result',()=>{
 const html=render({name:'search_resources',status:'succeeded',arguments:{topic:'Pythagore'},result_summary:'{"provider":"Linkup","sources":[…'},0);
 assert.match(html,/Ressources pédagogiques récupérées/);
 assert.match(html,/Sujet/);
 assert.ok(!html.split('<details')[0].includes('"provider"'));
 assert.match(html,/<details(?![^>]* open)[^>]*>/);
 assert.ok(!html.includes('<pre'));assert.ok(!html.includes('&quot;provider&quot;'));assert.match(html,/Détails de cette étape/);
});
test('validated figures are formatted and nested dossier JSON stays folded',()=>{
 const html=render({name:'validate_dossier',status:'succeeded',arguments:{dossier:'{"summary":"Bonjour"}'},result_summary:'{"valid":true,"evidence_count":12,"scenes":4}'},1);
 assert.match(html,/12 éléments de preuve/);assert.match(html,/4 séquences/);
 assert.ok(!html.includes('<pre'));assert.match(html,/<table/);assert.match(html,/Bonjour/);assert.match(html,/Synthèse/);
});
test('errors, unknown tools and hostile strings remain escaped and truthful',()=>{
 const html=render({name:'new_tool',status:'failed',arguments:{topic:'<img src=x onerror=alert(1)>'},result_summary:'<script>alert(1)</script>'},2);
 assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img'));
 assert.match(html,/&lt;script&gt;/);assert.ok(!html.includes('terminé'));
 assert.match(render({name:'unknown',status:'running'},3),/travaille/);
});

test('arrays and nested JSON strings become labelled tables, never raw payloads',()=>{
 const html=render({name:'example',status:'succeeded',arguments:{dossier:'{"summary":"Un résultat","evidence":[{"claim":"Correct","quote":"5 cm"}]}'},result_summary:{valid:true,scenes:4}},4);
 assert.match(html,/Un résultat/);assert.match(html,/Correct/);assert.match(html,/5 cm/);assert.match(html,/Oui/);assert.ok(!html.includes('&quot;summary&quot;'));assert.ok(!html.includes('<pre'));
});
