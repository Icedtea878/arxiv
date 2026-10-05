/* Daily recommendations use committed, reviewed results; feedback stays local until exported. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const key = 'arxiv-dataset-feedback-v1';
  let feedback = {}, report, stored = {};
  try { stored = JSON.parse(localStorage.getItem(key) || '{}'); } catch {}
  const gradeNames = {A:'核心用途', B:'直接支撑', C:'有条件借鉴'};
  const usability = {usable:'可以尝试', conditional:'需处理或验证', unknown:'信息待确认'};
  const origin = {real:'真人 / 真实观测', synthetic:'合成', mixed:'混合', unknown:'未知'};
  const labels = {useful:'有用', not_relevant:'不相关', seen:'已看'};
  function node(tag,text,className) {
    const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;
  }
  function link(label,url) {
    const a=node('a',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;
  }
  function safeUrl(url) {
    try {const u=new URL(url);return u.protocol==='https:' && ['huggingface.co','arxiv.org'].includes(u.hostname);} catch {return false;}
  }
  function setFeedback(id,value) {
    if(value) feedback[id]=value;else delete feedback[id];
    try {localStorage.setItem(key,JSON.stringify(feedback));} catch { $('dailyDatasetStatus').textContent='浏览器未允许保存反馈，请导出反馈文件。'; }
    render();
  }
  function fact(r,name) {return r[name]?.status==='known'?r[name].value:'未知';}
  function render() {
    const grid=$('dailyDatasetResults');grid.replaceChildren();if(!report)return;
    const rows=report.datasets.filter(r=>$('datasetFeedbackFilter').value==='all' || !['seen','not_relevant'].includes(feedback[r.id]));
    for(const item of rows) {
      if(!/^[\w.-]+(?:\/[\w.-]+)?$/.test(item.id) || !safeUrl(item.url))continue;
      const r=item.review;const card=node('article',undefined,'dataset-card');
      const heading=node('h3');heading.append(link(item.id,item.url));
      const meta=node('p',`${r.grade} · ${gradeNames[r.grade]||r.grade} · ${usability[r.suitability]} · ${item.reason_type}`,'dataset-relevance');
      const directions=r.directions.map(d=>report.directions[d]||d).join('；');
      const overview=node('p',r.overview,'dataset-description');
      const use=node('p','研究用途（推断）：'+r.application,'dataset-description');
      const reason=node('p','匹配依据：'+r.reason,'dataset-description');
      const facts=node('p',`数据来源：${origin[fact(r,'origin')]||fact(r,'origin')}\n个体 ID：${fact(r,'individual_id')}\n时间信息：${fact(r,'time_info')}\n行为 / 任务标签：${fact(r,'labels')}\n许可：${Array.isArray(item.license)?item.license.join('、'):item.license||'未知'}${item.gated?' · 需要申请访问':''}`,'dataset-description');
      const constraints=node('p','使用限制：'+[...r.constraints,...item.coverage_notes].join('；'),'dataset-description');
      const details=node('details');details.append(node('summary','查看数据属性和使用限制'),facts,constraints,node('p','对应方向：'+directions,'dataset-description'));
      const links=node('div',undefined,'dataset-card-links');links.append(link('数据卡 ↗',item.url));
      for(const sid of r.evidence) {const url=item.source_links[sid];if(safeUrl(url))links.append(link('依据 '+sid+' ↗',url));}
      for(const id of item.papers||[])if(/^\d{4}\.\d{4,5}(v\d+)?$/.test(id))links.append(link('关联论文 ↗','https://arxiv.org/abs/'+id));
      const actions=node('div',undefined,'dataset-feedback');
      for(const [value,label] of Object.entries(labels)) {
        const button=node('button',label);button.type='button';button.setAttribute('aria-pressed',String(feedback[item.id]===value));
        button.addEventListener('click',()=>setFeedback(item.id,feedback[item.id]===value?null:value));actions.append(button);
      }
      if(feedback[item.id])actions.append(node('span','已标记：'+labels[feedback[item.id]]));
      card.append(heading,meta,overview,use,reason,details,links,actions);grid.append(card);
    }
    $('dailyDatasetStatus').textContent=`${report.date}（UTC）· 推荐 ${report.datasets.length} 个，当前显示 ${rows.length} 个；本次评审 ${report.reviewed_this_run} 个候选。`+
      (report.datasets.length?'':' 没有新增的高相关数据集，不重复推荐或凑数。')+(report.warnings.length?' 检索提示：'+report.warnings.join('；'):'');
    $('datasetReportLink').href=DATA_CONFIG.getDataUrl('data/datasets/'+report.date+'.md');$('datasetReportLink').hidden=false;
  }
  async function json(path,optional=false) {
    const response=await fetch(DATA_CONFIG.getDataUrl(path),{cache:'no-store'});
    if(optional && response.status===404)return null;
    if(!response.ok)throw new Error('无法读取每日精选：HTTP '+response.status);
    return response.json();
  }
  async function load(day) {
    $('dailyDatasetResults').setAttribute('aria-busy','true');
    try {report=await json('data/datasets/'+day+'.json');render();}
    catch(error){$('dailyDatasetStatus').textContent=error.message;}
    finally{$('dailyDatasetResults').setAttribute('aria-busy','false');}
  }
  $('datasetFeedbackFilter').addEventListener('change',render);
  $('datasetDate').addEventListener('change',event=>load(event.target.value));
  $('exportDatasetFeedback').addEventListener('click',()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,feedback},null,2)+'\n'],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='dataset_feedback.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  async function start() {
    $('dailyDatasetStatus').textContent='正在读取每日数据集精选…';
    try {
      try {const r=await fetch('dataset_feedback.json',{cache:'no-store'});if(r.ok)feedback={...(await r.json()).feedback,...stored};else feedback=stored;} catch {feedback=stored;}
      const index=await json('data/datasets/index.json',true);
      if(!index?.dates?.length){$('dailyDatasetStatus').textContent='每日数据集精选尚未生成；首次工作流成功后会出现在这里。也可以展开下方手动搜索。';return;}
      for(const day of index.dates.filter(d=>/^\d{4}-\d{2}-\d{2}$/.test(d))) {const option=node('option',day);option.value=day;$('datasetDate').append(option);}
      await load(index.dates[0]);
    }catch(error){$('dailyDatasetStatus').textContent=error.message+'；可以展开下方手动搜索。';}
  }
  start();
})();
