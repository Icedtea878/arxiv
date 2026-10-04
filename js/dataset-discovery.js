/* Broad retrieval and transparent metadata ranking; no eligibility threshold. */
(function (root) {
  'use strict';
  const scopes = {
    individual: {label: '个体', aliases: ['个体', '人格', '用户', 'individual', 'human simulation', 'user simulation', 'persona', 'personality'],
      queries: ['persona', 'personality', 'user', 'emotion', 'human behavior'],
      terms: ['persona', 'personality', 'big five', 'big5', 'user', 'preference', 'emotion', 'human behavior', 'human behaviour', 'mental state', 'cognitive', 'experience sampling'],
      use: '探索个体画像、偏好、情绪或行为建模'},
    interaction: {label: '交互', aliases: ['交互', '对话', 'interaction', 'dialogue', 'negotiation', 'human interaction'],
      queries: ['dialogue', 'conversation', 'negotiation', 'sotopia', 'theory-of-mind'],
      terms: ['dialogue', 'dialog', 'conversation', 'negotiation', 'interaction', 'sotopia', 'theory of mind', 'real talk', 'realtalk'],
      use: '探索对话行为、意图理解、关系或交互策略'},
    group: {label: '群体', aliases: ['群体', '群体模拟', 'group', 'group simulation', 'collective', 'cooperation'],
      queries: ['cooperation', 'multi-agent', 'group', 'collective', 'crowd'],
      terms: ['cooperation', 'cooperative', 'multi agent', 'team', 'group', 'collective', 'crowd', 'coordination', 'prisoner', 'game theory'],
      use: '探索多人协作、博弈、群体决策或集体行为'},
    society: {label: '社会', aliases: ['社会', '社会模拟', 'society', 'social', 'social simulation', 'social network'],
      queries: ['social', 'opinion', 'social-network', 'social-norm', 'community'],
      terms: ['social', 'society', 'opinion', 'community', 'social network', 'social norm', 'diffusion', 'propagation'],
      use: '探索社会关系、观点、规范或传播过程'}
  };
  const tracked = ['HUMANUAL', 'PersonaConvBench', 'REALTALK', 'Twin-2K-500', 'OPeRA', 'Persona-E2', 'BIG5-CHAT', 'CoSER', 'Psych-101', 'PersonaMem', 'openESM', 'Smartphone Sensing Panel Study'];
  const normalize = value => String(value || '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const has = (text, term) => (' ' + normalize(text) + ' ').includes(' ' + normalize(term) + ' ');

  function plan(query) {
    const normalized = normalize(query);
    if (['相关数据', '全部方向', 'all', 'social world model'].includes(normalized)) {
      // Round-robin across all four scopes so every scope is represented early.
      return [0, 1, 2].flatMap(i => Object.values(scopes).map(s => s.queries[i]));
    }
    if (['已有数据集', '追踪数据集', 'tracked'].includes(normalized)) return [...tracked];
    const scope = Object.values(scopes).find(s => s.aliases.some(a => normalize(a) === normalized));
    if (scope) return [...new Set([...( /[\u3400-\u9fff]/.test(query) ? [] : [query]), ...scope.queries])];
    const name = tracked.find(n => normalize(n).replaceAll(' ', '') === normalized.replaceAll(' ', ''));
    if (name) return [...new Set([name, name.replace(/[-²]/g, c => c === '²' ? '2' : ' '), ...(name === 'Persona-E2' ? ['Persona-E'] : [])])];
    return [query];
  }

  function rank(rows, query) {
    const merged = new Map();
    for (const row of rows) {
      if (typeof row.id !== 'string' || !/^[\w./-]+$/.test(row.id)) continue;
      const old = merged.get(row.id);
      merged.set(row.id, {...old, ...row, retrievalTerms: [...new Set([...(old?.retrievalTerms || []), ...(row.retrievalTerms || [])])]});
    }
    return [...merged.values()].map(row => {
      const text = [row.description || '', ...(row.tags || [])].join(' ');
      const directions = Object.entries(scopes).map(([key, scope]) => {
        const matches = scope.terms.filter(term => has(row.id, term) || has(text, term));
        return {key, label: scope.label, use: scope.use, matches};
      }).filter(scope => scope.matches.length);
      // Prefer direct name matches, then explicit topic evidence; popularity only breaks ties.
      const score = (has(row.id, query) ? 12 : 0) + directions.reduce((total, scope) => total + scope.matches.reduce((n, term) => n + (has(row.id, term) ? 3 : 1), 0), 0);
      return {...row, directions, matchScore: score};
    }).sort((a, b) => b.matchScore - a.matchScore || (b.downloads || 0) - (a.downloads || 0) || a.id.localeCompare(b.id));
  }
  const api = {scopes, tracked, plan, rank};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DatasetDiscovery = api;
})(globalThis);
