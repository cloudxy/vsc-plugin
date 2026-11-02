// Load the actual ES-module graph with native relative resolution. Each test
// environment gets its own graph and browser globals; no UI function is stubbed.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {pathToFileURL}=require('node:url');
const sourceRoot=path.resolve(process.env.VSC_TEST_ROOT||path.join(__dirname,'../../../..'),'src/vsc/interfaces/web/static');
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'vsc-frontend-modules-'));
const environments=globalThis.__vscFrontendModuleEnvironments ||= new Map();let sequence=0;
process.once('exit',()=>fs.rmSync(directory,{recursive:true,force:true}));
function moduleGraph(environment={},overrides={}){
 const id=++sequence,folder=path.join(directory,String(id)),copied=new Set();environments.set(id,environment);
 fs.mkdirSync(folder);fs.writeFileSync(path.join(folder,'package.json'),' {"type":"module"}');
 const names=Object.keys(environment);for(const name of names)if(!/^[a-zA-Z_$][\w$]*$/.test(name))throw new Error('Invalid fixture global '+name);
 const prefix=names.length?`const {${names.join(',')}}=globalThis.__vscFrontendModuleEnvironments.get(${id});\n`:'';
 function copy(name){
  const sourceFile=path.resolve(sourceRoot,name);if(!sourceFile.startsWith(sourceRoot+path.sep))throw new Error('Module escapes static root');
  const relative=path.relative(sourceRoot,sourceFile);if(copied.has(relative))return;copied.add(relative);
  const source=overrides[relative]??fs.readFileSync(sourceFile,'utf8'),target=path.join(folder,relative);
  fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,prefix+source);
  for(const match of source.matchAll(/\b(?:from\s*|import\s*\(\s*)['"](\.{1,2}\/[^'"]+\.js)['"]/g))copy(path.join(path.dirname(relative),match[1]));
 }
 return {load(name){copy(name);return import(pathToFileURL(path.join(folder,name)).href);}};
}
async function loadModule(name,environment={},overrides={}){return moduleGraph(environment,overrides).load(name);}
module.exports={moduleGraph,loadModule};
