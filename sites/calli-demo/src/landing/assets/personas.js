// Accessible, isolated role tabs. All content is server-rendered.
document.querySelectorAll('.persona-tabs').forEach(list => {
  const tabs = [...list.querySelectorAll('[role="tab"]')];
  const select = tab => tabs.forEach(item => {
    const active = item === tab;
    item.setAttribute('aria-selected', String(active));
    item.tabIndex = active ? 0 : -1;
    document.getElementById(item.getAttribute('aria-controls')).hidden = !active;
  });
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', event => {
      const next = {ArrowRight:(index+1)%tabs.length,ArrowLeft:(index+tabs.length-1)%tabs.length,Home:0,End:tabs.length-1}[event.key];
      if (next === undefined) return;
      event.preventDefault(); select(tabs[next]); tabs[next].focus();
    });
  });
});
