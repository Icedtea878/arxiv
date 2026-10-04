const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const discovery = require('../js/dataset-discovery.js');
class Element {
  constructor() { this.children=[]; this.attrs={}; this.value='相关数据'; this.textContent=''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; }
  setAttribute(k,v) { this.attrs[k]=v; }
  addEventListener() {}
}
async function runSearch(fetch) {
  const elements = new Map();
  const document={getElementById(id) { if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id); },createElement:()=>new Element(),querySelectorAll:()=>[]};
  let code=fs.readFileSync(require.resolve('../js/datasets.js'),'utf8');
  const i=code.lastIndexOf('  search();');
  code=code.slice(0,i)+'  globalThis.done = search();'+code.slice(i+'  search();'.length);
  const context={document,window:{DatasetDiscovery:discovery},fetch,AbortController,DOMException,URLSearchParams,setTimeout:(fn,ms)=>setTimeout(fn,ms===400?0:ms),clearTimeout};
  vm.createContext(context); vm.runInContext(code,context); await context.done;
  return elements;
}
test('429 retains partial results and stops remaining requests', async () => {
  let calls=0;
  const elements=await runSearch(async()=> ++calls===1 ? {ok:true,json:async()=>[{id:'test/persona',description:'User preferences'}]} : {ok:false,status:429});
  assert.equal(calls,2);
  assert.equal(elements.get('datasetResults').children.length,1);
  assert.match(elements.get('datasetStatus').textContent,/结果不完整/);
  assert.equal(elements.get('datasetResults').attrs['aria-busy'],'false');
});
test('full broad search deduplicates results across terms', async () => {
  let calls=0;
  const elements=await runSearch(async()=> {calls++; return {ok:true,json:async()=>[{id:'test/dialogue',description:'Synthetic dialogue'}]};});
  assert.equal(calls,12);
  assert.equal(elements.get('datasetResults').children.length,1);
  assert.match(elements.get('datasetStatus').textContent,/1 条去重候选/);
});
