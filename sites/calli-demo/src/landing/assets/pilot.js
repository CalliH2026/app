(() => {
  const fr = document.documentElement.lang === 'fr';
  const pins = [...document.querySelectorAll('[data-school]')];
  const detail = document.getElementById('school-detail');
  function showSchool(pin) {
    pins.forEach(p => p.setAttribute('aria-pressed', String(p === pin)));
    detail.textContent = `${fr ? 'Établissement' : 'School'} 0${pin.dataset.school} · Île-de-France · ${fr ? 'Pilote confirmé' : 'Pilot confirmed'}`;
  }
  pins.forEach(pin => {
    pin.addEventListener('click', () => showSchool(pin));
    pin.addEventListener('focus', () => showSchool(pin));
  });
  const form = document.getElementById('pilot-form');
  const status = document.getElementById('pilot-status');
  const submit = form.querySelector('[type=submit]');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form.reportValidity() || submit.disabled) return;
    submit.disabled = true;
    status.textContent = fr ? 'Enregistrement…' : 'Registering your interest…';
    status.className = '';
    const data = new FormData(form);
    const body = {email: data.get('email'), school: data.get('school'), role: data.get('role'), consent: data.get('consent') === 'on', website: data.get('website'), language: fr ? 'fr' : 'en'};
    try {
      const response = await fetch('/pilot/interest', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});
      if (!response.ok) throw new Error(String(response.status));
      const result = await response.json();
      if (result.ok !== true) throw new Error('not_saved');
      status.className = 'pilot-success';
      status.textContent = fr ? 'Merci ! Votre intérêt est enregistré. L’équipe Calli vous recontactera au sujet du pilote.' : 'Thank you! Your interest is registered. The Calli team will follow up about the pilot.';
      submit.textContent = fr ? 'Intérêt enregistré ✓' : 'Interest registered ✓';
      [...form.elements].forEach(element => element.disabled = true);
    } catch {
      status.className = 'pilot-error';
      status.textContent = fr ? 'L’enregistrement n’a pas pu être confirmé. Vos champs sont conservés ; réessayez dans quelques instants.' : 'We could not confirm your registration. Your details are still here; please try again shortly.';
      submit.disabled = false;
    }
  });
})();
