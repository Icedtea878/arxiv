const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function page(){
 const elements=new Map(),storage=new Map();let blob;
 function el(tag='DIV'){return {tagName:tag.toUpperCase(),value:'unseen',children:[],attrs:{},listeners:{},append(...v){this.children.push(...v)},replaceChildren(...v){this.children=v},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,fn){this.listeners[k]=fn},click(){this.listeners.click?.()}};}
 const document={getElementById(id){if(!elements.has(id))elements.set(id,el());return elements.get(id)},createElement:el};
 const unknown={status:'unknown',value:'unknown',evidence:[]};
 const report={date:'2026-10-05',directions:{individual:'个体'},warnings:[],reviewed_this_run:10,datasets:[{id:'test/persona',url:'https://huggingface.co/datasets/test/persona',reason_type:'首次推荐',license:'未知',papers:['2601.12345'],coverage_notes:[],source_links:{card:'https://huggingface.co/datasets/test/persona'},review:{grade:'A',suitability:'unknown',directions:['individual'],overview:'<script>unsafe()</script>',application:'尝试个体行为预测',reason:'有行为字段证据',origin:unknown,individual_id:unknown,time_info:unknown,labels:unknown,constraints:['未核验时间'],evidence:['card']}}]};
 const context={document,DATA_CONFIG:{getDataUrl:p=>'https://raw.example/'+p},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},Blob,URL:class extends URL{static createObjectURL(b){blob=b;return 'blob:test'}static revokeObjectURL(){}},setTimeout:()=>0,fetch:async url=>({ok:true,json:async()=>url==='dataset_feedback.json'?{feedback:{}}:url.endsWith('index.json')?{dates:['2026-10-05']}:report})};
 vm.createContext(context);vm.runInContext(fs.readFileSync('js/dataset-daily.js','utf8').replace('  start();','  globalThis.ready=start();'),context);await context.ready;
 return {elements,storage,getBlob:()=>blob};
}
test('daily cards safely show evidence, unknown facts and graded recommendations',async()=>{
 const {elements}=await page();const cards=elements.get('dailyDatasetResults').children;assert.equal(cards.length,1);
 assert.equal(cards[0].children[2].textContent,'<script>unsafe()</script>');assert.equal(cards[0].children[2].innerHTML,undefined);
 assert.match(elements.get('dailyDatasetStatus').textContent,/推荐 1 个/);assert.match(cards[0].children[5].children[1].textContent,/个体 ID：未知/);
});
test('feedback hides seen items, can be undone and exports persistent preferences',async()=>{
 const {elements,storage,getBlob}=await page();let card=elements.get('dailyDatasetResults').children[0];
 card.children.at(-1).children[2].click();assert.equal(elements.get('dailyDatasetResults').children.length,0);
 assert.equal(JSON.parse(storage.get('arxiv-dataset-feedback-v1'))['test/persona'],'seen');
 elements.get('datasetFeedbackFilter').value='all';elements.get('datasetFeedbackFilter').listeners.change();
 assert.equal(elements.get('dailyDatasetResults').children.length,1);
 elements.get('exportDatasetFeedback').click();assert.equal(JSON.parse(await getBlob().text()).feedback['test/persona'],'seen');
 card=elements.get('dailyDatasetResults').children[0];card.children.at(-1).children[2].click();assert.equal(JSON.parse(storage.get('arxiv-dataset-feedback-v1'))['test/persona'],undefined);
});
