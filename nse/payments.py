"""
nse/payments.py — Razorpay gateway helpers (Wave 11, gateway-ready)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Thin wrapper around Razorpay so quotation payments can be captured online and a
webhook flips `payment_status='paid'` automatically. Everything degrades
gracefully when keys are absent — exactly like the OpenRouter AI layer:

  * `enabled()` is False until RAZORPAY_KEY_ID + RAZORPAY_KEY_SECRET are set, so
    the UI keeps offering the manual UPI/cash flow.
  * The `razorpay` SDK is imported lazily; the app runs fine without it installed.

Signature verification is done with stdlib hmac so it works even without the SDK.
"""
import hashlib
import hmac

from flask import current_app


def enabled():
    return bool(current_app.config.get("RAZORPAY_KEY_ID")
                and current_app.config.get("RAZORPAY_KEY_SECRET"))


def key_id():
    return current_app.config.get("RAZORPAY_KEY_ID", "")


def _client():
    import razorpay  # lazy — only needed when actually enabled
    return razorpay.Client(auth=(current_app.config["RAZORPAY_KEY_ID"],
                                 current_app.config["RAZORPAY_KEY_SECRET"]))


def create_order(amount_rupees, receipt, notes=None):
    """Create a Razorpay order (amount auto-converted to paise). Returns the
    order dict, or None if the gateway is disabled or the call fails."""
    if not enabled():
        return None
    try:
        return _client().order.create({
            "amount": int(round(float(amount_rupees) * 100)),
            "currency": "INR",
            "receipt": receipt,
            "notes": notes or {},
            "payment_capture": 1,
        })
    except Exception:
        current_app.logger.exception("Razorpay order creation failed")
        return None


def verify_payment_signature(order_id, payment_id, signature):
    """Verify the checkout callback signature (order_id|payment_id)."""
    secret = current_app.config.get("RAZORPAY_KEY_SECRET", "").encode()
    if not secret or not (order_id and payment_id and signature):
        return False
    expected = hmac.new(secret, f"{order_id}|{payment_id}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body_bytes, signature):
    """Verify a Razorpay webhook body against RAZORPAY_WEBHOOK_SECRET."""
    secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET", "").encode()
    if not secret:
        return False
    expected = hmac.new(secret, body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def mark_quote_paid(sq, payment_id=None, method="online"):
    """Flip a ServiceQuotation to paid and cascade to its contract. Shared by the
    checkout-verify route and the webhook so both paths behave identically."""
    from datetime import datetime
    from .extensions import db
    from .utils import notify
    from flask import url_for

    if sq.payment_status == "paid":
        return
    sq.payment_status = "paid"
    sq.payment_method = method
    sq.payment_reference = payment_id or sq.payment_reference
    sq.gateway_payment_id = payment_id or sq.gateway_payment_id
    sq.payment_marked_at = datetime.utcnow()
    if sq.status in ("sent", "viewed", "negotiation_requested"):
        sq.status = "accepted"
        sq.responded_at = sq.responded_at or datetime.utcnow()
    if sq.contract:
        sq.contract.payment_status = "paid"
        if hasattr(sq.contract, "payment_date"):
            sq.contract.payment_date = datetime.utcnow()
    db.session.commit()
    if sq.customer_id:
        try:
            link = url_for("portal.service_quotation", sq_id=sq.id)
        except Exception:
            link = None
        notify(sq.customer_id, "Payment received — thank you!",
               f"Your online payment of ₹{sq.grand_total:,.0f} for {sq.reference} "
               f"is confirmed.", link=link)
