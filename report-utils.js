const ReportUtils = (() => {
  const inWindow = (value, scope) => !!value && Number.isFinite(Date.parse(value)) && Date.parse(value) >= Date.parse(scope.start) && Date.parse(value) <= Date.parse(scope.end);
  function beijingTime(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return '未核实';
    return new Date(Date.parse(value) + 8 * 3600000).toISOString().slice(0,19).replace('T',' ');
  }
  function selectEvents(view, current, history, saved) {
    if (view === 'today') return current;
    if (view === 'archive') return history;
    const all = [...new Map([...history,...current].map(e => [e.id,e])).values()];
    return view === 'saved' ? all.filter(e => saved.has(e.id)) : all;
  }
  return {inWindow,beijingTime,selectEvents};
})();
if (typeof module !== 'undefined') module.exports = ReportUtils;
