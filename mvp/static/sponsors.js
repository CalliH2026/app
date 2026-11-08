/* Explicit provider attribution. Logos stay local and never rewrite source text. */
(() => {
  const sponsors = Object.freeze({
    hcompany: {name: 'H Company', src: '/static/h-kit/h-logo-black.svg'},
    gladia: {name: 'Gladia', src: '/static/sponsors/gladia.svg'},
    linkup: {name: 'Linkup', src: '/static/sponsors/linkup.svg'},
    devin: {name: 'Devin', src: '/static/sponsors/devin.svg'},
    stripe: {name: 'Stripe', src: '/static/sponsors/stripe.svg'},
    gmail: {name: 'Gmail', src: '/static/integrations/gmail.svg'},
    google_docs: {name: 'Google Docs', src: '/static/integrations/google-docs.svg'},
    google_calendar: {name: 'Google Calendar', src: '/static/integrations/google-calendar.svg'},
  });
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));

  window.sponsorBrand = (id, {label, iconOnly = false} = {}) => {
    const sponsor = Object.hasOwn(sponsors, id) ? sponsors[id] : null;
    if (!sponsor) return '';
    const name = escape(label ?? sponsor.name);
    return `<span class="sponsor-brand sponsor-${id}${iconOnly ? ' sponsor-icon-only' : ''}"${iconOnly ? ` role="img" aria-label="${name}"` : ''}><img class="sponsor-logo" src="${sponsor.src}" width="20" height="20" alt="" aria-hidden="true">${iconOnly ? '' : `<span class="sponsor-name">${name}</span>`}</span>`;
  };

  // Static page attribution uses the same markup as dynamically rendered panels.
  document.querySelectorAll('[data-sponsor]').forEach(element => {
    element.innerHTML = window.sponsorBrand(element.dataset.sponsor, {
      label: element.dataset.sponsorLabel,
    });
  });
})();
