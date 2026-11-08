"""HTTP boundary for optional outing Checkout; no payment is made by Calli itself."""
import os
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from . import outing_checkout as checkout

WEBHOOK_PATH = '/api/stripe/webhook'


def is_stripe_webhook(request):
    """Only this POST bypasses browser auth/origin; the handler verifies its signature."""
    return request.method == 'POST' and request.url.path == WEBHOOK_PATH


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    family_id: str = Field(pattern=r'^family-\d{2}$')


def install_routes(app):
    @app.get('/api/stripe/config')
    def config():
        return checkout.configuration()

    @app.get('/api/outings/{outing_id}/checkout')
    def payments(outing_id: str, request: Request):
        if getattr(request.state, 'sites_public_poc', False):
            raise HTTPException(403, 'Le paiement nécessite le compagnon configuré.')
        from .outings import get
        try:
            job = get(outing_id)
            capability = checkout.configuration()
            entries = checkout.configured_store().list(outing_id) if capability['enabled'] else []
            families = [{'id': f['id'], 'label': f.get('student_label', f['id']), 'response': f.get('response')}
                        for f in (job.get('operations') or {}).get('families', [])]
            return {**capability, 'entries': entries, 'families': families}
        except KeyError:
            raise HTTPException(404, 'Sortie introuvable.') from None

    @app.post('/api/outings/{outing_id}/checkout')
    def create(outing_id: str, body: CheckoutRequest, request: Request):
        if getattr(request.state, 'sites_public_poc', False):
            raise HTTPException(403, 'Le paiement nécessite le compagnon configuré.')
        from .outings import get
        try:
            store = checkout.configured_store()
            return store.create(get(outing_id), body.family_id)
        except checkout.CheckoutUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except KeyError:
            raise HTTPException(404, 'Sortie introuvable.') from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post(WEBHOOK_PATH)
    async def webhook(request: Request):
        try:
            store = checkout.configured_store()
            # Limit accumulation before SDK signature verification.
            payload = bytearray()
            async for chunk in request.stream():
                payload.extend(chunk)
                if len(payload) > 262144:
                    raise HTTPException(413, 'Événement trop volumineux.')
            event = checkout.verify_event(bytes(payload), request.headers.get('stripe-signature', ''),
                                          os.environ['STRIPE_WEBHOOK_SECRET'])
            return {'result': store.apply_event(event)}
        except checkout.CheckoutUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except ValueError:
            raise HTTPException(400, 'Événement ou signature Stripe invalide.') from None

    @app.get('/payments/return')
    def payment_return():
        from .engine import ROOT
        # Query strings are ignored. A redirect is never payment evidence.
        return FileResponse(ROOT / 'static/checkout-return.html', headers={'Cache-Control': 'no-store'})
