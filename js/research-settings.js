(() => {
  'use strict';
  let profile, schema, datasetDefaults;
  const $ = id => document.getElementById(id);
  const fields = [
    ['name','档案名称','text'],['research_goal','研究目标','textarea'],
    ['directions','研究方向定义（JSON，英文标识 → 描述）','json'],['questions','评审问题（JSON 数组）','json'],
    ['grades','ABCDE 分级定义（JSON）','json'],['retain_grades','保留等级（逗号分隔）','csv'],
    ['exclusions','排除范围（JSON 数组）','json'],['examples','分级正反例（JSON 数组）','json'],
    ['crawl.categories','arXiv 分类（逗号分隔）','csv'],['crawl.per_category','每分类候选上限','number'],['crawl.shortlist','关键词预选上限','number'],
    ['keyword_profile.method_keywords','预选关键词及权重（JSON）','json'],
    ['models.triage','摘要初筛模型','text'],['models.reader','全文阅读模型','text'],['models.judge','裁判模型','text'],
    ['models.base_url','模型接口地址（HTTPS）','text'],['models.judge_base_url','独立裁判接口（留空沿用阅读服务）','text'],
    ['reading.max_fulltext_papers','全文篇数上限（留空读全部候选）','nullable'],['reading.max_revisions','最大修订次数（0 或 1）','number'],
    ['output.language','输出语言','text'],['output.brief_sentences','精简版每篇句数（2–6）','number'],
    ['datasets.daily_limit','每日数据集推荐上限（1–10）','number'],['datasets.review_limit','每日数据卡评审上限（1–50）','number'],
    ['datasets.model','数据集评审模型','text'],['datasets.queries','数据集检索词（方向标识 → 英文词数组）','json'],['datasets.aliases','数据集别名 / 镜像合并（JSON）','json'],
    ['output.detail_words','详细版每篇目标字数','number'],['output.sections','详细版栏目（JSON 数组）','json']
  ];
  const get = (obj,path) => path.split('.').reduce((v,k)=>v[k],obj);
  function set(obj,path,value) { const parts=path.split('.');const key=parts.pop();parts.reduce((v,k)=>v[k],obj)[key]=value; }
  function validate(value, spec=schema, path='config') {
    if (spec.$ref) return validate(value, schema.$defs[spec.$ref.split('/').pop()],path);
    if (spec.anyOf) {
      if (!spec.anyOf.some(s=>{try{validate(value,s,path);return true;}catch{return false;}})) throw new Error(path+' 类型或数值不符合要求');
      return;
    }
    if (spec.enum && !spec.enum.includes(value)) throw new Error(path+' 不在允许选项中');
    const t=spec.type;
    if (t==='null' && value!==null || t==='integer' && !Number.isInteger(value) || t==='number' && typeof value!=='number' || t==='string' && typeof value!=='string' || t==='array' && !Array.isArray(value) || t==='object' && (value===null || typeof value!=='object' || Array.isArray(value))) throw new Error(path+' 类型错误');
    if (typeof value==='string' && spec.minLength && value.trim().length<spec.minLength) throw new Error(path+' 不能为空');
    if (typeof value==='number' && (value<(spec.minimum??-Infinity)||value>(spec.maximum??Infinity))) throw new Error(path+' 超出允许范围');
    if (Array.isArray(value)) {if(value.length<(spec.minItems||0)) throw new Error(path+' 项目不足');value.forEach((v,i)=>validate(v,spec.items||{},path+'['+i+']'));}
    if (t==='object') {
      for(const key of spec.required||[]) if(!(key in value)) throw new Error(path+' 缺少 '+key);
      for(const [key,v] of Object.entries(value)) {
        if (/^(api[_-]?key|token|password|secret)$/i.test(key)) throw new Error('配置中不能保存密钥');
        const child=spec.properties?.[key] || spec.additionalProperties;
        if(child===false || (!child && spec.additionalProperties===false)) throw new Error(path+' 未知字段 '+key);
        if(child && typeof child==='object') validate(v,child,path+'.'+key);
      }
    }
  }
  function check(value) {
    if (!value.datasets && datasetDefaults) value.datasets=structuredClone(datasetDefaults);
    validate(value);
    if(value.version!==1 || Object.keys(value.grades).sort().join('')!=='ABCDE' || !value.retain_grades.every(g=>'ABCDE'.includes(g)&&g.length===1)) throw new Error('请保留完整ABCDE定义及合法保留等级');
    if(!Object.keys(value.directions).length || !Object.entries(value.directions).every(([k,v])=>/^[a-z][a-z0-9_]*$/.test(k)&&v.trim())) throw new Error('方向需要英文小写标识及非空描述');
    if(value.datasets && (!Object.keys(value.datasets.queries).every(k=>k in value.directions) || value.datasets.daily_limit>value.datasets.review_limit)) throw new Error('数据集检索方向需存在于研究档案，推荐上限不能超过评审上限');
    if(!value.crawl.categories.every(c=>/^[A-Za-z][A-Za-z0-9.-]*$/.test(c))) throw new Error('分类格式错误');
    for(const u of [value.models.base_url,value.models.judge_base_url]) if(u && new URL(u).protocol!=='https:') throw new Error('接口必须使用HTTPS');
    if(!Object.keys(value.keyword_profile.method_keywords).length || !Object.entries(value.keyword_profile.method_keywords).every(([k,v])=>k.trim()&&typeof v==='number'&&v>=0)) throw new Error('关键词权重需为非负数');
  }
  function collect() {
    const result=structuredClone(profile);
    for(const [path,,type] of fields) {
      const raw=String($('field-'+path).value);
      set(result,path,type==='json'?JSON.parse(raw):type==='csv'?raw.split(',').map(v=>v.trim()).filter(Boolean):type==='nullable'?(raw.trim()?Number(raw):null):type==='number'?Number(raw):raw.trim());
    }
    check(result);return result;
  }
  function render() {
    $('profileFields').replaceChildren();
    for(const [path,label,type] of fields) {
      const div=document.createElement('div');div.className='profile-field';
      const l=document.createElement('label');l.textContent=label;l.htmlFor='field-'+path;
      const el=document.createElement(['json','textarea'].includes(type)?'textarea':'input');el.id=l.htmlFor;
      if(['number','nullable'].includes(type))el.type='number';
      const value=get(profile,path);el.value=type==='json'?JSON.stringify(value,null,2):type==='csv'?value.join(', '):value??'';
      el.addEventListener('change',()=>{try{$('profileJson').value=JSON.stringify(collect(),null,2);$('profileStatus').textContent='配置已编辑，尚未导出或上传。';}catch(e){$('profileStatus').textContent=e.message;}});
      div.append(l,el);$('profileFields').append(div);
    }
    $('profileJson').value=JSON.stringify(profile,null,2);$('exportProfile').disabled=false;
  }
  $('exportProfile').addEventListener('click',()=>{try{
    profile=collect();const url=URL.createObjectURL(new Blob([JSON.stringify(profile,null,2)+'\n'],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='research_config.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    $('profileStatus').textContent='已导出。请替换自己仓库 main 分支的 research_config.json；Actions 会再次完整校验。';
  }catch(e){$('profileStatus').textContent=e.message;}});
  function apply(text){const value=JSON.parse(text);check(value);profile=value;render();$('profileStatus').textContent='配置已导入，导出并上传仓库后生效。';}
  $('applyJson').addEventListener('click',()=>{try{apply($('profileJson').value);}catch(e){$('profileStatus').textContent=e.message;}});
  $('importProfile').addEventListener('change',async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>1000000)throw new Error('配置文件过大');apply(await file.text());}catch(e){$('profileStatus').textContent=e.message;}});
  Promise.all(['research_config.json','research_config.schema.json'].map(async url=>{const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error('无法读取配置：'+r.status);return r.json();})).then(([config,s])=>{schema=s;datasetDefaults=config.datasets;check(config);profile=config;render();$('profileStatus').textContent='已读取仓库当前研究档案。';}).catch(e=>{$('profileStatus').textContent=e.message;});
})();
