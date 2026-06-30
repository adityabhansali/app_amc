"""
nse/reminders.py — payment-reminder computation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Surfaces "money still owed" nudges across the app:

  * AMC annual fee unpaid after 2+ completed visits
  * Visit-linked material quotations approved but not yet paid
  * Service quotations accepted (client committed) but payment not confirmed

Used by the Ops Console (staff sees everyone's) and the customer profile
(filtered to their own). Pure read helper — no side effects.
"""
from flask import url_for


def payment_reminders(customer_id=None):
    """Return a list of reminder dicts. If `customer_id` is given, only that
    customer's reminders are returned (for the portal profile view)."""
    from .models import Contract, Quotation, ServiceQuotation

    reminders = []

    # 1) AMC annual fee unpaid after 2+ completed visits ---------------------
    q = Contract.query.filter(Contract.status == "active")
    if customer_id:
        q = q.filter(Contract.customer_id == customer_id)
    for c in q.all():
        if c.payment_status != "paid" and c.completed_visits >= 2:
            reminders.append({
                "kind": "amc_fee",
                "severity": "high",
                "title": "AMC fee unpaid",
                "detail": (f"{c.reference} — {c.completed_visits} visits done, "
                           f"annual fee not yet received."),
                "customer_id": c.customer_id,
                "customer_name": (c.customer.name if c.customer else c.applicant_name),
                "link": url_for("admin.contract", contract_id=c.id),
            })

    # 2) Visit-linked material quotes approved but unpaid --------------------
    mq = Quotation.query.filter(Quotation.status == "approved",
                                Quotation.payment_status != "paid")
    for m in mq.all():
        cust_id = m.contract.customer_id if m.contract else None
        if customer_id and cust_id != customer_id:
            continue
        reminders.append({
            "kind": "material_quote",
            "severity": "medium",
            "title": "Material quotation unpaid",
            "detail": (f"{m.reference} (₹{m.grand_total:,.0f}) approved"
                       f"{' on ' + m.visit.label if m.visit else ''} — payment pending."),
            "customer_id": cust_id,
            "customer_name": m.customer_name,
            "link": (url_for("admin.visit", visit_id=m.visit_id) if m.visit_id
                     else url_for("admin.contract", contract_id=m.contract_id)),
        })

    # 3) Service quotations accepted but payment not confirmed ----------------
    sq = ServiceQuotation.query.filter(ServiceQuotation.status == "accepted",
                                       ServiceQuotation.payment_status != "paid")
    if customer_id:
        sq = sq.filter(ServiceQuotation.customer_id == customer_id)
    for s in sq.all():
        # An accepted AMC quote whose contract fee reminder already fires above
        # would double-count; skip if it's linked to an active contract that the
        # amc_fee rule already covers.
        if s.contract and s.contract.status == "active" and s.contract.completed_visits >= 2 \
                and s.contract.payment_status != "paid":
            continue
        chose = f" — client chose {s.payment_method_label}" if s.payment_method else ""
        reminders.append({
            "kind": "service_quote",
            "severity": "medium",
            "title": "Quotation accepted, payment pending",
            "detail": f"{s.reference} (₹{s.grand_total:,.0f}) accepted{chose}.",
            "customer_id": s.customer_id,
            "customer_name": s.customer_name,
            "link": url_for("sq.detail_quotation", sq_id=s.id),
        })

    return reminders


def payment_reminder_count(customer_id=None):
    return len(payment_reminders(customer_id=customer_id))
