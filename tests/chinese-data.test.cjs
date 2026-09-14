const test = require('node:test');
const assert = require('node:assert/strict');
const RadarData = require('../data-ui.js');

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
  assert.equal(result.events[0].title, '暂无中文标题');
  assert.equal(result.events[0].summary, '暂无中文整理');
});

test('known live records have a Chinese card translation', () => {
  const live = {...row, id: 'a7c1e5fcf9af05021743', titleZh: '', summaryZh: ''};
  const report = {version: 1, checkedAt: '2026-09-14T01:00:00Z', news: [live], cases: [], checks: []};
  const result = RadarData.merge(report, [], [], '2026-09-14T02:00:00Z');
  assert.match(result.events[0].title, /毫米波雷达/);
  assert.match(result.events[0].summary, /新视角合成/);
});
