const test = require('node:test');
const assert = require('node:assert/strict');
const RadarData = require('../data-ui.js');
const CaseUI = require('../case-ui.js');

const row = {
  id: '0123456789abcdef0123', lane: 'news',
  publishedAt: '2026-09-14T00:00:00Z', url: 'https://example.com/news',
  title: 'English title', titleZh: '中文标题',
  summary: 'English summary', summaryZh: '中文摘要',
  background: '背景', difference: '变化', meaning: '判断', industryImpact: '行业影响',
  tripoImpact: 'Tripo 影响', method: '方法', videoIdea: '视频建议', postIdea: '图文建议',
  author: '作者', sourceName: '来源', category: 'AI 3D', verificationNote: '核对说明',
  evidence: [{quote: 'English source text', locator: '原文段落', url: 'https://example.com/news'}]
};

test('pending queue is visible without publishing placeholder cards', () => {
  const report = {version:1, checkedAt:'2026-09-18T01:00:00Z', news:[], cases:[], checks:[], pending:[{id:'queued'}]};
  const result = RadarData.merge(report, [], [], '2026-09-18T02:00:00Z');
  assert.equal(result.pendingCount, 1);
  assert.equal(result.events.length, 0);
});

test('event display prefers Chinese title and summary fields', () => {
  const report = {version: 1, checkedAt: '2026-09-14T01:00:00Z', news: [row], cases: [], checks: []};
  const result = RadarData.merge(report, [], [], '2026-09-14T02:00:00Z');
  assert.equal(result.events[0].title, '中文标题');
  assert.equal(result.events[0].summary, '中文摘要');
});

test('English-only source text does not leak into the card when Chinese fields are absent', () => {
  const english = {...row, titleZh: '', summaryZh: ''};
  const report = {version: 1, checkedAt: '2026-09-14T01:00:00Z', news: [english], cases: [], checks: []};
  const result = RadarData.merge(report, [], [], '2026-09-14T02:00:00Z');
  assert.equal(result.events.length, 0);
  assert.equal(result.pendingCount, 1);
});

test('known live records have a Chinese card translation', () => {
  const live = {...row, id: 'a7c1e5fcf9af05021743', titleZh: '', summaryZh: ''};
  const report = {version: 1, checkedAt: '2026-09-14T01:00:00Z', news: [live], cases: [], checks: []};
  const result = RadarData.merge(report, [], [], '2026-09-14T02:00:00Z');
  assert.match(result.events[0].title, /毫米波雷达/);
  assert.match(result.events[0].summary, /新视角合成/);
});

test('old news stays in the archive and never becomes a current feature', () => {
  const report = {version:1, checkedAt:'2026-09-18T01:00:00Z', news:[row], cases:[], checks:[]};
  const result = RadarData.merge(report, [{id:'old', status:'升温', sources:[]}], [], '2026-09-18T02:00:00Z');
  assert.deepEqual(result.todayIds, []);
  assert.equal(result.events[0].status, '近7天发布');
  assert.equal(result.events[1].status, '历史参考');
});

test('source news remains visible without AI and escapes source HTML', () => {
  const brief = {...row, firstSeenAt:'2026-09-14T01:00:00Z', contentStatus:'source_only',
    title:'<img src=x onerror=alert(1)>', excerpt:'Original & attributed excerpt'};
  delete brief.titleZh; delete brief.summaryZh;
  const report = {version:1, checkedAt:'2026-09-14T01:00:00Z', news:[], cases:[], checks:[], sourceNews:[brief], pending:[{id:row.id}]};
  const result = RadarData.merge(report, [], [], '2026-09-14T02:00:00Z');
  assert.equal(result.events.length, 1);
  assert.equal(result.events[0].type, '来源快讯 · 原文');
  assert.ok(!result.events[0].title.includes('<img'));
  assert.deepEqual(result.todayIds,[row.id]);
  assert.equal(result.pendingCount,1);
  const later=RadarData.merge(report, [], [], '2026-09-16T02:00:00Z');
  assert.deepEqual(later.todayIds,[]);
  assert.deepEqual(later.recentIds,[row.id]);
  assert.equal(later.stale,true);
});

test('AI and source versions share one card', () => {
  const report={version:1, checkedAt:'2026-09-14T01:00:00Z', news:[row], cases:[], checks:[],
    sourceNews:[{...row,firstSeenAt:'2026-09-14T01:00:00Z',excerpt:'Original excerpt'}]};
  assert.equal(RadarData.merge(report, [], [], '2026-09-14T02:00:00Z').events.length,1);
});

test('fresh news expires after 24 hours even if the report is unchanged', () => {
  const report = {version:1, checkedAt:'2026-09-14T01:00:00Z', news:[row], cases:[], checks:[]};
  assert.deepEqual(RadarData.merge(report, [], [], '2026-09-14T02:00:00Z').todayIds, [row.id]);
  assert.deepEqual(RadarData.merge(report, [], [], '2026-09-15T02:00:00Z').todayIds, []);
});

test('case card shows analysis once and hides unsupported placeholder advice', () => {
  const item = {...row, lane:'cases', checkedAt:'2026-09-14T01:00:00Z', meaning:'编辑分析：编辑分析：建议逐层展示制作过程。'};
  const report = {version:1, checkedAt:item.checkedAt, news:[], cases:[item], checks:[]};
  const card = CaseUI.caseCard(RadarData.merge(report, [], []).cases[0]);
  assert.equal(card.split('建议逐层展示制作过程。').length-1, 1);
  assert.ok(!card.includes('编辑分析：编辑分析：'));
  item.meaning='编辑分析：编辑分析：原始资料不足，暂不下结论。';
  assert.ok(!CaseUI.caseCard(RadarData.merge(report, [], []).cases[0]).includes('可以借鉴'));
});
