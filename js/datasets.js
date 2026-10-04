(() => {
  'use strict';
  const form = document.getElementById('datasetSearch');
  const input = document.getElementById('datasetQuery');
  const button = document.getElementById('searchButton');
  const status = document.getElementById('datasetStatus');
  const results = document.getElementById('datasetResults');
  const cache = new Map();
  const discovery = window.DatasetDiscovery;
  let activeRequest;
  let requestId = 0;
  let cooldownUntil = 0;

  function link(label, url) {
    const element = document.createElement('a');
    element.textContent = label;
    element.href = url;
    element.target = '_blank';
    element.rel = 'noopener noreferrer';
    return element;
  }

  function paperUrl(query) {
    return 'https://arxiv.org/search/?' + new URLSearchParams({
      query: query + ' dataset', searchtype: 'all', abstracts: 'show', order: '-announced_date_first'
    });
  }

  function updateLinks(query) {
    document.getElementById('hfSearchLink').href = 'https://huggingface.co/datasets?' + new URLSearchParams({search: query});
    document.getElementById('paperSearchLink').href = paperUrl(query);
    document.getElementById('googleDatasetLink').href = 'https://datasetsearch.research.google.com/search?' + new URLSearchParams({query});
  }

  function render(datasets) {
    results.replaceChildren();
    for (const dataset of datasets) {
      if (typeof dataset.id !== 'string' || !/^[\w./-]+$/.test(dataset.id)) continue;
      const card = document.createElement('article');
      card.className = 'dataset-card';
      const title = document.createElement('h2');
      const datasetUrl = 'https://huggingface.co/datasets/' + dataset.id;
      title.append(link(dataset.id, datasetUrl));
      const description = document.createElement('p');
      description.className = 'dataset-description';
      const plainDescription = String(dataset.description || '').replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();
      description.textContent = plainDescription ? plainDescription.slice(0, 260) + (plainDescription.length > 260 ? '…' : '') : '暂无简介，请打开数据卡查看数据格式和使用方法。';
      const meta = document.createElement('div');
      meta.className = 'dataset-meta';
      const license = dataset.cardData?.license;
      const tasks = dataset.cardData?.task_categories;
      const fields = [
        '下载 ' + Number(dataset.downloads || 0).toLocaleString('zh-CN'),
        '许可 ' + (Array.isArray(license) ? license.join(', ') : license || '未标注'),
        dataset.gated ? '需要申请访问' : '公开仓库',
        Array.isArray(tasks) ? tasks.join(', ') : ''
      ];
      for (const value of fields.filter(Boolean)) {
        const item = document.createElement('span');
        item.textContent = value;
        meta.append(item);
      }
      const links = document.createElement('div');
      links.className = 'dataset-card-links';
      links.append(link('查看数据卡 ↗', datasetUrl));
      const paperIds = (dataset.tags || []).filter(tag => /^arxiv:\d{4}\.\d{4,5}(v\d+)?$/.test(tag)).slice(0, 3);
      for (const tag of paperIds) links.append(link('关联论文 ' + tag.slice(6), 'https://arxiv.org/abs/' + tag.slice(6)));
      if (!paperIds.length) links.append(link('检索同名论文 ↗', paperUrl(dataset.id.split('/').pop())));
      const relevance = document.createElement('p');
      relevance.className = 'dataset-relevance';
      relevance.textContent = dataset.directions.length
        ? '相关线索：' + dataset.directions.map(d => `${d.label}（${d.matches.join('、')}）`).join('；')
        : '相关性待确认：由检索词召回，简介中的领域线索不足，仍保留供你查看。';
      const uses = document.createElement('p');
      uses.className = 'dataset-description';
      uses.textContent = dataset.directions.length
        ? '可能用途（按公开简介推测）：' + dataset.directions.map(d => d.use).join('；') + '。具体是否支持，需要核对数据字段。'
        : '可能用途：公开信息不足，请打开数据卡判断。';
      const provenance = document.createElement('p');
      provenance.className = 'dataset-description';
      provenance.textContent = '来源：Hugging Face · 检索词：' + dataset.retrievalTerms.join('、') + '。真人/合成、稳定个体 ID、时间字段：尚未核验，不作为排除条件。';
      card.append(title, description, relevance, uses, meta, provenance, links);
      results.append(card);
    }
  }

  async function fetchTerm(term, signal) {
    const cached = cache.get(term.toLowerCase());
    if (cached && Date.now() - cached.time < 10 * 60 * 1000) return cached.data;
    if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal.addEventListener('abort', cancel, {once: true});
    const timeout = setTimeout(cancel, 15000);
    try {
      const params = new URLSearchParams({search: term, limit: '30', full: 'true', sort: 'downloads', direction: '-1'});
      const response = await fetch('https://huggingface.co/api/datasets?' + params, {signal: controller.signal});
      if (response.status === 429) {
        cooldownUntil = Date.now() + 60000;
        throw new Error('服务限流，已暂停后续查询；一分钟后可重试。');
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error('返回格式异常');
      cache.set(term.toLowerCase(), {data, time: Date.now()});
      return data;
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener('abort', cancel);
    }
  }

  async function search() {
    const query = input.value.trim();
    if (!query) { input.focus(); return; }
    activeRequest?.abort();
    const id = ++requestId;
    activeRequest = new AbortController();
    const signal = activeRequest.signal;
    button.disabled = false; // A new query can replace an in-flight search.
    if (Date.now() < cooldownUntil) {
      status.textContent = '搜索服务限流中，请一分钟后重试；已有结果保留。';
      results.setAttribute('aria-busy', 'false');
      return;
    }
    const terms = discovery.plan(query);
    updateLinks(terms[0]);
    results.replaceChildren();
    results.setAttribute('aria-busy', 'true');
    const rows = [], failures = [];
    let completed = 0;
    let ranked = [];
    try {
      for (const term of terms) {
        if (signal.aborted) return;
        status.textContent = `正在查找“${query}”：${completed}/${terms.length} 个检索词，当前“${term}”；已找到 ${ranked.length} 条候选。`;
        try {
          const data = await fetchTerm(term, signal);
          if (id !== requestId) return;
          rows.push(...data.map(row => ({...row, retrievalTerms: [term]})));
        } catch (error) {
          if (id !== requestId) return;
          failures.push(term + '：' + (error.name === 'AbortError' ? '请求超时' : error.message));
        }
        completed++;
        ranked = discovery.rank(rows, query);
        render(ranked);
        if (Date.now() < cooldownUntil) break;
        // Serial calls with spacing; cache repeated terms between topic searches.
        if (completed < terms.length) await new Promise(resolve => setTimeout(resolve, 400));
      }
      if (id !== requestId) return;
      const incomplete = failures.length || completed < terms.length;
      status.textContent = `“${query}”：${ranked.length} 条去重候选，按相关线索排序；已查询 ${completed}/${terms.length} 个词。` +
        (incomplete ? ' 部分检索未完成，当前结果不完整：' + failures.join('；') : ' 不设分数门槛，弱匹配也保留。') +
        (!ranked.length && !incomplete ? ' 可换用具体数据集名，或打开其他来源继续检索。' : '');
    } finally {
      if (id === requestId) results.setAttribute('aria-busy', 'false');
    }
  }

  form.addEventListener('submit', event => { event.preventDefault(); search(); });
  document.querySelectorAll('[data-query]').forEach(chip => chip.addEventListener('click', () => {
    input.value = chip.dataset.query;
    search();
  }));
  search();
})();
