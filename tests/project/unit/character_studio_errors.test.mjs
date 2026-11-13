import assert from 'node:assert/strict';
import {test} from 'node:test';
import {generateCharacterImage} from '../../../src/vsc/interfaces/web/static/character-studio-ai.js';

const recipe={extraImages:[{url:'data:image/png;base64,AA=='}]};
const options=(provider='agy_auth')=>({recipe,prompt:'test',config:{activeProvider:provider,providers:{[provider]:{model:'test-model',apiKey:'private-browser-key'}},imagePassMode:'url',useProxy:false,geminiParams:{endpointMode:'compat'},gptParams:{endpointMode:'chat'},qwenParams:{},doubaoParams:{}}});
async function failingResponse(provider,json,{status=502,invalid=false,headers={}}={}){
 const original=globalThis.fetch;
 globalThis.fetch=async()=>({ok:status<400,status,headers:new Headers(headers),json:async()=>{if(invalid)throw new SyntaxError('invalid');return json;}});
 try{await generateCharacterImage(options(provider));assert.fail('must fail');}
 catch(error){assert.notEqual(error.code,'ERR_ASSERTION');return error.message;}
 finally{globalThis.fetch=original;}
}

test('all auth channels retain backend detail, HTTP status and the selected model',async()=>{
 for(const provider of ['agy_auth','grok_auth','codex_auth']){
  const message=await failingResponse(provider,{detail:'模型不可用：MODEL_NOT_FOUND；request_id=req-17'},{status:404});
  for(const fact of ['test-model','HTTP 状态：404','MODEL_NOT_FOUND','req-17'])assert.ok(message.includes(fact),message);
 }
});

test('API channels retain structured errors, request IDs, and redact credentials without dumping input',async()=>{
 for(const provider of ['gemini','gpt','grok','qwen','doubao']){
  const message=await failingResponse(provider,{error:{message:'model unavailable private-browser-key Bearer upstream-token',code:'MODEL_NOT_FOUND'},request_id:'req-api',input:{prompt:'private prompt'}},{status:404});
  for(const fact of ['test-model','HTTP 状态：404','MODEL_NOT_FOUND','req-api'])assert.ok(message.includes(fact),message);
  for(const value of ['private-browser-key','upstream-token','private prompt'])assert.ok(!message.includes(value),message);
 }
});

test('HTTP 200 without an image retains refusal, finish reason and structured failure facts',async()=>{
 const cases=[
  {promptFeedback:{blockReason:'SAFETY',blockReasonMessage:'reference image blocked'}},
  {candidates:[{finishReason:'IMAGE_SAFETY',content:{parts:[{text:'image rejected by policy'}]}}]},
  {choices:[{message:{content:[{type:'text',text:'This model cannot output images'}]}}]},
  {error:{message:'quota exhausted',code:'QuotaExceeded'},request_id:'req-noimage'},
  {status:'incomplete',incomplete_details:{reason:'max_output_tokens'}},
 ];
 for(const body of cases){
  const message=await failingResponse('gemini',body,{status:200});
  assert.match(message,/未返回可读取的图片/);assert.match(message,/HTTP 状态：200/);
  const fact=body.promptFeedback?.blockReason||body.candidates?.[0].finishReason||body.choices?.[0].message.content[0].text||body.error?.code||body.incomplete_details?.reason;
  assert.ok(message.includes(fact),message);assert.ok(!message.includes('slice is not a function'),message);
 }
 const empty=await failingResponse('agy_auth',{}, {status:200});
 assert.match(empty,/平台未提供具体失败原因/);assert.doesNotMatch(empty,/安全策略|额度不足|授权失效/);
});

test('non-JSON, network failure, and cancellation remain distinct',async()=>{
 const malformed=await failingResponse('agy_auth',null,{status:503,invalid:true,headers:{'x-request-id':'req-gateway'}});
 assert.match(malformed,/无法解析为 JSON/);assert.match(malformed,/503/);assert.match(malformed,/req-gateway/);
 const original=globalThis.fetch;
 try{
  globalThis.fetch=async()=>{throw new TypeError('Failed to fetch');};
  await assert.rejects(generateCharacterImage(options()),/未收到生成服务的 HTTP 响应[\s\S]*Failed to fetch/);
  globalThis.fetch=async()=>{throw new DOMException('stopped','AbortError');};
  await assert.rejects(generateCharacterImage(options()),error=>error.name==='AbortError');
 }finally{globalThis.fetch=original;}
});
