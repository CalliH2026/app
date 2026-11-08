"""Route boundaries: webhook signatures replace login only for the exact hook."""
import hashlib
import hmac
import json
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from mvp import outing_checkout_routes as routes
from mvp import outing_checkout as checkout
from mvp.auth import install_auth

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('PUBLIC_URL',raising=False)
    app=FastAPI();routes.install_routes(app)
    return TestClient(app)


def test_disabled_config_does_not_create_a_payment(client,monkeypatch):
    monkeypatch.delenv('CALLI_STRIPE_ENABLED',raising=False)
    assert client.get('/api/stripe/config').json()['enabled'] is False
    result=client.post('/api/outings/aabbccddeeff/checkout',json={'family_id':'family-01'})
    assert result.status_code==503


def test_client_cannot_supply_a_price_or_redirect(client):
    result=client.post('/api/outings/aabbccddeeff/checkout',json={
        'family_id':'family-01','amount':1,'success_url':'https://attacker.invalid'})
    assert result.status_code==422


def test_return_page_never_confirms_payment(client):
    response=client.get('/payments/return?status=paid&session_id=forged')
    assert response.status_code==200
    assert 'confirmation' in response.text
    assert 'Paiement confirmé' not in response.text
    assert 'forged' not in response.text


def test_webhook_signature_exact_route_and_proxy_boundary(monkeypatch,tmp_path):
    monkeypatch.setenv('PUBLIC_URL','https://school.example')
    monkeypatch.setenv('SESSION_SECRET','test-session-'*4)
    monkeypatch.setenv('ALLOWED_EMAILS','teacher@example.invalid')
    monkeypatch.setenv('GOOGLE_CLIENT_ID','offline-test')
    monkeypatch.setenv('GOOGLE_CLIENT_SECRET','offline-test')
    monkeypatch.setenv('SITES_PROXY_TOKEN','unit-proxy-'*4)
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET','whsec_unit-test')
    store=checkout.CheckoutStore(tmp_path/'ledger.db','https://school.example',None)
    monkeypatch.setattr(checkout,'configured_store',lambda:store)
    app=FastAPI();routes.install_routes(app);install_auth(app)
    client=TestClient(app,base_url='https://school.example')
    assert client.post('/api/stripe/webhook',content=b'{}',headers={'Stripe-Signature':'bad'}).status_code==400
    payload=json.dumps({'id':'evt_irrelevant','type':'unhandled.event'}).encode()
    stamp=str(int(time.time()));signature=hmac.new(b'whsec_unit-test',stamp.encode()+b'.'+payload,hashlib.sha256).hexdigest()
    assert client.post('/api/stripe/webhook',content=payload,headers={'Stripe-Signature':f't={stamp},v1={signature}'}).status_code==200
    assert client.post('/api/stripe/webhook/extra',content=payload).status_code in (401,403)
    assert client.get('/api/stripe/config').status_code==401
    headers={'Origin':'https://school.example','x-pronote-sites-token':'unit-proxy-'*4}
    assert client.post('/api/outings/aabbccddeeff/checkout',json={'family_id':'family-01'},headers=headers).status_code==403
    assert client.post('/api/outings/aabbccddeeff/checkout',json={'family_id':'family-01'},headers={'Origin':'https://evil.invalid'}).status_code==403
