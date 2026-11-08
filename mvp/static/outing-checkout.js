/* Configurable Checkout is separate from the saved/simulated operations panel. */
(() => {
  const text = (tag, value, className) => {
    const element = document.createElement(tag); element.textContent = value;
    if (className) element.className = className; return element;
  };
  async function request(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const value = await response.json();
    if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Checkout indisponible.');
    return value;
  }
  async function render(panel) {
    const output = panel.querySelector('[data-checkout-content]');
    const job = panel.dataset.checkoutJob;
    output.replaceChildren(text('p', 'Chargement du statut Stripe…'));
    try {
      const data = await request('/api/outings/'+encodeURIComponent(job)+'/checkout');
      if (!panel.isConnected) return;
      output.replaceChildren(text('p', data.message, 'outing-ops-explain'));
      if (!data.enabled) {
        const button=text('button','Stripe à configurer','button');button.disabled=true;output.append(button);return;
      }
      output.append(text('p','Environnement de test Stripe · aucun fonds réel.', 'checkout-mode'));
      const refresh=text('button','Actualiser les règlements','button');refresh.type='button';refresh.onclick=()=>render(panel);output.append(refresh);
      if (!data.families.length) output.append(text('p','Préparez les messages aux familles pour retrouver les contributions.'));
      data.families.forEach(family => {
        const entry=data.entries.find(e=>e.family_id===family.id);
        const row=text('div','', 'checkout-family'); row.append(text('strong',family.label));
        const label={paid:'Réglé · test confirmé',pending:'En attente',failed:'Échec · à vérifier',expired:'Session expirée'};
        const status=text('span',family.response==='declined'?'Sortie refusée':label[entry?.status]||'À préparer');row.append(status);
        if (entry?.amount_minor) row.append(text('span',new Intl.NumberFormat('fr-FR',{style:'currency',currency:'EUR'}).format(entry.amount_minor/100)));
        if (family.response!=='declined' && entry?.status!=='paid') {
          const button=text('button',entry?.url?'Ouvrir Checkout':'Préparer le lien Stripe','button');button.type='button';
          button.onclick=async()=>{
            button.disabled=true;
            try {
              const payment=await request('/api/outings/'+encodeURIComponent(job)+'/checkout',{family_id:family.id});
              if(!panel.isConnected) return;
              if(payment.status==='paid'){await render(panel);return;}
              // Use a visible link, avoiding popup blocking and automatic navigation.
              const url=new URL(payment.url);
              if(url.protocol!=='https:'||url.host!=='checkout.stripe.com')throw new Error('Lien Stripe indisponible.');
              const link=text('a','Continuer sur Stripe ↗','button primary');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';
              button.replaceWith(link);status.textContent='Lien prêt · en attente de règlement';
            } catch(error){status.textContent=error.message;button.disabled=false;}
          };row.append(button);
        }
        output.append(row);
      });
    } catch(error) { output.replaceChildren(text('p',error.message,'outing-ops-explain')); }
  }
  document.addEventListener('toggle',event=>{
    const panel=event.target;
    if(panel instanceof HTMLDetailsElement && panel.matches('[data-checkout-job]') && panel.open) render(panel);
  },true);
})();
