"""Checkout contract: never infer payment from a click or browser redirect."""
import json
import time
import hashlib
import hmac
from types import SimpleNamespace
import pytest
from mvp import outing_checkout as checkout

@pytest.fixture
def job():
    return {'id':'aabbccddeeff','revision':1,'status':'done','dossier':{'text':'ready'},
            'budget':{'complete':True,'per_student':'12.34'},
            'operations':{'source_revision':1,'families':[{'id':'family-01','response':'confirmed'}]}}

@pytest.fixture
def service(tmp_path):
    calls=[]
    class Sessions:
        def create(self, params, options):
            calls.append((params,options))
            from stripe import StripeObject
            return StripeObject.construct_from({'id':'cs_test_unit','url':'https://checkout.stripe.com/c/pay/cs_test_unit',
                    'livemode':False,'expires_at':int(time.time())+3600}, key=None)
    client=SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions())))
    result=checkout.CheckoutStore(tmp_path/'payments.sqlite3','http://localhost:8000',client)
    result.calls=calls
    return result


def test_checkout_is_server_priced_and_reused_after_restart(service, job):
    first=service.create(job,'family-01')
    assert first['status']=='pending' and first['amount_minor']==1234
    assert first['url'].startswith('https://checkout.stripe.com/')
    restarted=checkout.CheckoutStore(service.path,service.base_url,service.client)
    assert restarted.create(job,'family-01')==first
    assert len(service.calls)==1
    params,options=service.calls[0]
    assert params['line_items'][0]['price_data']['unit_amount']==1234
    assert params['mode']=='payment'
    assert params['payment_method_types']==['card']
    assert 'customer_email' not in params
    assert params['metadata']=={'checkout_ref':first['reference']}
    assert options['idempotency_key']==first['reference']
    assert params['success_url']=='http://localhost:8000/payments/return'

@pytest.mark.parametrize('price',[None,True,'NaN','Infinity','0','-1','0.49','12.345','1000000'])
def test_invalid_budget_never_calls_stripe(service,job,price):
    job['budget']['per_student']=price
    with pytest.raises(ValueError):service.create(job,'family-01')
    assert service.calls==[]

@pytest.mark.parametrize('change',[{'budget':{'complete':False,'per_student':'12.34'}}, {'revision':2},
                                   {'status':'preparing'}, {'dossier':None}])
def test_incomplete_or_stale_dossier_rejected(service,job,change):
    job.update(change)
    with pytest.raises(ValueError):service.create(job,'family-01')
    assert service.calls==[]


def test_declined_unknown_and_changed_contribution_rejected(service,job):
    with pytest.raises(ValueError):service.create(job,'family-99')
    job['operations']['families'][0]['response']='declined'
    with pytest.raises(ValueError):service.create(job,'family-01')
    job['operations']['families'][0]['response']='confirmed'
    service.create(job,'family-01')
    job['budget']['per_student']='20.00'
    with pytest.raises(ValueError):service.create(job,'family-01')
    assert len(service.calls)==1


def event(payment, *, kind='checkout.session.completed', status='paid', event_id='evt_unit'):
    return {'id':event_id,'type':kind,'livemode':False,'data':{'object':{
        'id':'cs_test_unit','livemode':False,'mode':'payment','payment_status':status,
        'amount_total':1234,'currency':'eur','metadata':{'checkout_ref':payment['reference']}}}}


def test_signed_webhook_marks_payment_once_and_cannot_regress(service,job):
    payment=service.create(job,'family-01')
    data=event(payment)
    raw=json.dumps(data).encode();secret='whsec_'+'unit-test-only'
    stamp=str(int(time.time()));sig=hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    verified=checkout.verify_event(raw,f't={stamp},v1={sig}',secret)
    assert service.apply_event(verified)=='updated'
    assert service.apply_event(verified)=='duplicate'
    assert service.list(job['id'])[0]['status']=='paid'
    assert service.apply_event(event(payment,kind='checkout.session.expired',status='unpaid',event_id='evt_late'))=='ignored'
    assert service.list(job['id'])[0]['status']=='paid'
    with pytest.raises(ValueError):checkout.verify_event(raw+b' ',f't={stamp},v1={sig}',secret)

@pytest.mark.parametrize('field,value',[('amount_total',99),('currency','usd'),('livemode',True),('id','cs_other'),('mode','subscription')])
def test_mismatched_webhook_cannot_mark_paid(service,job,field,value):
    payment=service.create(job,'family-01'); data=event(payment);data['data']['object'][field]=value
    with pytest.raises(ValueError):service.apply_event(data)
    assert service.list(job['id'])[0]['status']=='pending'


def test_unpaid_completed_is_pending_and_paid_can_arrive_later(service,job):
    payment=service.create(job,'family-01')
    service.apply_event(event(payment,status='unpaid'))
    assert service.list(job['id'])[0]['status']=='pending'
    service.apply_event(event(payment,kind='checkout.session.async_payment_succeeded',event_id='evt_paid'))
    assert service.list(job['id'])[0]['status']=='paid'


def test_timeout_uses_same_reference_on_retry(service,job):
    original=service.client.v1.checkout.sessions.create
    refs=[]
    def fail(params, options):
        refs.append(options['idempotency_key']);raise TimeoutError('private provider details')
    service.client.v1.checkout.sessions.create=fail
    with pytest.raises(checkout.CheckoutUnavailable,match='Stripe'):service.create(job,'family-01')
    service.client.v1.checkout.sessions.create=original
    payment=service.create(job,'family-01')
    assert refs==[payment['reference']]


def test_config_disabled_without_keys_and_rejects_live_keys(monkeypatch):
    for key in ['CALLI_STRIPE_ENABLED','STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','STRIPE_RETURN_BASE_URL']:
        monkeypatch.delenv(key,raising=False)
    assert checkout.configuration()['enabled'] is False
    monkeypatch.setenv('CALLI_STRIPE_ENABLED','true')
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_live_'+'unit-test-only')
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_'+'unit-test-only')
    monkeypatch.setenv('STRIPE_RETURN_BASE_URL','http://localhost:8000')
    assert checkout.configuration()['enabled'] is False
    monkeypatch.setenv('STRIPE_SECRET_KEY','sk_test_'+'unit-test-only')
    assert checkout.configuration()['enabled'] is True
    monkeypatch.setenv('STRIPE_RETURN_BASE_URL','https://example.com.evil@localhost:8000/path')
    assert checkout.configuration()['enabled'] is False
