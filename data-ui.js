const RadarData=(()=>{
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const url=value=>{const u=new URL(value);if(u.protocol!=='https:'||u.username||u.password)throw Error('Invalid source URL');return u.href;};
 const dateLabel=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value))+'（北京时间）';
 const fields={title:'标题',summary:'发生了什么',background:'背景',change:'前后变化',method:'作者方法'};
 const translations={
  'a7c1e5fcf9af05021743':{title:'毫米波雷达的 3D 点溅射新视角合成',summary:'研究提出面向毫米波雷达的新视角合成方法，同时保留物理真实性、复数输出和多视角优化能力。'},
  'cca8d225a3520ac4af7c':{title:'Godot 4.8 开发快照 5 发布',summary:'Godot 4.8 进入功能冻结前的最后阶段，开发者正在集中完成新功能，社区期待已久的改进陆续合入。'},
  '143d0040a196fe573687':{title:'用 Spyderfy 插件在 After Effects 和 Blender 中添加生物群',summary:'作者演示如何用程序化群体系统快速加入蝗虫、蜻蜓、蜘蛛等生物群，减少逐个制作和动画的工作量。'},
  'd715db7f0a63dd8cc312':{title:'Spyderfy 插件：几秒钟为 After Effects 加入 3D 生物群',summary:'这个插件把群体和爬行动物系统直接放进 After Effects，可调节数量、速度、间距、比例和运动行为。'},
  '01d63ccc33cabb2672bb':{title:'一个 After Effects 项目用了 209 个图层',summary:'作者把赛博朋克城市拆成独立图层，分别处理遮罩、颜色、镜头和细节，展示复杂场景如何逐层搭建。'},
  '900574c44e3c0d76c9b5':{title:'Spyderfy 新插件发布：让生物群动画不再繁琐',summary:'作者公开展示用于爬行、群体和背景运动的程序化系统，并说明该插件现已支持 After Effects 与 Blender 3D。'}
 };
 const chinese=(value,fallback)=>typeof value==='string'&&/[\u3400-\u9fff]/.test(value)?value:fallback;
 const title=r=>translations[r.id]?.title||chinese(r.titleZh||r.title,'暂无中文标题');
 const summary=r=>translations[r.id]?.summary||chinese(r.summaryZh||r.summary,'暂无中文整理');
 const ready=r=>!title(r).startsWith('暂无中文')&&!summary(r).startsWith('暂无中文');
 const analysis=value=>chinese(value,'').replace(/^(?:(?:编辑分析|编辑建议)[：:]\s*)+/,'').trim();
 const useful=value=>{const s=analysis(value);return /原始资料不足|暂不下结论|尚未核实|需要进一步核对/.test(s)?'':s;};
 function checkRow(r,lane,cutoff){
  if(!r||r.lane!==lane||!/^[a-f0-9]{20}$/.test(r.id)||!Number.isFinite(Date.parse(r.publishedAt))||Date.parse(r.publishedAt)>cutoff)throw Error('Invalid source record');
  url(r.url);
  for(const key of ['title','summary','background','difference','meaning','industryImpact','tripoImpact','method','videoIdea','postIdea','author','sourceName','category','verificationNote'])if(typeof r[key]!=='string')throw Error('Missing source field');
  if(!Array.isArray(r.evidence)||!r.evidence.length||r.evidence.some(e=>typeof e.quote!=='string'||typeof e.locator!=='string'||e.url!==r.url))throw Error('Invalid evidence');
 }
 function event(r){return {...r,title:title(r),summary:summary(r),date:dateLabel(r.publishedAt),status:'来源更新',type:r.category==='学术研究'?'研究动态':'来源动态',tags:[r.category],signal:r.verificationNote,
  sources:[[r.sourceName,url(r.url)]],evidence:r.evidence.map(e=>[(fields[e.field]||'资料')+' · 原文引文',e.quote+'\n'+e.locator]),live:true};}
 function social(r){
  const host=new URL(r.url).hostname;
  const platform=host.endsWith('youtube.com')?'YouTube':host.endsWith('instagram.com')?'Instagram':host.endsWith('behance.net')?'Behance':host;
  return {id:r.id,url:url(r.url),title:title(r),author:r.author,platform,format:r.url.includes('/shorts/')?'短视频':'作品 / 演示',use:r.category,
   desc:summary(r),combination:r.category,method:r.method,tools:'仅以作者方法中的明确披露为准；未推断工具链。',unknown:r.verificationNote+' 未观看视频，未复现方法。',
   hook:useful(r.meaning),videoIdea:useful(r.videoIdea),postIdea:useful(r.postIdea),adaptation:useful(r.meaning),nature:'作者公开内容 · AI辅助整理',publishedLabel:dateLabel(r.publishedAt),
   collectedAt:dateLabel(r.checkedAt),checkedAt:r.checkedAt,checkLabel:'订阅说明已核对，视觉待核实',image:null,chapters:[],
   evidence:r.evidence.map(e=>e.quote+'（'+e.locator+'）').join('\n')};
 }
 function merge(report,historical,curated,now=new Date().toISOString()){
  const cutoff=Date.parse(report?.checkedAt),current=Date.parse(now);
  if(report?.version!==1||!Number.isFinite(cutoff)||!Number.isFinite(current)||!Array.isArray(report.news)||!Array.isArray(report.cases)||!Array.isArray(report.checks))throw Error('Invalid report');
  const ids=new Set();
  for(const [items,lane] of [[report.news,'news'],[report.cases,'cases']])for(const r of items){checkRow(r,lane,cutoff);if(ids.has(r.id))throw Error('Duplicate ID');ids.add(r.id);}
  const pendingCount=[...report.news,...report.cases].filter(r=>!ready(r)).length;
  const generated=report.news.filter(ready).map(event),known=new Set(generated.map(e=>e.url)),caseUrls=new Set(curated.map(c=>c.url));
  const events=[...generated,...historical.filter(e=>!(e.sources||[]).some(([,u])=>known.has(u))).map(e=>({...e,status:'历史参考'}))];
  const cases=[...report.cases.filter(r=>ready(r)&&!caseUrls.has(r.url)).map(social),...curated];
  const todayIds=generated.filter(e=>Date.parse(e.publishedAt)>current-86400000&&Date.parse(e.publishedAt)<=Math.min(current,cutoff)).map(e=>e.id);
  for(const e of generated)e.status=todayIds.includes(e.id)?'近24小时发布':'历史保留';
  return {events,cases,todayIds,pendingCount,checkedAt:report.checkedAt,checks:report.checks,trialOnly:report.trialOnly===true};
 }
 return {merge,escape,dateLabel};
})();
if(typeof module!=='undefined')module.exports=RadarData;
