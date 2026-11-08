/* Same-origin aggregate counts; one count per event per document load. No identity or storage. */
(() => {
  if (window.self !== window.top || navigator.webdriver || navigator.doNotTrack === '1' || navigator.globalPrivacyControl === true) return;
  const seen = new Set();
  const emit = event => {
    if (seen.has(event)) return;
    seen.add(event);
    fetch('/metrics/event', {method: 'POST', credentials: 'omit', keepalive: true,
      headers: {'content-type': 'application/json'}, body: JSON.stringify({event})}).catch(() => {});
  };
  const route = location.pathname;
  if (route === '/' || route === '/fr') emit('landing');
  else if (route === '/app' || route === '/workspace') emit('workspace');
  else if (route === '/guide') emit('guide');
  document.addEventListener('click', e => {
    const node = e.target.closest?.('button, a');
    if (!node) return;
    const page = node.dataset.page;
    if (page === 'family') emit('parent');
    else if (page === 'outings') emit('outing');
    else if (page === 'students' || page === 'appreciations' || page === 'calli') emit('teacher');
    if (node.dataset.practiceAction === 'preview' || node.dataset.practiceAction === 'review') emit('practice');
    if (node.href?.startsWith('https://youtu.be/')) emit('video');
  });
})();
