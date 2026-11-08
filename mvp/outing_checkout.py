"""Opt-in Stripe sandbox Checkout, kept separate from simulated outing operations.

The durable ledger is authoritative; only verified webhooks can confirm payment.
It stores opaque family/job references, never card details or student names.
The shared fictional pilot deliberately refuses live-mode credentials.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import importlib.util
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
import uuid


class CheckoutUnavailable(RuntimeError):
    """Safe operational error, without provider payloads or credentials."""


def configuration():
    """Return public capability information; secrets never enter the response."""
    secret = os.getenv('STRIPE_SECRET_KEY', '')
    base = os.getenv('STRIPE_RETURN_BASE_URL', '').rstrip('/')
    parsed = urlsplit(base)
    valid_origin = bool(parsed.hostname and not parsed.username and not parsed.password
                        and parsed.path == '' and not parsed.query and not parsed.fragment
                        and (parsed.scheme == 'https' or (parsed.scheme == 'http'
                             and parsed.hostname in ('localhost', '127.0.0.1'))))
    enabled = (os.getenv('CALLI_STRIPE_ENABLED') == 'true'
               and secret.startswith(('sk_test_', 'rk_test_'))
               and os.getenv('STRIPE_WEBHOOK_SECRET', '').startswith('whsec_')
               and valid_origin and importlib.util.find_spec('stripe') is not None)
    return {'provider': 'Stripe', 'mode': 'test', 'enabled': enabled,
            'message': 'Stripe Checkout disponible en environnement de test.' if enabled else
            'Stripe Checkout prêt à configurer : clé de test, webhook et URL de retour requis.'}


def configured_store():
    if not configuration()['enabled']:
        raise CheckoutUnavailable('Stripe Checkout n’est pas configuré.')
    from stripe import StripeClient, RequestsClient
    from .engine import DATA
    client = StripeClient(os.environ['STRIPE_SECRET_KEY'], max_network_retries=1,
                          http_client=RequestsClient(timeout=15))
    return CheckoutStore(Path(DATA) / 'outing-checkout.sqlite3',
                         os.environ['STRIPE_RETURN_BASE_URL'].rstrip('/'), client)


def verify_event(payload, signature, secret):
    """Verify the original bytes and timestamp with Stripe's official SDK."""
    from stripe import Webhook, SignatureVerificationError
    try:
        return Webhook.construct_event(payload, signature, secret, tolerance=300).to_dict()
    except (ValueError, SignatureVerificationError):
        raise ValueError('Signature Stripe invalide.') from None


def contribution(job, family_id):
    """Validate current source evidence and calculate cents without float rounding."""
    ops = job.get('operations') or {}
    family = next((f for f in ops.get('families', []) if f['id'] == family_id), None)
    if (not re.fullmatch(r'[a-f0-9]{12}', str(job.get('id', '')))
            or job.get('status') not in ('done', 'ready', 'saved') or not job.get('dossier')
            or ops.get('source_revision') != job.get('revision', 1)
            or not family or family.get('response') == 'declined'):
        raise ValueError('Dossier ou famille à vérifier avant de préparer le paiement.')
    budget = job.get('budget') or {}
    try:
        amount = Decimal(str(budget.get('per_student')))
        valid = amount.is_finite() and Decimal('.50') <= amount <= 100000
        valid = valid and amount == amount.quantize(Decimal('.01')) and budget.get('complete') is True
    except (InvalidOperation, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError('Un budget complet et positif, en centimes exacts, est requis.')
    return int(amount * 100)


class CheckoutStore:
    """One checkout per outing/family. A changed or expired contribution needs review.

    SQLite uniqueness survives restarts. A committed reservation retains the same
    Stripe idempotency key after a timeout; retries stop before its 24h retention
    window. No automatic replacement session can create a second contribution.
    """
    def __init__(self, path, base_url, client):
        self.path, self.base_url, self.client = Path(path), base_url, client
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS payments (
                    reference TEXT PRIMARY KEY, job_id TEXT NOT NULL, family_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL,
                    status TEXT NOT NULL, session_id TEXT, url TEXT, created_at INTEGER NOT NULL,
                    expires_at INTEGER, UNIQUE(job_id,family_id));
                CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY);
            ''')

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def list(self, job_id):
        with self.db() as db:
            return [self.public(row) for row in db.execute(
                'SELECT * FROM payments WHERE job_id=? ORDER BY family_id', (job_id,))]

    @staticmethod
    def public(row):
        result = {key: row[key] for key in ('reference', 'family_id', 'amount_minor', 'currency', 'status')}
        usable = row['status'] == 'pending' and (row['expires_at'] or 0) > time.time()
        result.update(url=row['url'] if usable else None, mode='test')
        return result

    def create(self, job, family_id):
        cents = contribution(job, family_id)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM payments WHERE job_id=? AND family_id=?', (job['id'], family_id)).fetchone()
            if row is None:
                reference = 'calli-' + uuid.uuid4().hex
                db.execute('''INSERT INTO payments
                    (reference,job_id,family_id,revision,amount_minor,currency,status,created_at)
                    VALUES (?,?,?,?,?,'eur','pending',?)''',
                    (reference, job['id'], family_id, job.get('revision', 1), cents, int(time.time())))
                row = db.execute('SELECT * FROM payments WHERE reference=?', (reference,)).fetchone()
            if row['amount_minor'] != cents or row['revision'] != job.get('revision', 1):
                raise ValueError('Une contribution existe pour un autre budget. Rapprochement manuel requis.')
            if row['session_id']:
                if row['status'] == 'paid':
                    return self.public(row)
                if row['status'] in ('expired', 'failed') or (row['expires_at'] or 0) <= time.time():
                    raise ValueError('Cette session est terminée. Vérifiez-la dans Stripe avant de la remplacer.')
                return self.public(row)
            if time.time() - row['created_at'] >= 23 * 3600:
                raise ValueError('Résultat Stripe incertain : rapprochement manuel requis avant une nouvelle tentative.')
            reference = row['reference']
        # Reservation was committed before network I/O; concurrent calls use the same key.
        params = {'mode': 'payment', 'payment_method_types': ['card'], 'locale': 'fr',
                  'line_items': [{'price_data': {'currency': 'eur', 'unit_amount': cents,
                      'product_data': {'name': 'Participation à la sortie scolaire'}}, 'quantity': 1}],
                  'metadata': {'checkout_ref': reference}, 'client_reference_id': reference,
                  'success_url': self.base_url + '/payments/return',
                  'cancel_url': self.base_url + '/payments/return?cancelled=1'}
        try:
            session = self.client.v1.checkout.sessions.create(params, options={'idempotency_key': reference})
            if hasattr(session, 'to_dict'):
                session = session.to_dict()
            url = urlsplit(session.get('url') or '')
            if (session.get('livemode') is not False or not str(session.get('id', '')).startswith('cs_test_')
                    or url.scheme != 'https' or url.netloc != 'checkout.stripe.com'
                    or not isinstance(session.get('expires_at'), int)):
                raise ValueError('Unexpected Stripe session')
        except Exception:
            raise CheckoutUnavailable('Stripe indisponible. Réessayez : la même référence sera conservée.') from None
        with self.db() as db:
            db.execute('UPDATE payments SET session_id=?,url=?,expires_at=? WHERE reference=?',
                       (session['id'], session['url'], session['expires_at'], reference))
            return self.public(db.execute('SELECT * FROM payments WHERE reference=?', (reference,)).fetchone())

    def apply_event(self, event):
        """Apply an already signature-verified event; duplicates and old events are harmless."""
        kind = event.get('type')
        if kind not in ('checkout.session.completed', 'checkout.session.async_payment_succeeded',
                        'checkout.session.async_payment_failed', 'checkout.session.expired'):
            return 'ignored'
        obj = (event.get('data') or {}).get('object') or {}
        reference = (obj.get('metadata') or {}).get('checkout_ref')
        if not reference:
            return 'ignored'
        if not isinstance(event.get('id'), str) or not event['id']:
            raise ValueError('Événement Stripe invalide.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM events WHERE id=?', (event['id'],)).fetchone():
                return 'duplicate'
            row = db.execute('SELECT * FROM payments WHERE reference=?', (reference,)).fetchone()
            if row is None:
                return 'ignored'
            if (event.get('livemode') is not False or obj.get('livemode') is not False
                    or obj.get('mode') != 'payment' or obj.get('amount_total') != row['amount_minor']
                    or obj.get('currency') != row['currency']
                    or not str(obj.get('id', '')).startswith('cs_test_')
                    or row['session_id'] and row['session_id'] != obj.get('id')):
                raise ValueError('Événement Stripe incompatible avec la contribution.')
            db.execute('INSERT INTO events (id) VALUES (?)', (event['id'],))
            if row['status'] == 'paid':
                return 'ignored'
            status = ('paid' if kind in ('checkout.session.completed', 'checkout.session.async_payment_succeeded')
                      and obj.get('payment_status') == 'paid' else
                      'expired' if kind == 'checkout.session.expired' else
                      'failed' if kind == 'checkout.session.async_payment_failed' else 'pending')
            # A late unpaid completed event must not reopen an expired session.
            if status == 'pending' and row['status'] in ('expired', 'failed'):
                return 'ignored'
            db.execute('UPDATE payments SET status=?,session_id=? WHERE reference=?', (status, obj['id'], reference))
            return 'updated'
