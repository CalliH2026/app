"""Local-only school outing operations for a visibly labelled demonstration.

This module deliberately imports no network, mail, calendar or reservation
transport. Its 'sent' and 'reserved' states are simulated records in the job.
The caller owns locking and persistence. Synthetic choices are never legal
consent, school approval, real family responses or real inventory bookings.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


MODE = 'simulation'
SCENARIO_SOURCE = 'Scénario local de démonstration · aucune réponse réelle reçue'
STEPS = (
    'parent_messages', 'family_responses', 'targeted_reminders',
    'photo_permissions', 'equipment_check', 'equipment_reservation', 'administration',
)


def _now():
    return datetime.now(ZoneInfo('Europe/Paris')).isoformat()


def ensure(job):
    """Initialise demo data without replacing metadata owned by the caller."""
    revision = job.get('revision', 1)
    ops = job.get('operations')
    if ops is None:
        ops = {}
        job['operations'] = ops
    source_revision = ops.get('source_revision', ops.get('snapshot_revision', revision))
    if source_revision != revision:
        raise ValueError('Le dossier a changé. Relancez la démonstration administrative depuis sa nouvelle version.')
    defaults = {
        'mode': MODE, 'simulated': True, 'external_effects': False,
        'source_revision': source_revision, 'snapshot_revision': source_revision,
        'stage': 'not_started', 'completed_steps': [], 'families': [], 'counts': {},
        'messages': [], 'photo': {}, 'equipment': {}, 'admin': {}, 'events': [],
        'scenario_source': SCENARIO_SOURCE,
    }
    for key, value in defaults.items():
        ops.setdefault(key, deepcopy(value))
    # These are invariants, not options accepted from a model or saved payload.
    if ops['mode'] != MODE or ops['external_effects'] is not False or ops['simulated'] is not True:
        raise ValueError('Cette démonstration exige le mode simulation sans effets externes.')
    for family in ops['families']:
        if not str(family.get('email', '')).endswith('.invalid'):
            raise ValueError('Les familles de démonstration doivent utiliser des adresses fictives .invalid.')
    _counts(ops)
    return ops


def _family_count(job):
    count = (job.get('roster') or {}).get('student_count')
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 60:
        raise ValueError('La liste de classe doit être disponible avant cette démonstration.')
    return count


def _families(job, ops):
    count = _family_count(job)
    if ops['families']:
        if len(ops['families']) != count:
            raise ValueError('L’effectif a changé. Relancez la démonstration administrative.')
        return ops['families']
    return [
        {'id': f'family-{i:02}', 'label': f'Famille fictive {i:02}',
         'student_label': f'Élève fictif {i:02}', 'email': f'famille{i:02}@example.invalid',
         'response': 'pending', 'photo_consent': 'pending', 'reminder_state': 'not_needed',
         'simulated': True, 'source': SCENARIO_SOURCE}
        for i in range(1, count + 1)
    ]


def _counts(ops):
    families, messages = ops.get('families', []), ops.get('messages', [])
    ops['counts'] = {
        'families': len(families),
        'confirmed': sum(f['response'] == 'confirmed' for f in families),
        'declined': sum(f['response'] == 'declined' for f in families),
        'pending': sum(f['response'] == 'pending' for f in families),
        'responses': sum(f['response'] != 'pending' for f in families),
        'initial_messages': sum(m['kind'] == 'invitation' for m in messages),
        'confirmation_messages': sum(m['kind'] == 'confirmation' for m in messages),
        'reminders': sum(m['kind'] == 'reminder' for m in messages),
        'photo_authorized': sum(f['photo_consent'] == 'authorized' for f in families),
        'photo_refused': sum(f['photo_consent'] == 'refused' for f in families),
        'photo_pending': sum(f['photo_consent'] == 'pending' for f in families),
        'equipment_reserved_units': sum(r['quantity'] for r in ops.get('equipment', {}).get('reservations', [])),
        'admin_prepared_documents': len(ops.get('admin', {}).get('documents', [])),
        'admin_pending_checks': sum(c['status'] == 'pending' for c in ops.get('admin', {}).get('checklist', [])),
    }


def _require(ops, *steps):
    missing = [step for step in steps if step not in ops['completed_steps']]
    if missing:
        raise ValueError('Étape préalable à appeler : ' + ', '.join(missing))


def _finish(job, step, text, *, cached=False):
    ops = ensure(job)
    if not cached:
        ops['completed_steps'].append(step)
        ops['stage'] = step
        ops['events'].append({'id': f"{job.get('id', 'demo')}:{step}", 'step': step,
                              'at': _now(), 'text': text, 'simulated': True,
                              'external_effects': False})
    _counts(ops)
    return {**summary(job), 'operation': step, 'cached': cached}


def _cached(job, step):
    return step in ensure(job)['completed_steps']


def _trip(job):
    route, visit, data = job.get('route') or {}, job.get('visit') or {}, job.get('input') or {}
    destination = (route.get('destination') or {}).get('name') or visit.get('name') or 'Destination à confirmer'
    def clock(field):
        try:
            return datetime.fromisoformat(route[field]).strftime('%H:%M')
        except (KeyError, TypeError, ValueError):
            return 'à confirmer'
    amount = (job.get('budget') or {}).get('per_student')
    try:
        money = format(Decimal(str(amount)), '.2f').replace('.', ',') + ' €'
        if not Decimal(str(amount)).is_finite():
            money = 'à confirmer'
    except (InvalidOperation, TypeError, ValueError):
        money = 'à confirmer'
    return {'destination': destination, 'date': data.get('date') or 'à confirmer',
            'objective': data.get('objective') or 'à compléter par le professeur',
            'departure': clock('departure_at'), 'return': clock('return_at'), 'contribution': money}


def _message(family, kind, subject, body, at):
    return {'id': f"{kind}:{family['id']}", 'kind': kind, 'recipient_id': family['id'],
            'recipient': family['email'], 'recipient_label': family['label'],
            'subject': '[DÉMO — NON ENVOYÉ] ' + subject,
            'body': 'SIMULATION — AUCUN MESSAGE RÉEL N’A ÉTÉ ENVOYÉ.\n\n' + body,
            'state': 'simulated_sent', 'simulated': True, 'actual_sent': False,
            'external_effects': False, 'simulated_at': at}


def prepare_parent_messages(job):
    step = 'parent_messages'
    if _cached(job, step):
        return _finish(job, step, '', cached=True)
    ops = ensure(job)
    if not (job.get('dossier') or {}).get('text'):
        raise ValueError('Préremplissez le dossier de sortie avant de préparer les messages aux familles.')
    families, trip, at = _families(job, ops), _trip(job), _now()
    body = (f"Madame, Monsieur,\n\nNous préparons une sortie à destination de {trip['destination']} le {trip['date']}.\n"
            f"Objectif pédagogique : {trip['objective']}.\nDépart envisagé : {trip['departure']} ; retour prévu : {trip['return']}.\n"
            f"Participation prévisionnelle : {trip['contribution']} par élève.\n\n"
            "Merci de confirmer la participation de votre enfant. Le choix concernant les photos est demandé séparément. "
            "La réservation, le budget et la sortie restent soumis à validation par l’établissement.\n\nL’équipe pédagogique")
    ops['families'] = families
    ops['messages'].extend(_message(f, 'invitation', f"Sortie du {trip['date']} · réponse attendue", body, at) for f in families)
    return _finish(job, step, f"Envoi simulé vers {len(families)} familles fictives · aucun mail envoyé.")


def simulate_family_responses(job):
    step = 'family_responses'
    if _cached(job, step):
        return _finish(job, step, '', cached=True)
    ops = ensure(job)
    _require(ops, 'parent_messages')
    count, at = len(ops['families']), _now()
    confirmed = count * 5 // 7
    declined = min(2, max(0, count - confirmed - 1))
    for index, family in enumerate(ops['families']):
        family['response'] = 'confirmed' if index < confirmed else 'declined' if index < confirmed + declined else 'pending'
        family['response_source'] = SCENARIO_SOURCE
        if family['response'] != 'pending':
            family['response_simulated_at'] = at
        if family['response'] == 'confirmed':
            body = ("Votre réponse fictive a été prise en compte dans la démonstration. "
                    "La participation est marquée confirmée dans ce scénario. Cette confirmation ne vaut ni autorisation signée "
                    "ni accord pour les photos. Les documents définitifs restent à valider par l’établissement.")
            ops['messages'].append(_message(family, 'confirmation', 'Confirmation de participation — simulation', body, at))
    pending = count - confirmed - declined
    return _finish(job, step, f"Réponses simulées : {confirmed} confirmations, {declined} refus, {pending} sans réponse · aucun retour réel reçu.")


def prepare_targeted_reminders(job):
    step = 'targeted_reminders'
    if _cached(job, step):
        return _finish(job, step, '', cached=True)
    ops = ensure(job)
    _require(ops, 'family_responses')
    trip, at, recipients = _trip(job), _now(), []
    for family in ops['families']:
        if family['response'] != 'pending':
            continue
        body = (f"Nous attendons encore votre réponse pour la sortie à destination de {trip['destination']} le {trip['date']}. "
                "Merci d’indiquer si votre enfant participera. Si votre réponse a déjà été donnée, elle devra être rapprochée du dossier par le professeur. "
                "Aucune relance réelle n’est envoyée par cette démonstration.")
        ops['messages'].append(_message(family, 'reminder', 'Rappel ciblé · réponse à la sortie', body, at))
        family['reminder_state'] = 'simulated_sent'
        recipients.append(family['id'])
    ops['reminder_recipient_ids'] = recipients
    return _finish(job, step, f"{len(recipients)} relances ciblées simulées ; les confirmations et refus sont exclus.")


def prepare_photo_permissions(job):
    step = 'photo_permissions'
    if _cached(job, step):
        return _finish(job, step, '', cached=True)
    ops = ensure(job)
    ops['families'] = _families(job, ops)
    count, at, trip = len(ops['families']), _now(), _trip(job)
    authorized, refused = count * 9 // 14, min(4, count - count * 9 // 14)
    # Rotate decisions relative to participation responses: these are two
    # separate choices, and an outing confirmation cannot grant photo consent.
    order = ops['families'][4:] + ops['families'][:4]
    decisions, blocked = [], []
    for index, family in enumerate(order):
        choice = 'authorized' if index < authorized else 'refused' if index < authorized + refused else 'pending'
        family['photo_consent'] = choice
        family['photo_source'] = SCENARIO_SOURCE
        if choice != 'pending':
            family['photo_response_simulated_at'] = at
        decisions.append({'family_id': family['id'], 'label': family['label'], 'status': choice, 'simulated': True})
        if choice != 'authorized':
            blocked.append(family['id'])
    text = ("AUTORISATION PHOTO — MODÈLE DE DÉMONSTRATION À FAIRE VALIDER\nAucune signature réelle collectée.\n\n"
            f"Sortie : {trip['destination']} · {trip['date']}\nÉlève : [à compléter]\nResponsable légal : [à compléter]\n\n"
            "Finalité proposée : carnet pédagogique de la classe lié à cette sortie.\n"
            "Supports envisagés : carnet de classe et espace scolaire à accès restreint, à préciser par l’établissement.\n"
            "Durée de conservation : [à définir et valider par l’établissement].\n"
            "Choix distinct de la participation : ☐ J’autorise ☐ Je refuse la prise et l’utilisation de l’image pour la finalité décrite.\n"
            "Le refus de photo ne change pas la participation à la sortie. Aucun usage public ou réseau social n’est inclus dans ce brouillon.\n"
            "Contact pour modifier un choix ou demander le retrait : [contact établissement à compléter].\n"
            "Date et signature : [à recueillir hors de cette démonstration].\n\n"
            "Ce texte est un brouillon fictif, sans valeur d’accord ni de validation juridique.")
    ops['photo'] = {'status': 'prepared', 'simulated': True, 'external_effects': False,
                    'title': 'Autorisation photo · choix séparé de la sortie',
                    'document': {'id': 'photo-authorization-demo', 'title': 'Autorisation photo — brouillon',
                                 'text': text, 'status': 'draft', 'simulated': True},
                    'decisions': decisions, 'blocked_families': blocked,
                    'counts': {'authorized': authorized, 'refused': refused, 'pending': count - authorized - refused},
                    'actual_signatures': 0,
                    'usage_policy': 'En simulation, seules les familles explicitement autorisées sont incluses ; refus et absences de réponse restent exclus.'}
    return _finish(job, step, f"Autorisation photo préparée : {authorized} accords, {refused} refus respectés, {count-authorized-refused} réponses attendues — scénario fictif.")


def check_equipment(job):
    step = 'equipment_check'
    if _cached(job, step):
        return _finish(job, step, '', cached=True)
    ops = ensure(job)
    count = _family_count(job)
    tablets = max(1, (count + 3) // 4 + 1)
    items = [
        {'id': 'tablets', 'label': 'Tablettes pédagogiques', 'requested': tablets, 'available': 6, 'unit': 'unité'},
        {'id': 'clipboards', 'label': 'Supports d’écriture', 'requested': (count + 1) // 2, 'available': 30, 'unit': 'unité'},
        {'id': 'audio-kit', 'label': 'Kit audio portable', 'requested': 1, 'available': 2, 'unit': 'kit'},
    ]
    conflicts, fallbacks = [], []
    for item in items:
        item.update(allocated=0, shortfall=max(0, item['requested'] - item['available']))
        if item['shortfall']:
            conflicts.append({'item_id': item['id'], 'requested': item['requested'], 'available': item['available'],
                              'missing': item['shortfall'], 'solution': 'Supports papier proposés pour les groupes restants.', 'simulated': True})
            fallbacks.append({'id': 'paper-kits', 'label': 'Kits papier en remplacement', 'quantity': item['shortfall'] * 2,
                              'reason': 'Alternative de démonstration au matériel indisponible.', 'simulated': True})
    if fallbacks:
        items.append({'id': 'paper-kits', 'label': 'Kits papier de remplacement',
                      'requested': sum(item['quantity'] for item in fallbacks), 'available': 60,
                      'allocated': 0, 'shortfall': 0, 'unit': 'kit'})
    ops['equipment'] = {'status': 'checked', 'simulated': True, 'external_effects': False, 'actual_reserved': False,
                        'checked_at': _now(), 'source': 'Inventaire fictif de démonstration', 'items': items,
                        'conflicts': conflicts, 'fallbacks': fallbacks, 'reservations': []}
    return _finish(job, step, f"Inventaire fictif vérifié : {len(conflicts)} indisponibilité(s), alternative papier proposée.")


def reserve_equipment(job):
    step = 'equipment_reservation'
    if _cached(job, step):
        return _finish(job, step, '', cached=True)
    ops = ensure(job)
    _require(ops, 'equipment_check')
    route, data, at = job.get('route') or {}, job.get('input') or {}, _now()
    start = route.get('departure_at') or f"{data.get('date', 'Date à confirmer')} · horaire à confirmer"
    end = route.get('return_at') or f"{data.get('date', 'Date à confirmer')} · horaire à confirmer"
    reservations = []
    for item in ops['equipment']['items']:
        quantity = min(item['requested'], item['available'])
        item['allocated'] = quantity
        item['remaining'] = item['available'] - quantity
        if quantity:
            reservations.append({'id': f"equipment:{item['id']}", 'item_id': item['id'], 'label': item['label'],
                                 'quantity': quantity, 'start_at': start, 'end_at': end,
                                 'status': 'simulated_reserved', 'simulated': True, 'actual_reserved': False,
                                 'external_effects': False, 'simulated_at': at})
    for conflict in ops['equipment']['conflicts']:
        conflict.update(resolution_state='simulated_resolved', resolved_by='paper-kits')
    ops['equipment'].update(status='reserved_simulation', reservations=reservations, reserved_simulated_at=at)
    return _finish(job, step, f"Réservation simulée de {sum(r['quantity'] for r in reservations)} unités disponibles ; aucune réservation réelle effectuée.")


def prepare_administration(job):
    step = 'administration'
    if _cached(job, step):
        return _finish(job, step, '', cached=True)
    ops = ensure(job)
    _require(ops, *STEPS[:-1])
    trip, counts = _trip(job), ops['counts']
    documents = [
        {'id': 'outing-file-demo', 'title': 'Fiche de sortie préremplie', 'text': (job.get('dossier') or {}).get('text', 'Informations à compléter.')},
        {'id': 'parent-authorization-demo', 'title': 'Autorisation parentale — brouillon',
         'text': f"DÉMONSTRATION — AUCUNE SIGNATURE COLLECTÉE\nSortie : {trip['destination']} · {trip['date']}\nÉlève : [à compléter]\nResponsable légal : [à compléter]\nChoix de participation : ☐ Oui ☐ Non\nDate et signature : [à recueillir après validation de l’établissement]."},
        {'id': 'photo-authorization-demo', 'title': ops['photo']['document']['title'], 'text': ops['photo']['document']['text']},
        {'id': 'equipment-slip-demo', 'title': 'Bon de matériel — réservation simulée',
         'text': 'DÉMONSTRATION — AUCUNE RÉSERVATION RÉELLE\n' + '\n'.join(f"{r['label']} : {r['quantity']}" for r in ops['equipment']['reservations'])},
    ]
    for document in documents:
        document.update(status='draft', simulated=True, external_effects=False, actual_approved=False)
    checklist = [
        {'id': 'file', 'label': 'Fiche de sortie et budget', 'status': 'prepared', 'detail': 'Brouillon prérempli à relire.'},
        {'id': 'family-forms', 'label': 'Autorisation parentale', 'status': 'prepared', 'detail': 'Formulaire préparé ; aucune signature réelle.'},
        {'id': 'photo-form', 'label': 'Autorisation photo séparée', 'status': 'prepared', 'detail': 'Choix photo fictifs enregistrés ; refus et absences de réponse exclus.'},
        {'id': 'equipment', 'label': 'Bon de matériel', 'status': 'prepared', 'detail': 'Réservation simulée, indisponibilités et alternative papier conservées.'},
        {'id': 'principal', 'label': 'Accord du chef d’établissement', 'status': 'pending', 'detail': 'À demander réellement ; aucune approbation obtenue.'},
        {'id': 'venue', 'label': 'Réservation du lieu et du transport', 'status': 'pending', 'detail': 'À confirmer auprès des prestataires ; aucun contact effectué.'},
        {'id': 'signatures', 'label': 'Autorisations signées', 'status': 'pending', 'detail': 'À recueillir réellement après validation de la sortie.'},
        {'id': 'schedule', 'label': 'Emploi du temps complet et encadrement', 'status': 'pending', 'detail': 'À contrôler avec l’établissement.'},
    ]
    for item in checklist:
        item.update(simulated=True, actual_approved=False)
    ops['admin'] = {'status': 'draft_prepared', 'simulated': True, 'external_effects': False,
                    'documents': documents, 'checklist': checklist,
                    'missing': [item['label'] for item in checklist if item['status'] == 'pending'],
                    'approval_status': 'not_requested', 'actual_approved': False, 'actual_signatures': 0,
                    'summary': f"{len(documents)} documents de démonstration préparés ; {counts['pending']} familles sans réponse dans le scénario."}
    return _finish(job, step, 'Dossier administratif de démonstration assemblé : 4 brouillons, validations et signatures encore à obtenir.')


def summary(job):
    """Bounded response for Holo4; full previews remain in job.operations."""
    ops = ensure(job)
    return {'mode': MODE, 'simulated': True, 'external_effects': False,
            'stage': ops['stage'], 'source_revision': ops['source_revision'],
            'completed_steps': deepcopy(ops['completed_steps']), 'counts': deepcopy(ops['counts']),
            'photo': {'status': ops['photo'].get('status', 'not_started'),
                      'counts': deepcopy(ops['photo'].get('counts', {})), 'actual_signatures': 0},
            'equipment': {'status': ops['equipment'].get('status', 'not_started'),
                          'conflicts': deepcopy(ops['equipment'].get('conflicts', [])),
                          'reservations': [{'item_id': r['item_id'], 'quantity': r['quantity'], 'actual_reserved': False}
                                           for r in ops['equipment'].get('reservations', [])]},
            'admin': {'status': ops['admin'].get('status', 'not_started'),
                      'missing': deepcopy(ops['admin'].get('missing', [])), 'actual_approved': False},
            'next_steps': [step for step in STEPS if step not in ops['completed_steps']],
            'notice': 'Tout ce suivi est simulé localement. Aucun mail, réservation, accord ou signature réels.'}
