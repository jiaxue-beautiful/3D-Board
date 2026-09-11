const RadarData=(()=>{
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const url=value=>{const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password)throw Error('Invalid source URL');return u.href;};
 const dateLabel=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value))+'（北京时间）';
 const fields={title:'标题',summary:'发生了什么',background:'背景',change:'前后变化',method:'作者方法'};
 function checkRow(r,lane,cutoff){
  if(!r||r.lane!==lane||!/^[a-f0-9]{20}$/.test(r.id)||!Number.isFinite(Date.parse(r.publishedAt))||Date.parse(r.publishedAt)>cutoff)throw Error('Invalid source record');
  url(r.url);
  for(const key of ['title','summary','background','difference','meaning','industryImpact','tripoImpact','method','videoIdea','postIdea','author','sourceName','category','verificationNote'])if(typeof r[key]!=='string')throw Error('Missing source field');
  if(!Array.isArray(r.evidence)||!r.evidence.length||r.evidence.some(e=>typeof e.quote!=='string'||typeof e.locator!=='string'||e.url!==r.url))throw Error('Invalid evidence');
 }
 function event(r){return {...r,date:dateLabel(r.publishedAt),status:'来源更新',type:r.category==='学术研究'?'研究动态':'来源动态',tags:[r.category],signal:r.verificationNote,
  sources:[[r.sourceName,url(r.url)]],evidence:r.evidence.map(e=>[(fields[e.field]||'资料')+' · 原文引文',e.quote+'\n'+e.locator]),live:true};}
 function social(r){
  const host=new URL(r.url).hostname;
  const platform=host.endsWith('youtube.com')?'YouTube':host.endsWith('instagram.com')?'Instagram':host.endsWith('behance.net')?'Behance':host;
  return {id:r.id,url:url(r.url),title:r.title,author:r.author,platform,format:r.url.includes('/shorts/')?'短视频':'作品 / 演示',use:r.category,
   desc:r.summary,combination:r.meaning,method:r.method,tools:'仅以作者方法中的明确披露为准；未推断工具链。',unknown:r.verificationNote+' 未观看视频，未复现方法。',
   hook:r.meaning,videoIdea:r.videoIdea,postIdea:r.postIdea,adaptation:r.meaning,nature:'作者公开内容 · AI辅助整理',publishedLabel:dateLabel(r.publishedAt),
   collectedAt:dateLabel(r.checkedAt),checkedAt:r.checkedAt,checkLabel:'订阅说明已核对，视觉待核实',image:null,chapters:[],
   evidence:r.evidence.map(e=>e.quote+'（'+e.locator+'）').join('\n')};
 }
 function merge(report,historical,curated,now=new Date().toISOString()){
  const cutoff=Date.parse(report?.checkedAt),current=Date.parse(now);
  if(report?.version!==1||!Number.isFinite(cutoff)||!Number.isFinite(current)||!Array.isArray(report.news)||!Array.isArray(report.cases)||!Array.isArray(report.checks))throw Error('Invalid report');
  const ids=new Set();
  for(const [items,lane] of [[report.news,'news'],[report.cases,'cases']])for(const r of items){checkRow(r,lane,cutoff);if(ids.has(r.id))throw Error('Duplicate ID');ids.add(r.id);}
  const generated=report.news.map(event),known=new Set(generated.map(e=>e.url)),caseUrls=new Set(curated.map(c=>c.url));
  const events=[...generated,...historical.filter(e=>!(e.sources||[]).some(([,u])=>known.has(u)))];
  const cases=[...report.cases.filter(r=>!caseUrls.has(r.url)).map(social),...curated];
  const todayIds=generated.filter(e=>Date.parse(e.publishedAt)>current-86400000&&Date.parse(e.publishedAt)<=Math.min(current,cutoff)).map(e=>e.id);
  return {events,cases,todayIds,checkedAt:report.checkedAt,checks:report.checks,trialOnly:report.trialOnly===true};
 }
 return {merge,escape,dateLabel};
})();
if(typeof module!=='undefined')module.exports=RadarData;
