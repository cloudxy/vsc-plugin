// Small browser DOM fixture. Tests execute the real panel module with fake HTTP.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(document, tag) {
    this.ownerDocument = document;
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.parentElement = null;
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.hidden = false;
    this.value = '';
    this._text = '';
    this._classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => this._classes.add(name)),
      remove: (...names) => names.forEach(name => this._classes.delete(name)),
      contains: name => this._classes.has(name),
      toggle: (name, force) => {
        const include = force === undefined ? !this._classes.has(name) : force;
        if (include) this._classes.add(name); else this._classes.delete(name);
        return include;
      },
    };
  }
  set className(value) { this._classes = new Set(value.split(/\s+/).filter(Boolean)); }
  get className() { return [...this._classes].join(' '); }
  set textContent(value) { this._text = String(value); this.replaceChildren(); }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set id(value) { this.attributes.set('id', value); }
  get id() { return this.attributes.get('id') || ''; }
  get childElementCount() { return this.children.length; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); if(name==='class')this.className=String(value); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  append(...children) {
    for (let child of children) {
      if (typeof child === 'string') child = this.ownerDocument.createTextNode(child);
      if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(item => item !== child);
      child.parentElement = this;
      this.children.push(child);
      if (this.tagName === 'SELECT' && this.children.length === 1) this.value = child.value;
    }
  }
  prepend(...children) {
    const previous=[...this.children];this.replaceChildren(...children,...previous);
  }
  replaceChildren(...children) {
    for (const child of this.children) child.parentElement = null;
    this.children = [];
    this.append(...children);
  }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    return this.tagName.toLowerCase() === selector.toLowerCase();
  }
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (child.matches(selector)) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  remove() { if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(child=>child!==this);this.parentElement=null; }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }
  async dispatch(type, properties = {}) {
    const event = {type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...properties};
    for (const listener of this.listeners.get(type) || []) await listener(event);
    return event;
  }
  async click(properties={}) { if(!this.disabled){this.focus();return this.dispatch('click',{detail:1,...properties});} }
  async pressKey(key) {
    this.focus();
    const event = await this.dispatch('keydown', {key});
    // Native HTML buttons activate via Enter/Space without custom JS handlers.
    if (!event.defaultPrevented && this.tagName === 'BUTTON' && ['Enter', ' '].includes(key)) await this.click({detail:0});
    return event;
  }
  focus() { this.ownerDocument.activeElement = this; }
  visible() {
    for (let node = this; node; node = node.parentElement) if (node.hidden) return false;
    return true;
  }
}

class Document {
  constructor(html) {
    this.body = new Element(this, 'body');
    for (const match of html.matchAll(/<([a-z][\w-]*)\b([^>]*\bid="[^"]+"[^>]*)>/gi)) {
      const node = this.createElement(match[1]);
      for (const attribute of match[2].matchAll(/([\w-]+)="([^"]*)"/g)) node.setAttribute(attribute[1], attribute[2]);
      this.body.append(node);
    }
  }
  createElement(tag) { return new Element(this, tag); }
  createTextNode(text) { const node = new Element(this, '#text'); node.textContent = text; return node; }
  getElementById(id) { return this.body.querySelectorAll('#' + id)[0] || null; }
  querySelectorAll(selector) { return this.body.querySelectorAll(selector); }
}

function createPanel(root, projects, treeOverride = null, options = {}) {
  const folder = path.join(root, 'src/vsc/interfaces/web');
  const document = new Document(fs.readFileSync(path.join(folder, 'templates/index.html'), 'utf8'));
  const requests = [], writes = [], confirmations=[];
  for(const dialog of document.querySelectorAll('dialog')){
    dialog.close = () => {dialog.open=false;};
    dialog.showModal = () => {dialog.open=true;};
  }
  const fetch = async (url, options={}) => {
    requests.push(url);
    if(options.method==='POST')writes.push({url,headers:options.headers,body:JSON.parse(options.body)});
    const override=await fixtureOptions.handleRequest?.(url,options);
    if(override!==undefined)return {ok:true,status:200,json:async()=>override};
    if(options.method==='POST')return {ok:true,json:async()=>({revision:2,jobs:[]})};
    // Keep automatic startup pending; cases drive the real project selection.
    if (url === '/api/v1/session') return new Promise(() => {});
    let value;
    if (url === '/api/v1/projects') value = {items: [...projects.values()].map(data => data.project)};
    else if (url === '/api/v1/preview-capabilities') value = {};
    else {
      const match = url.match(/^\/api\/v1\/projects\/([^/]+)\/(tree|media|artifacts|workbench)(?:\/([^/?]+))?(?:\?|$)/);
      if (!match) throw new Error('Unexpected fixture request: ' + url);
      const project = projects.get(decodeURIComponent(match[1]));
      if (match[2] === 'tree') value = treeOverride ? await treeOverride(match[1], project) : project;
      else if(match[2]==='workbench'){const params=new URL(url,'http://fixture').searchParams;value={project_id:match[1],revision:project.revision,scope:project.nodes.find(row=>row.id===params.get('object_id'))||null,sections:{},summary:{},gaps:[],warnings:[],ancestors:[]};}
      else if(match[2]==='artifacts')value=match[3]?project.artifactDetails?.[decodeURIComponent(match[3])]:{items:project.artifacts||[]};
      else value = {items: [], total: 0, revision: project.revision};
    }
    return {ok: true, status: 200, json: async () => value};
  };
  const fixtureOptions=options;
  const memory=new Map();
  const context = vm.createContext({document, fetch, URLSearchParams, URL, AbortController, console, Map, Set,setTimeout,clearTimeout,localStorage:{getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value)},crypto:require('node:crypto').webcrypto,confirm:message=>{confirmations.push(message);return fixtureOptions.confirm?.(message)??true;}});
  vm.runInContext('(()=>{'+fs.readFileSync(path.join(folder,'static/artifact-reader.js'),'utf8').replaceAll('export function ','function ')+';globalThis.artifactReader={artifactTitle,renderArtifactContent};})()',context,{filename:'artifact-reader.js'});
  vm.runInContext('(()=>{'+fs.readFileSync(path.join(folder,'static/workbench.js'),'utf8').replace('export function createCreativeWorkbench','function createCreativeWorkbench')+';globalThis.createCreativeWorkbench=createCreativeWorkbench;})()',context,{filename:'workbench.js'});
  const source = fs.readFileSync(path.join(folder, 'static/panel.js'), 'utf8').replace("import {artifactTitle, renderArtifactContent} from './artifact-reader.js';",'const {artifactTitle,renderArtifactContent}=globalThis.artifactReader;').replace("await import('./workbench.js')",'await Promise.resolve({createCreativeWorkbench:globalThis.createCreativeWorkbench})');
  vm.runInContext(source + '\nglobalThis.panel = {state, applySession, renderTree, selectProject, selectObject, loadProjects, reviewForm, switchView, loadArtifacts, openArtifact};', context, {filename: 'panel.js'});
  return {document, requests, writes, confirmations, panel: context.panel};
}

module.exports = {createPanel,Document,Element};
