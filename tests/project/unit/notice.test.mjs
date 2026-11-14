import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createRequire} from 'node:module';
import {createNotice} from '../../../src/vsc/interfaces/web/static/notice.js';
import {msg,setLocale} from '../../../src/vsc/interfaces/web/static/i18n.js';
const require=createRequire(import.meta.url),{Document,createPanel}=require('../../support/fixtures/frontend/panel_dom.cjs');
function clock(t){
 const originalSet=globalThis.setTimeout,originalClear=globalThis.clearTimeout,timers=new Map();let now=0,sequence=0;
 globalThis.setTimeout=(fn,delay=0)=>{const id=++sequence;timers.set(id,{fn,at:now+delay});return id;};globalThis.clearTimeout=id=>timers.delete(id);
 t.after(()=>{globalThis.setTimeout=originalSet;globalThis.clearTimeout=originalClear;setLocale('zh-cn',{persist:false});});
 return {timers,advance(ms){const end=now+ms;while(true){const next=[...timers].sort((a,b)=>a[1].at-b[1].at).find(([,timer])=>timer.at<=end);if(!next)break;now=next[1].at;timers.delete(next[0]);next[1].fn();}now=end;}};
}
function setup(t){const time=clock(t),document=new Document(''),host=document.createElement('div');document.body.append(host);return {time,host,notice:createNotice(host)};}

test('transient feedback stays for three seconds then fades before removal',t=>{
 const h=setup(t);h.notice.show('已随机抽取一套角色配方',{duration:3000});
 assert.equal(h.host.children[0].className,'notice-close');assert.equal(h.host.hidden,false);
 h.time.advance(2999);assert.equal(h.host.classList.contains('notice-leaving'),false);
 h.time.advance(1);assert.equal(h.host.classList.contains('notice-leaving'),true);assert.equal(h.host.hidden,false);
 h.time.advance(299);assert.equal(h.host.hidden,false);h.time.advance(1);assert.equal(h.host.hidden,true);assert.equal(h.host.children.length,0);assert.equal(h.time.timers.size,0);
});

test('manual close hides the message immediately and cancels both lifetime timers',async t=>{
 const h=setup(t);
 for(const elapsed of [1000,3000]){
  h.notice.show('配方已更新',{duration:3000});h.time.advance(elapsed);
  const close=h.host.querySelector('button');assert.equal(close.getAttribute('aria-label'),'关闭');await close.click();
  assert.equal(h.host.hidden,true);assert.equal(h.time.timers.size,0);h.time.advance(300);assert.equal(h.host.hidden,true);
 }
});

test('replacement cannot be hidden by a late timeout, fade, or detached close button',async t=>{
 const h=setup(t);h.notice.show('first',{duration:3000});const staleDelay=[...h.time.timers.values()][0].fn,oldClose=h.host.querySelector('button');
 h.notice.show('second',{duration:3000});staleDelay();await oldClose.click();assert.ok(h.host.textContent.includes('second'));assert.equal(h.host.classList.contains('notice-leaving'),false);
 h.time.advance(3000);const staleFade=[...h.time.timers.values()][0].fn;h.notice.show('important error');staleFade();h.time.advance(10000);
 assert.equal(h.host.hidden,false);assert.ok(h.host.textContent.includes('important error'));assert.equal(h.time.timers.size,0);
});

test('persistent errors remain dismissible and locale updates retain the close button',t=>{
 const h=setup(t);h.notice.show(msg('common.completed'));const close=h.host.querySelector('button');setLocale('en',{persist:false});
 assert.equal(h.host.querySelector('button'),close);assert.equal(close.getAttribute('aria-label'),'Close');h.time.advance(10000);assert.equal(h.host.hidden,false);
 h.notice.show('');assert.equal(h.host.hidden,true);assert.equal(h.host.children.length,0);
});

test('the actual panel forwards a caller lifetime without changing other notices',t=>{
 const time=clock(t),root=new URL('../../..',import.meta.url).pathname,h=createPanel(root,new Map()),host=h.document.getElementById('notice');
 h.panel.notice('random recipe',{duration:3000});time.advance(3000);assert.equal(host.classList.contains('notice-leaving'),true);time.advance(300);assert.equal(host.hidden,true);
 h.panel.notice('保存失败，请重试');time.advance(10000);assert.equal(host.hidden,false);assert.ok(host.querySelector('button'));
});
