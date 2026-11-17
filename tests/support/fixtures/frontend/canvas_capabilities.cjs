// Use the real server catalogue in canvas DOM fixtures as its shape evolves.
const {execFileSync}=require('node:child_process');
const path=require('node:path');
const root=process.env.VSC_TEST_ROOT||path.resolve(__dirname,'../../../..'),cache=new Map();
function catalogueFor(models=[]){
  const key=JSON.stringify(models);
  if(!cache.has(key))cache.set(key,JSON.parse(execFileSync(path.join(root,'.venv/bin/python'),['-c',
    "import json,sys;sys.path.insert(0,'src');from vsc.production.canvas_capabilities import canvas_capabilities;print(json.dumps(canvas_capabilities(json.loads(sys.argv[1]))))",key],{cwd:root,encoding:'utf8'})));
  return structuredClone(cache.get(key));
}
module.exports={catalogueFor};
