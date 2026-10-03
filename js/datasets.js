(() => {
  'use strict';
  const form = document.getElementById('datasetSearch');
  const input = document.getElementById('datasetQuery');
  const button = document.getElementById('searchButton');
  const status = document.getElementById('datasetStatus');
  const results = document.getElementById('datasetResults');
  const cache = new Map();
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
      card.append(title, description, meta, links);
      results.append(card);
    }
  }

  async function search() {
    const query = input.value.trim();
    if (!query) { input.focus(); return; }
    updateLinks(query);
    activeRequest?.abort();
    const id = ++requestId;
    const cached = cache.get(query.toLowerCase());
    if (cached && Date.now() - cached.time < 10 * 60 * 1000) {
      render(cached.data);
      status.textContent = `“${query}”：${cached.data.length} 条结果（最近搜索缓存）。`;
      results.setAttribute('aria-busy', 'false');
      button.disabled = false;
      return;
    }
    if (Date.now() < cooldownUntil) {
      status.textContent = '搜索服务限流中，请一分钟后重试，或使用上方的外部检索入口。';
      results.setAttribute('aria-busy', 'false');
      button.disabled = false;
      return;
    }
    activeRequest = new AbortController();
    const controller = activeRequest;
    const timeout = setTimeout(() => controller.abort(), 20000);
    button.disabled = true;
    results.replaceChildren();
    results.setAttribute('aria-busy', 'true');
    status.textContent = `正在查找“${query}”…`;
    try {
      const params = new URLSearchParams({search: query, limit: '30', full: 'true', sort: 'downloads', direction: '-1'});
      const response = await fetch('https://huggingface.co/api/datasets?' + params, {signal: controller.signal});
      if (response.status === 429) {
        cooldownUntil = Date.now() + 60000;
        throw new Error('搜索服务暂时限流，请一分钟后重试。');
      }
      if (!response.ok) throw new Error(`搜索服务返回 HTTP ${response.status}。`);
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error('搜索服务返回的数据格式异常。');
      if (id !== requestId) return;
      cache.set(query.toLowerCase(), {data, time: Date.now()});
      render(data);
      status.textContent = data.length ? `“${query}”：显示 ${data.length} 条结果，按下载量排列。` : `没有找到“${query}”。试试更短的英文关键词，或使用上方的其他检索入口。`;
    } catch (error) {
      if (id !== requestId) return;
      status.textContent = error.name === 'AbortError' ? '请求超时，请重试或打开上方的外部检索入口。' : error.message + ' 可使用上方的外部检索入口继续查找。';
    } finally {
      clearTimeout(timeout);
      if (id === requestId) {
        button.disabled = false;
        results.setAttribute('aria-busy', 'false');
      }
    }
  }

  form.addEventListener('submit', event => { event.preventDefault(); search(); });
  document.querySelectorAll('[data-query]').forEach(chip => chip.addEventListener('click', () => {
    input.value = chip.dataset.query;
    search();
  }));
  search();
})();
