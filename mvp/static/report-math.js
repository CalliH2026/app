/* Display mathematics without rewriting stored reports or interpreting surrounding prose. */
(() => {
  'use strict';
  const atom = '(?:[A-Z]{1,3}(?:[²³])?|[0-9]+(?:[.,][0-9]+)?(?:[²³])?)';
  const equation = `(?<![\\p{L}0-9])${atom}(?:\\s*[=+−×÷-]\\s*${atom})+(?:\\s+(?:cm|mm|m)(?:[²³])?)?(?![\\p{L}0-9])`;
  function segments(value) {
    const input = String(value || ''), parts = []; let cursor = 0;
    const pattern = new RegExp(String.raw`\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|` + equation, 'gu');
    for (const match of input.matchAll(pattern)) {
      const raw = match[0], delimited = raw.startsWith('\\(') || raw.startsWith('\\[') || raw.startsWith('$$');
      if (!delimited && !raw.includes('=')) continue;
      if (match.index > cursor) parts.push({text: input.slice(cursor, match.index)});
      let tex = delimited ? raw.slice(2, -2) : raw.replace(/²/g, '^2').replace(/³/g, '^3').replace(/×/g, '\\times ').replace(/÷/g, '\\div ').replace(/−/g, '-').replace(/\b(cm|mm|m)\b/g, '\\,\\mathrm{$1}');
      if (tex.length > 1000) parts.push({text: raw});
      else parts.push({text: raw, tex, display: raw.startsWith('\\[') || raw.startsWith('$$')});
      cursor = match.index + raw.length;
    }
    if (cursor < input.length) parts.push({text: input.slice(cursor)});
    return parts;
  }
  window.calliMathSegments = segments;
  window.renderReportMath = root => {
    if (!window.katex || !root) return;
    const blocks = root.querySelectorAll('.report-summary, .report-summary-full, .report-part p, .report-part blockquote');
    for (const block of blocks) {
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT), nodes = [];
      while (walker.nextNode()) if (!walker.currentNode.parentElement?.closest('.calli-math, .katex, pre, code, button, a, textarea, .activity')) nodes.push(walker.currentNode);
      for (const node of nodes) {
        const chunks = segments(node.nodeValue);
        if (!chunks.some(chunk => chunk.tex)) continue;
        const fragment = document.createDocumentFragment();
        for (const chunk of chunks) {
          if (!chunk.tex) { fragment.append(document.createTextNode(chunk.text)); continue; }
          const span = document.createElement('span'); span.className = 'calli-math';
          try { window.katex.render(chunk.tex, span, {displayMode: chunk.display, output: 'htmlAndMathml', trust: false, strict: 'error', throwOnError: true, maxExpand: 100, maxSize: 10}); }
          catch { span.textContent = chunk.text; }
          fragment.append(span);
        }
        node.replaceWith(fragment);
      }
    }
  };
})();
