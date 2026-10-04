const test = require('node:test');
const assert = require('node:assert/strict');
const discovery = require('../js/dataset-discovery.js');

test('broad search covers all four scopes and Chinese topics expand', () => {
  const terms = discovery.plan('相关数据');
  for (const scope of Object.values(discovery.scopes)) assert.ok(scope.queries.some(q => terms.includes(q)));
  assert.equal(new Set(terms).size, terms.length);
  assert.ok(discovery.plan('群体').includes('cooperation'));
  assert.ok(discovery.plan('个体').includes('personality'));
  assert.ok(discovery.plan('Persona E²').includes('Persona-E2'));
});

test('all candidates survive regardless of missing fields or synthetic origin', () => {
  const rows = [
    {id:'test/unknown', retrievalTerms:['social']},
    {id:'test/synthetic-dialogue', description:'Synthetic conversations', retrievalTerms:['dialogue']},
    {id:'test/social', description:'Social network and opinion diffusion', retrievalTerms:['social']}
  ];
  const ranked = discovery.rank(rows, '相关数据');
  assert.equal(ranked.length, 3);
  assert.equal(ranked.find(x => x.id === 'test/unknown').directions.length, 0);
  assert.ok(ranked.find(x => x.id === 'test/synthetic-dialogue').directions.some(d => d.key === 'interaction'));
});

test('deduplicates with provenance and prioritizes evidence before downloads', () => {
  const ranked = discovery.rank([
    {id:'test/irrelevant', downloads:100000, retrievalTerms:['social']},
    {id:'test/persona', description:'User preference and personality', downloads:1, retrievalTerms:['persona']},
    {id:'test/persona', description:'User preference and personality', downloads:1, retrievalTerms:['user']}
  ], '个体');
  assert.equal(ranked.length,2);
  assert.equal(ranked[0].id,'test/persona');
  assert.deepEqual(ranked[0].retrievalTerms,['persona','user']);
});
