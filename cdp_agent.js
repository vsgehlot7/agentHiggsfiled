#!/usr/bin/env node
/* =============================================================================
 *  PixelPitch (CDP) — true-background Higgsfield image generation agent
 * =============================================================================
 *  Drives a BACKGROUND Chrome tab via the DevTools Protocol. Because CDP input
 *  events are "trusted", the Lexical prompt editor accepts them — so we can
 *  clear + type + generate without stealing your keyboard/mouse. You can keep
 *  working while this runs.
 *
 *  Requires Chrome started with:  --remote-debugging-port=9222
 *  (the start_chrome_debug.sh helper does this for you).
 *
 *  Usage:
 *    node cdp_agent.js <prompts.md>
 *  Env (optional): MODEL, QUALITY (1K|2K|4K), ASPECT (e.g. 9:16),
 *                  UNLIMITED (on|off), WAIT (seconds), PORT (default 9222),
 *                  AGENT_NAME
 * ========================================================================== */

const fs = require('fs');
const http = require('http');

const PORT       = process.env.PORT || '9222';
const AGENT_NAME = process.env.AGENT_NAME || 'PixelPitch';
const MODEL      = process.env.MODEL || 'Nano Banana Pro';
const QUALITY    = process.env.QUALITY || '1K';
const ASPECT     = process.env.ASPECT || '9:16';
const UNLIMITED  = (process.env.UNLIMITED || 'on').toLowerCase();
const WAIT       = parseInt(process.env.WAIT || '50', 10);
const URL_MATCH  = 'higgsfield.ai/ai/image';
const PROMPTS_FILE = process.argv[2];

if (!PROMPTS_FILE) { console.error('Usage: node cdp_agent.js <prompts.md>'); process.exit(1); }
if (!fs.existsSync(PROMPTS_FILE)) { console.error('Prompts file not found: ' + PROMPTS_FILE); process.exit(1); }

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

function httpGet(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: PORT, path }, (res) => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(d));
    }).on('error', reject);
  });
}

// --- minimal CDP client over the tab's WebSocket -----------------------------
class CDP {
  constructor(wsUrl) { this.wsUrl = wsUrl; this.id = 0; this.pending = new Map(); }
  connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => resolve();
      this.ws.onerror = (e) => reject(e);
      this.ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
        }
      };
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'eval error');
    return r.result.value;
  }
  // Trusted keystroke (e.g. Cmd+A, Backspace)
  async key(type, { key, code, vk, modifiers = 0 }) {
    await this.send('Input.dispatchKeyEvent', {
      type, modifiers, key, code,
      windowsVirtualKeyCode: vk, nativeVirtualKeyCode: vk,
    });
  }
  // Trusted text insertion (replaces current selection)
  async insertText(text) { await this.send('Input.insertText', { text }); }
}

// --- page-side helper expressions -------------------------------------------
const Q = (s) => JSON.stringify(s); // safe-embed a string into evaluated JS

async function applySettings(cdp) {
  // MODEL — open the model picker only if not already set
  const already = await cdp.evaluate(
    `(function(){var b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim().indexOf(${Q(MODEL)})===0); return !!b;})()`
  );
  if (already) {
    console.log('  model already: ' + MODEL);
  } else {
    // The model button shares the composer toolbar row with the aspect (N:N) and quality (1K/2K/4K) buttons.
    await cdp.evaluate(`(function(){
      var qb=[...document.querySelectorAll('button')].find(x=>/^(1K|2K|4K)$/.test(x.innerText.trim()));
      if(!qb) return 'no-toolbar';
      var row=qb; for(var i=0;i<5;i++){ if(row.parentElement){row=row.parentElement; if(row.querySelectorAll('button').length>=3) break;} }
      var btns=[...row.querySelectorAll('button')];
      var mb=btns.find(x=>{var t=x.innerText.trim(); return t && !/^[0-9]+:[0-9]+$/.test(t) && !/^(1K|2K|4K)$/.test(t) && t.indexOf('Unlimited')!==0 && t.indexOf('Draw')!==0 && !/^[0-9]+\\/[0-9]+$/.test(t);});
      if(mb){mb.click(); return 'opened';} return 'no-model-btn';
    })()`);
    await sleep(1200);
    const res = await cdp.evaluate(`(function(){
      var dlg=document.querySelector('[role=dialog],[data-state=open]')||document;
      var target=null;
      dlg.querySelectorAll('*').forEach(function(el){var d=''; el.childNodes.forEach(function(n){if(n.nodeType===3)d+=n.textContent;}); if(d.trim()===${Q(MODEL)}) target=el;});
      if(!target) return 'NOT_FOUND';
      var e=target; for(var i=0;i<6&&e;i++){ if(e.tagName==='BUTTON'){e.click(); return 'SELECTED';} e=e.parentElement;}
      target.click(); return 'CLICKED';
    })()`);
    console.log('  model -> ' + MODEL + ' (' + res + ')');
    await cdp.evaluate(`(function(){var d=document.querySelector('[role=dialog]'); if(d){var c=d.querySelector('button[aria-label],button'); } document.body.click();})()`);
    await sleep(500);
  }

  // QUALITY
  await cdp.evaluate(`(function(){var b=[...document.querySelectorAll('button')].find(x=>/^(1K|2K|4K)$/.test(x.innerText.trim())); if(b)b.click();})()`);
  await sleep(700);
  const qr = await cdp.evaluate(`(function(){var o=[...document.querySelectorAll('button[role=option]')].find(b=>b.innerText.trim().indexOf(${Q(QUALITY)})===0); if(!o)return 'NOT_FOUND'; o.click(); return 'OK';})()`);
  console.log('  quality -> ' + QUALITY + ' (' + qr + ')');
  await sleep(400);

  // ASPECT
  await cdp.evaluate(`(function(){var b=[...document.querySelectorAll('button')].find(x=>/^[0-9]+:[0-9]+$/.test(x.innerText.trim())); if(b)b.click();})()`);
  await sleep(700);
  const ar = await cdp.evaluate(`(function(){var o=[...document.querySelectorAll('button[role=option]')].find(b=>b.innerText.trim().indexOf(${Q(ASPECT)})===0); if(!o)return 'NOT_FOUND'; o.click(); return 'OK';})()`);
  console.log('  aspect -> ' + ASPECT + ' (' + ar + ')');
  await sleep(400);

  // UNLIMITED switch
  const want = UNLIMITED === 'off' ? 'false' : 'true';
  const ur = await cdp.evaluate(`(function(){var s=document.querySelector('[role=switch]'); if(!s)return 'NO_SWITCH'; var on=(s.getAttribute('aria-checked')==='true'||s.getAttribute('data-state')==='checked'); if(String(on)!==${Q(want)}){s.click(); return 'TOGGLED';} return 'OK';})()`);
  console.log('  unlimited -> ' + UNLIMITED + ' (' + ur + ')');
  await sleep(300);
}

async function typePrompt(cdp, prompt) {
  // Focus the Lexical editor (trusted focus via JS is fine; typing must be trusted via CDP)
  await cdp.evaluate(`(function(){var e=document.querySelector('[contenteditable]'); e.focus(); return 'ok';})()`);
  await sleep(200);
  // Select all (Cmd+A) — trusted, so Lexical syncs its selection
  await cdp.key('rawKeyDown', { key: 'a', code: 'KeyA', vk: 65, modifiers: 4 });
  await cdp.key('keyUp',      { key: 'a', code: 'KeyA', vk: 65, modifiers: 4 });
  await sleep(120);
  // Delete the selection — trusted backspace
  await cdp.key('rawKeyDown', { key: 'Backspace', code: 'Backspace', vk: 8 });
  await cdp.key('keyUp',      { key: 'Backspace', code: 'Backspace', vk: 8 });
  await sleep(120);
  // Insert the new prompt (trusted) — Lexical accepts it
  await cdp.insertText(prompt);
  await sleep(300);
  const len = await cdp.evaluate(`document.querySelector('[contenteditable]').innerText.trim().length`);
  return len;
}

async function clickGenerate(cdp) {
  return await cdp.evaluate(`(function(){
    var b=[...document.querySelectorAll('button')];
    var f=null;
    b.forEach(function(x){var t=(x.innerText||'').trim(); if(!f && (t.indexOf('Unlimited')===0||t.indexOf('Generate')===0) && x.offsetWidth>120 && !x.disabled) f=x;});
    if(!f) b.forEach(function(x){var t=(x.innerText||'').trim(); if(!f && (t.indexOf('Unlimited')===0||t.indexOf('Generate')===0)) f=x;});
    if(f){f.click(); return 'clicked ['+f.innerText.trim().split(String.fromCharCode(10))[0].slice(0,15)+']';}
    return 'NOT_FOUND';
  })()`);
}

(async () => {
  // 1) find the Higgsfield tab target
  let targets;
  try { targets = JSON.parse(await httpGet('/json')); }
  catch (e) { console.error('Cannot reach Chrome debug port ' + PORT + '. Start Chrome with ./start_chrome_debug.sh first.'); process.exit(1); }
  const tab = targets.find(t => t.type === 'page' && (t.url || '').includes(URL_MATCH));
  if (!tab) { console.error('No Chrome tab on ' + URL_MATCH + '. Open it first.'); process.exit(1); }

  // 2) parse prompts
  const prompts = fs.readFileSync(PROMPTS_FILE, 'utf8')
    .split(/\r?\n/).filter(l => /^[0-9]+\.\s/.test(l)).map(l => l.replace(/^[0-9]+\.\s/, '').trim());
  if (!prompts.length) { console.error('No numbered prompts in ' + PROMPTS_FILE); process.exit(1); }

  console.log('======================================================');
  console.log('  Agent : ' + AGENT_NAME + '  (CDP true-background)');
  console.log('  Model : ' + MODEL + '   Quality: ' + QUALITY + '   Aspect: ' + ASPECT + '   Unlimited: ' + UNLIMITED);
  console.log('  File  : ' + PROMPTS_FILE + '   (' + prompts.length + ' prompts)   Wait: ' + WAIT + 's');
  console.log('======================================================');

  // 3) connect
  const cdp = new CDP(tab.webSocketDebuggerUrl);
  await cdp.connect();
  await cdp.send('Runtime.enable', {});
  await cdp.send('Page.enable', {});

  // 4) settings once
  console.log('Applying settings...');
  await applySettings(cdp);
  console.log('');

  // 5) loop
  for (let i = 0; i < prompts.length; i++) {
    console.log('=== [' + (i + 1) + '/' + prompts.length + '] ===');
    console.log('    ' + prompts[i]);
    const len = await typePrompt(cdp, prompts[i]);
    console.log('    typed (len=' + len + ')');
    console.log('    ' + await clickGenerate(cdp));
    console.log('    waiting ' + WAIT + 's...');
    await sleep(WAIT * 1000);
    console.log('    done.\n');
  }

  console.log('=== ' + AGENT_NAME + ' finished: ' + prompts.length + ' image(s). Check the History tab. ===');
  cdp.ws.close();
  process.exit(0);
})().catch(e => { console.error('FATAL: ' + e.message); process.exit(1); });
