import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import ts from 'typescript';

const source = await fs.readFile('src/api.ts','utf8');
const { outputText } = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}});
const { streamChat, ApiError } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
globalThis.sessionStorage={getItem:()=>null};
const chat={mode:'Conversation',messages:[{role:'user',content:'hello'}]};
const signal=new AbortController().signal;
const run=onEvent=>streamChat(chat,'hello','test:4b','vi',false,signal,onEvent);
const events=[];
globalThis.fetch=async()=>new Response('{"delta":"hello"}\n{"done":true}');
await run(e=>events.push(e));
assert.equal(events[0].delta,'hello');
assert.equal(events[1].done,true);
globalThis.fetch=async()=>new Response('{"delta":"unfinished"}\n');
await assert.rejects(()=>run(()=>{}),e=>e instanceof ApiError&&e.status===502);
globalThis.fetch=async()=>new Response('');
await assert.rejects(()=>run(()=>{}),e=>e instanceof ApiError&&e.status===502);
let cancelled=false;
globalThis.fetch=async()=>new Response(new ReadableStream({
  start(controller){controller.enqueue(new TextEncoder().encode('{"error":"AI unavailable"}\n'));},
  cancel(){cancelled=true;},
}));
await assert.rejects(()=>run(e=>{if(e.error)throw new Error(e.error);}),/AI unavailable/);
assert.equal(cancelled,true);
console.log('6 chat-stream assertions passed.');
