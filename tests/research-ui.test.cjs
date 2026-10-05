const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('js/app.js','utf8');
function fn(name){const start=source.indexOf('function '+name+'(');const end=source.indexOf('\nfunction ',start+10);return source.slice(start,end);}
test('new grades are not removed by old numeric threshold and sort ABC',()=>{
 const context={console,window:{researchDates:new Set(['2026-10-05']),relevanceDates:new Set(['2026-10-04','2026-10-05'])}};
 vm.createContext(context);for(const name of ['escapePaperText','parseJsonlData','compareRelevanceScores'])vm.runInContext(fn(name),context);
 const rows=['C','A','B'].map((grade,i)=>({id:String(i),title:'paper',categories:['cs.AI'],research_review:{grade,status:'reviewed',analysis:{brief:['<unsafe>','Summary']}},summary:'abstract'}));
 const papers=context.parseJsonlData(rows.map(JSON.stringify).join('\n'),'2026-10-05')['cs.AI'];
 assert.equal(papers.length,3);papers.sort(context.compareRelevanceScores);assert.equal(papers.map(p=>p.research_review.grade).join(''),'ABC');
 assert.equal(papers[0].summary,'&lt;unsafe&gt; Summary');
 assert.equal(Object.keys(context.parseJsonlData(JSON.stringify({...rows[0],relevance:{score:80}}),'2026-10-04')).length,0);
});
test('profile editor loads real schema and exports edited config',async()=>{
 const elements=new Map();let blob;
 function element(){const el={value:'',children:[],listeners:{},append(...x){this.children.push(...x);},replaceChildren(){this.children=[];},addEventListener(n,fn){this.listeners[n]=fn;},click(){this.listeners.click?.();}};Object.defineProperty(el,'id',{set(v){elements.set(v,el);},get(){return [...elements].find(([,e])=>e===el)?.[0];}});return el;}
 const document={getElementById(id){if(!elements.has(id)){const el=element();el.id=id;}return elements.get(id);},createElement:element};
 const context={document,structuredClone,Blob,URL:class extends URL {static createObjectURL(b){blob=b;return 'blob:test';} static revokeObjectURL(){}},setTimeout:()=>0,fetch:async url=>({ok:true,json:async()=>JSON.parse(fs.readFileSync(url,'utf8'))})};
 vm.createContext(context);vm.runInContext(fs.readFileSync('js/research-settings.js','utf8'),context);
 await new Promise(resolve=>setImmediate(resolve));
 assert.match(elements.get('profileStatus').textContent,/已读取/);
 elements.get('field-research_goal').value='Study human cooperation';
 elements.get('exportProfile').listeners.click();
 assert.equal(JSON.parse(await blob.text()).research_goal,'Study human cooperation');
 elements.get('field-output.brief_sentences').value='20';
 elements.get('exportProfile').listeners.click();
 assert.match(elements.get('profileStatus').textContent,/超出/);
});
