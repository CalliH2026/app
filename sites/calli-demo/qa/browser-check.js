// Browser check of the built preview served by build/serve.mjs on :8787.
const {chromium} = require('playwright-core');
const fs = require('fs');
const BASE = 'http://127.0.0.1:8787';
const OUT = __dirname + '/shots';
fs.mkdirSync(OUT, {recursive: true});
const results = [];
const ok = (name, pass, info = '') => { results.push({name, pass: !!pass, info: String(info).slice(0, 300)}); console.log(pass ? 'PASS' : 'FAIL', name, String(info).slice(0, 160)); };
(async () => {
  const b = await chromium.launch({executablePath: process.env.HOME + '/.local/bin/google-chrome', headless: true});
  const ctx = await b.newContext({viewport: {width: 1440, height: 900}, locale: 'fr-FR'});
  const nonGet = [], external = [], bad = [], errors = [];
  ctx.on('request', (r) => { if (!['GET', 'HEAD'].includes(r.method())) nonGet.push(r.method() + ' ' + r.url()); if (!r.url().startsWith(BASE) && !r.url().startsWith('data:') && !r.url().startsWith('blob:')) external.push(r.url()); });
  ctx.on('response', (r) => { if (r.status() >= 400) bad.push(r.status() + ' ' + r.url()); });
  await ctx.route(/^https?:\/\/(?!127\.0\.0\.1:8787)/, (route) => route.abort());
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push('pageerror ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console ' + m.text()); });
  const text = () => page.innerText('body');
  const shot = (n) => page.screenshot({path: `${OUT}/${n}.png`});

  await page.goto(BASE + '/'); await page.waitForTimeout(600); await shot('01-landing');
  const cta = page.getByRole('link', {name: /Try the workspace/}).first();
  ok('landing shows Try the workspace', await cta.isVisible());
  ok('landing video links to YouTube', await page.locator('a.video-link[href="https://www.youtube.com/watch?v=mILSh_vLQck"]').count() === 1);
  await cta.click(); await page.waitForURL(/\/app$/); await page.waitForTimeout(1800);
  ok('Today greets Mme Laurent', /Bonjour, Madame Laurent/.test(await text()));
  ok('preview status chip present', await page.locator('.calli-preview-status summary').isVisible());
  await shot('02-today');
  await page.click('.calli-preview-status summary'); await page.waitForTimeout(200); await shot('03-status-open'); await page.click('.calli-preview-status summary');

  for (const p of ['classes', 'evaluations', 'documents', 'messages', 'agenda', 'agent', 'reports', 'management']) {
    await page.evaluate((p) => document.querySelector(`[data-page="${p}"]`).click(), p); await page.waitForTimeout(900);
    ok(`page ${p} renders`, (await page.locator('#main').innerText()).length > 40);
  }
  await page.evaluate(() => document.querySelector('[data-page="evaluations"]').click()); await page.waitForTimeout(600);
  await page.evaluate(() => document.querySelector('#main [data-doc="copie"], #main [data-doc]').click()); await page.waitForTimeout(1200);
  ok('copy document opens with source details', /La copie d’Alex/.test(await text()) && await page.locator('.doc-provenance').count() > 0); await shot('04-copy');
  ok('opening the copy attaches the saved H run (no new run)', /rendez-vous est préparé/i.test(await page.locator('#agent-panel').innerText().catch(() => '')) && await page.locator('#calli-preview-toast:not([hidden])').count() === 1, await page.locator('#calli-preview-toast').innerText().catch(() => ''));
  await page.evaluate(() => document.querySelector('#main [data-doc="bareme"]')?.click()); await page.waitForTimeout(800);
  ok('marking scheme opens', /Barème/i.test(await page.locator('#main').innerText())); await shot('05-bareme');

  await page.goto(BASE + '/app?job=6b073dfc404f'); await page.waitForTimeout(2500);
  const report = await text();
  ok('saved H report renders', /Le rapport, en bref/.test(report)); await shot('07-report');
  ok('practice card shows the saved Devin exercise', await page.locator('.practice-card').count() > 0, (await page.locator('.practice-card').first().innerText().catch(() => '')).replace(/\s+/g, ' '));
  await page.locator('.practice-card').first().scrollIntoViewIfNeeded().catch(() => {}); await page.waitForTimeout(800); await shot('08-practice-card');

  const ex = await ctx.newPage();
  ex.on('pageerror', (e) => errors.push('exercise ' + e.message));
  await ex.goto(BASE + '/api/jobs/6b073dfc404f/practice/preview'); await ex.waitForSelector('button.choice', {timeout: 8000});
  await ex.click('button.choice[data-ok="0"]'); await ex.waitForTimeout(500);
  const wrong = await ex.innerText('body'); ok('exercise: wrong answer counted', /Erreurs : 1/.test(wrong), (wrong.match(/Score[^\n]*/) || [''])[0]);
  await ex.screenshot({path: `${OUT}/09-exercise-wrong.png`});
  await ex.click('#restart'); await ex.waitForTimeout(300);
  await ex.click('button.choice[data-ok="1"]'); await ex.waitForTimeout(500);
  const right = await ex.innerText('body'); ok('exercise: correct answer scored', /Score : [1-9]/.test(right), (right.match(/Score[^\n]*/) || [''])[0]);
  await ex.screenshot({path: `${OUT}/10-exercise-right.png`});
  await ex.click('#restart'); await ex.waitForTimeout(500);
  ok('exercise: reset', /Score : 0 \/ 7 · Erreurs : 0/.test(await ex.innerText('body')));
  await ex.close();

  await page.goto(BASE + '/app?view=outings&outing_id=23025b24ce29'); await page.waitForTimeout(3000);
  const outing = await page.locator('#main').innerText();
  ok('saved outing draft renders', /Orsay/.test(outing), outing.replace(/\s+/g, ' ').slice(0, 200)); await shot('11-outing');
  await page.mouse.wheel(0, 1400); await page.waitForTimeout(500); await shot('12-outing-trace');
  const trace = await page.evaluate(() => { const d = document.getElementById('outing-trace'); if (!d || d.hidden) return null; d.open = true; d.scrollIntoView(); return d.innerText.replace(/\s+/g, ' ').slice(0, 200); });
  await page.waitForTimeout(600); await shot('13-outing-trace-open'); ok('outing tool trace reachable', !!trace, trace);
  const launch = await page.evaluate(() => { const b = [...document.querySelectorAll('#main button')].find((x) => /lancer|relancer|actualiser|préparer|nouvelle/i.test(x.innerText)); if (b) { b.click(); return b.innerText; } return null; });
  await page.waitForTimeout(500);
  ok('outing action blocked with short note', !launch || await page.locator('#calli-preview-toast:not([hidden])').count() === 1, launch);
  await shot('14-outing-blocked');

  await page.goto(BASE + '/app?view=family'); await page.waitForTimeout(2500);
  const fam = await page.locator('#main').innerText();
  ok('family: Mme Martin with Alex Martin and Lucas Martin', /Mme Martin/.test(fam) && /Alex Martin/.test(fam) && /Lucas Martin/.test(fam) && !/Lucas Bernard/.test(fam));
  ok('family: no prominent fictive banner', !/Famille fictive de démonstration/.test(fam.split('Détails techniques')[0]));
  await shot('15-family');
  await page.locator('[data-family-source]').first().click(); await page.waitForTimeout(900);
  ok('family: source opens', /Copie|Message|Rendez-vous|Devoir|Réunion|Sortie/.test(await page.locator('#main').innerText())); await shot('16-family-source');

  await page.evaluate(() => document.querySelector('[data-page="appreciations"]').click()); await page.waitForTimeout(3500);
  const frame = page.frames().find((f) => f.url().includes('/calli/workspace'));
  const appr = frame ? await frame.locator('body').innerText() : '';
  ok('appreciations iframe renders roster', frame && /Lucas Bernard/.test(appr), appr.replace(/\s+/g, ' ').slice(0, 160));
  ok('appreciations: no "Arrêt demandé"', !/Arrêt demandé/.test(appr));
  const portraits = frame ? await frame.evaluate(() => [...document.images].filter((i) => i.complete && i.naturalWidth > 0).length) : 0;
  ok('appreciations portraits loaded', portraits > 0, portraits);
  await shot('17-appreciations');
  if (frame) {
    const mic = await frame.evaluate(() => { const b = [...document.querySelectorAll('button')].find((x) => /dict|micro|enregistr|parler/i.test(x.innerText + (x.getAttribute('aria-label') || ''))); if (b) { b.click(); return b.innerText || b.getAttribute('aria-label'); } return null; });
    await page.waitForTimeout(700); ok('dictation control does not reach the network', true, mic); await shot('18-appreciations-mic');
  }

  const m = await b.newContext({viewport: {width: 390, height: 844}, isMobile: true, locale: 'fr-FR'});
  await m.route(/^https?:\/\/(?!127\.0\.0\.1:8787)/, (route) => route.abort());
  const mp = await m.newPage();
  for (const [u, n] of [['/', 'm-landing'], ['/guide', 'm-guide'], ['/app?view=family', 'm-family'], ['/app', 'm-today']]) {
    await mp.goto(BASE + u); await mp.waitForTimeout(2200);
    const overflow = await mp.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    ok(`390px ${u} no horizontal overflow`, overflow <= 1, overflow); await mp.screenshot({path: `${OUT}/${n}.png`});
  }
  await page.goto(BASE + '/guide'); await page.waitForTimeout(500); await shot('19-guide');

  ok('no non-GET request left the browser', nonGet.length === 0, nonGet.join(' | '));
  ok('no external request attempted', external.length === 0, [...new Set(external)].join(' | '));
  ok('no failed responses', bad.length === 0, [...new Set(bad)].join(' | '));
  ok('no page errors', errors.length === 0, [...new Set(errors)].join(' | '));
  fs.writeFileSync(__dirname + '/browser-results.json', JSON.stringify({results, nonGet, external: [...new Set(external)], bad: [...new Set(bad)], errors: [...new Set(errors)]}, null, 1));
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
