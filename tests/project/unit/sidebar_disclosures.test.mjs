import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import {msg,setText,setLocale} from '../../../src/vsc/interfaces/web/static/i18n.js';

const {Document}=createRequire(import.meta.url)('../../support/fixtures/frontend/panel_dom.cjs');
const source=readFileSync(new URL('../../../src/vsc/interfaces/web/static/panel.js',import.meta.url),'utf8');
const start=source.indexOf('// Sidebar disclosures only affect visibility;');
const end=source.indexOf('// End sidebar disclosures.',start);
assert.ok(start>=0&&end>start,'execute the sidebar handlers from the owning panel module');

function setup({empty=false}={}){
  const document=new Document('');
  const node=(tag,id)=>{const element=document.createElement(tag);if(id)element.id=id;return element;};
  const section=node('section'),heading=node('h2'),label=node('span');section.className='recent-projects';
  const toggle=node('button','recent-projects-toggle'),region=node('div','recent-projects'),project=node('a');
  toggle.append(label);heading.append(toggle);section.append(heading,region);
  toggle.setAttribute('aria-expanded','true');project.textContent='已保存的创作';region.append(project);
  const help=node('details');help.className='sidebar-help';
  const summary=node('summary'),menu=node('div'),feedback=node('button','help-feedback'),feedbackIcon=node('svg'),feedbackLabel=node('span');
  feedback.append(feedbackIcon,feedbackLabel);
  help.append(summary,menu);menu.append(feedback);
  if(!empty)document.body.append(section,help);
  const query=document.querySelector.bind(document);
  document.querySelector=selector=>{const [first,...children]=selector.split(/\s*>\s*/);let found=query(first);for(const child of children)found=found?.children.find(item=>item.matches(child));return found||null;};
  vm.runInNewContext(source.slice(start,end),{document,$:id=>document.getElementById(id)});
  return {document,toggle,region,project,help,summary,feedback,heading,label,feedbackIcon,feedbackLabel};
}

test('recent creation disclosure supports keyboard activation and preserves rendered projects',async()=>{
  const {toggle,region,project}=setup();
  await toggle.pressKey('Enter');assert.equal(toggle.getAttribute('aria-expanded'),'false');assert.equal(region.hidden,true);
  await toggle.pressKey(' ');assert.equal(toggle.getAttribute('aria-expanded'),'true');assert.equal(region.hidden,false);
  assert.equal(region.children[0],project);assert.equal(project.textContent,'已保存的创作');
});

test('help opens with a mouse or tap, retains keyboard focus and dismisses outside',async()=>{
  const {document,help,summary,feedback}=setup();
  const isOpen=()=>help.getAttribute('open')!==null;
  await help.dispatch('pointerenter',{pointerType:'touch'});assert.equal(isOpen(),false);
  const click=await summary.click();assert.equal(click.defaultPrevented,true);assert.equal(isOpen(),true);
  feedback.focus();await help.dispatch('pointerleave');assert.equal(isOpen(),true);
  await help.dispatch('focusout',{relatedTarget:summary});assert.equal(isOpen(),true);
  const escape=await help.dispatch('keydown',{key:'Escape'});assert.equal(escape.defaultPrevented,true);assert.equal(isOpen(),false);assert.equal(document.activeElement,summary);
  await help.dispatch('pointerenter',{pointerType:'mouse'});assert.equal(isOpen(),true);
  document.body.focus();await help.dispatch('pointerleave');assert.equal(isOpen(),false);
  await help.dispatch('pointerenter',{pointerType:'mouse'});
  await document.body.dispatch('pointerdown',{target:feedback});assert.equal(isOpen(),true);
  await document.body.dispatch('pointerdown');assert.equal(isOpen(),false);
  await help.dispatch('pointerenter',{pointerType:'mouse'});
  await help.dispatch('focusout',{relatedTarget:document.body});assert.equal(isOpen(),false);
});

test('sidebar handlers tolerate pages without sidebar controls',async()=>{
  const {document}=setup({empty:true});await document.body.dispatch('pointerdown');
});

test('shell locale binding updates the caption without replacing the live disclosure',async()=>{
  const {document,toggle,region,heading,label,feedback,feedbackIcon,feedbackLabel}=setup();
  const bindings=source.split('\n').filter(line=>line.startsWith('for(const [selector,key]')&&(line.includes(".brand > span")||line.includes("#help-guide"))).join('\n');
  assert.ok(bindings,'execute the actual shell translation bindings');
  vm.runInNewContext(bindings,{document,setText,msg});
  assert.equal(heading.children[0],toggle);assert.equal(label.textContent,'最近创作');assert.equal(feedback.children[0],feedbackIcon);assert.equal(feedbackLabel.textContent,'意见反馈');
  try{
    setLocale('en',{persist:false});assert.equal(label.textContent,'Recent Creations');assert.equal(feedbackLabel.textContent,'Feedback');assert.equal(feedback.children[0],feedbackIcon);
    await toggle.click();assert.equal(region.hidden,true);assert.equal(heading.children[0],toggle);
  }finally{setLocale('zh-cn',{persist:false});}
});
