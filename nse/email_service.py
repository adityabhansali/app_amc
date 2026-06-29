"""
nse/email_service.py
~~~~~~~~~~~~~~~~~~~~
Centralised email functions for Northern Star Engineering.

All sending goes through Flask-Mail (Outlook SMTP).  When
MAIL_SUPPRESS_SEND=true (the default for dev), calls are logged to console
instead of actually sending — no SMTP credentials needed for local work.

Usage:
    from nse.email_service import send_quotation_email
    send_quotation_email(quotation, pdf_bytes)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from flask import current_app, render_template
from flask_mail import Message

from .extensions import mail

log = logging.getLogger(__name__)

SALES_PHONE = "+91 96872 66625"   # Click-to-call for negotiation


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _send(msg: Message, pdf_bytes: Optional[bytes] = None,
          pdf_filename: str = "quotation.pdf") -> bool:
    """Send *msg*, optionally attaching a PDF.  Returns True on success."""
    if pdf_bytes:
        msg.attach(pdf_filename, "application/pdf", pdf_bytes)

    suppressed = current_app.config.get("MAIL_SUPPRESS_SEND", True)
    if suppressed:
        log.info("[EMAIL SUPPRESSED] To=%s  Subject=%s", msg.recipients, msg.subject)
        return True

    if not current_app.config.get("MAIL_PASSWORD"):
        log.warning("[EMAIL SKIPPED] MAIL_PASSWORD not set — add to .env to send.")
        return False

    try:
        mail.send(msg)
        log.info("[EMAIL SENT] To=%s  Subject=%s", msg.recipients, msg.subject)
        return True
    except Exception as exc:           # noqa: BLE001
        log.error("[EMAIL ERROR] %s", exc)
        return False


def _subject(text: str) -> str:
    company = current_app.config.get("COMPANY_NAME", "Northern Star Engineering")
    return f"{company}: {text}"


# ──────────────────────────────────────────────────────────────────────────────
# Public send functions
# ──────────────────────────────────────────────────────────────────────────────

def send_quotation_email(quotation, pdf_bytes: bytes) -> bool:
    """Email the PDF quotation to the customer when staff clicks 'Send'."""
    to = quotation.customer_email
    if not to:
        log.warning("send_quotation_email: no email for quotation %s", quotation.reference)
        return False

    body = render_template("email/quotation_sent.html", q=quotation)
    msg = Message(
        subject=_subject(f"Your Quotation {quotation.reference}"),
        recipients=[to],
        html=body,
    )
    filename = f"{quotation.reference}.pdf"
    return _send(msg, pdf_bytes, filename)


def send_negotiation_alert(quotation) -> bool:
    """Notify staff when a customer requests negotiation."""
    staff_email = current_app.config.get("MAIL_USERNAME", "")
    if not staff_email:
        return False

    body = render_template("email/negotiation_requested.html", q=quotation,
                           sales_phone=SALES_PHONE)
    msg = Message(
        subject=_subject(f"Negotiation Requested — {quotation.reference}"),
        recipients=[staff_email],
        html=body,
    )
    return _send(msg)


def send_quote_accepted_alert(quotation) -> bool:
    """Notify staff when a customer accepts a quotation."""
    staff_email = current_app.config.get("MAIL_USERNAME", "")
    if not staff_email:
        return False

    body = render_template("email/quote_accepted.html", q=quotation)
    msg = Message(
        subject=_subject(f"Quote Accepted — {quotation.reference}"),
        recipients=[staff_email],
        html=body,
    )
    return _send(msg)


def send_visit_confirmation(visit) -> bool:
    """Email customer when a visit is scheduled."""
    contract = visit.contract
    if not contract:
        return False
    to = contract.applicant_email or (contract.customer.email if contract.customer else None)
    if not to:
        return False

    body = render_template("email/visit_scheduled.html", visit=visit, contract=contract)
    msg = Message(
        subject=_subject(f"Visit Scheduled — {contract.reference}"),
        recipients=[to],
        html=body,
    )
    # Also CC the assigned technician if they have an email
    if visit.technician and visit.technician.email:
        msg.cc = [visit.technician.email]

    return _send(msg)


def send_visit_reminder(visit) -> bool:
    """Email reminder 3 days before the visit date."""
    contract = visit.contract
    if not contract:
        return False
    to = contract.applicant_email or (contract.customer.email if contract.customer else None)
    if not to:
        return False

    body = render_template("email/visit_reminder.html", visit=visit, contract=contract)
    msg = Message(
        subject=_subject(f"Upcoming Visit Reminder — {contract.reference}"),
        recipients=[to],
        html=body,
    )
    return _send(msg)


def send_feedback_request(visit, feedback_token: str) -> bool:
    """Email customer a feedback link after visit is marked completed."""
    contract = visit.contract
    if not contract:
        return False
    to = contract.applicant_email or (contract.customer.email if contract.customer else None)
    if not to:
        return False

    feedback_url = f"/feedback/{feedback_token}"
    body = render_template("email/feedback_request.html", visit=visit,
                           contract=contract, feedback_url=feedback_url)
    msg = Message(
        subject=_subject(f"How did we do? Rate your recent service — {contract.reference}"),
        recipients=[to],
        html=body,
    )
    return _send(msg)


def send_payment_confirmation(contract_or_order, amount: int, mode: str) -> bool:
    """Email payment confirmation to customer and staff."""
    # Works for both Contract and RefillOrder (duck typing — both have applicant_email / email)
    to = getattr(contract_or_order, "applicant_email", None) \
        or getattr(contract_or_order, "email", None)
    ref = getattr(contract_or_order, "reference", str(contract_or_order.id))

    if not to:
        return False

    body = render_template("email/payment_confirmation.html",
                           record=contract_or_order, amount=amount,
                           mode=mode, ref=ref)
    msg = Message(
        subject=_subject(f"Payment Confirmed — {ref}"),
        recipients=[to],
        html=body,
    )
    # BCC staff
    staff_email = current_app.config.get("MAIL_USERNAME", "")
    if staff_email:
        msg.bcc = [staff_email]

    return _send(msg)


def send_enquiry_confirmation(enquiry) -> bool:
    """Auto-reply when someone submits an enquiry."""
    if not enquiry.email:
        return False

    body = render_template("email/enquiry_received.html", e=enquiry)
    msg = Message(
        subject=_subject("We received your enquiry"),
        recipients=[enquiry.email],
        html=body,
    )
    return _send(msg)
