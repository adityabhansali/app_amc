from datetime import datetime

import io

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort, send_from_directory, send_file, current_app)
from flask_login import login_required, current_user
from sqlalchemy import or_

from ..extensions import db
from ..models import (Contract, Visit, Quotation, ServiceRequest, Payment,
                      Notification, RefillOrder, ServiceQuotation,
                      CustomerJourneyEvent, VisitFeedback, Equipment,
                      HealthCheckReport)
from ..utils import customer_required, notify, notify_staff, WAIVER_TEXT
from ..email_service import (send_quote_accepted_alert, send_negotiation_alert)
from ..pdf_generator import (generate_quotation_pdf, generate_health_report_pdf,
                            generate_service_report_pdf,
                            generate_material_quotation_pdf)

portal_bp = Blueprint("portal", __name__, url_prefix="/portal")


def _own_contract(contract_id):
    c = db.session.get(Contract, contract_id)
    if not c or c.customer_id != current_user.id:
        abort(404)
    return c


@portal_bp.route("/")
@login_required
@customer_required
def dashboard():
    contracts = Contract.query.filter_by(customer_id=current_user.id)\
        .order_by(Contract.created_at.desc()).all()
    requests_ = ServiceRequest.query.filter_by(customer_id=current_user.id)\
        .order_by(ServiceRequest.created_at.desc()).all()
    # Service quotations (sales proposals) needing the customer's attention.
    # Match by customer_id OR phone so pre-login applications are always found.
    pending_quotes = ServiceQuotation.query.filter(
        or_(
            ServiceQuotation.customer_id == current_user.id,
            ServiceQuotation.customer_phone == current_user.phone,
        ),
        ServiceQuotation.status.in_(["sent", "viewed", "negotiation_requested"]),
    ).order_by(ServiceQuotation.created_at.desc()).all()
    refills = RefillOrder.query.filter_by(customer_id=current_user.id)\
        .order_by(RefillOrder.created_at.desc()).all()
    # Only surface action buttons for services the customer actually uses.
    has_emergencies = any(r.request_type == "emergency" for r in requests_)
    has_refills = bool(refills)
    return render_template("portal/dashboard.html", contracts=contracts,
                           requests=requests_, pending_quotes=pending_quotes,
                           refills=refills,
                           has_emergencies=has_emergencies, has_refills=has_refills)


@portal_bp.route("/contract/<int:contract_id>")
@login_required
@customer_required
def contract(contract_id):
    c = _own_contract(contract_id)
    health_reports = HealthCheckReport.query.filter_by(
        contract_id=c.id, status="completed").order_by(
        HealthCheckReport.report_date.desc()).all()
    return render_template("portal/contract.html", c=c,
                           health_reports=health_reports)


@portal_bp.route("/visit/<int:visit_id>")
@login_required
@customer_required
def visit(visit_id):
    v = db.session.get(Visit, visit_id)
    if not v or v.contract.customer_id != current_user.id:
        abort(404)
    return render_template("portal/visit.html", v=v)


@portal_bp.route("/report/<int:visit_id>")
@login_required
@customer_required
def report(visit_id):
    v = db.session.get(Visit, visit_id)
    if not v or v.contract.customer_id != current_user.id or not v.service_report_path:
        abort(404)
    path = v.service_report_path
    # On Vercel the report lives in Blob storage (absolute URL) — redirect there.
    if path.startswith(("http://", "https://")):
        return redirect(path)
    # Otherwise it's relative to the local static folder (dev).
    return send_from_directory(current_app.static_folder, path, as_attachment=True)


@portal_bp.route("/visit/<int:visit_id>/service-report.pdf")
@login_required
@customer_required
def service_report_pdf(visit_id):
    """Branded NSE service report generated from the visit record."""
    v = db.session.get(Visit, visit_id)
    if not v or v.contract.customer_id != current_user.id:
        abort(404)
    pdf = generate_service_report_pdf(v)
    if not pdf:
        abort(500)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"{v.contract.reference}-{v.label.replace(' ','')}.pdf")


@portal_bp.route("/visit/<int:visit_id>/approve", methods=["POST"])
@login_required
@customer_required
def visit_approve(visit_id):
    """Customer signs off a completed visit and submits the mandatory rating."""
    v = db.session.get(Visit, visit_id)
    if not v or v.contract.customer_id != current_user.id:
        abort(404)
    if v.status != "completed":
        flash("You can rate a visit once it is completed.", "warning")
        return redirect(url_for("portal.visit", visit_id=v.id))

    def _r(field):
        try:
            n = int(request.form.get(field, 0))
            return n if 1 <= n <= 5 else None
        except (ValueError, TypeError):
            return None

    overall = _r("rating_overall")
    if overall is None:
        flash("Please rate the visit before approving.", "warning")
        return redirect(url_for("portal.visit", visit_id=v.id))

    fb = VisitFeedback.query.filter_by(visit_id=v.id).first()
    if not fb:
        fb = VisitFeedback(visit_id=v.id, customer_id=current_user.id,
                           technician_id=v.technician_id)
        db.session.add(fb)
    fb.technician_id = v.technician_id
    fb.rating_behaviour = _r("rating_behaviour")
    fb.rating_quality = _r("rating_quality")
    fb.rating_punctuality = _r("rating_punctuality")
    fb.rating_communication = _r("rating_communication")
    fb.rating_overall = overall
    fb.comment = request.form.get("comment", "").strip() or None

    v.customer_approved = True
    v.approved_at = datetime.utcnow()
    db.session.add(CustomerJourneyEvent(
        customer_id=current_user.id, event_type="feedback_given",
        description=f"Customer rated {v.label} of {v.contract.reference} {overall}/5",
        ref_type="visit", ref_id=v.id))
    db.session.commit()

    # Notify the technician + ops console of the rating
    if v.technician_id:
        notify(v.technician_id, f"⭐ {overall}/5 — {v.label} rated",
               f"{current_user.name} rated {v.label} of {v.contract.reference} {overall}/5.",
               link=url_for("admin.visit", visit_id=v.id))
    notify_staff(f"Feedback received — {v.contract.reference} {v.label}",
                 f"{current_user.name} rated {overall}/5"
                 + (f": {fb.comment[:80]}" if fb.comment else "."),
                 link=url_for("admin.visit", visit_id=v.id))
    flash("Thank you! Your feedback has been shared with our team.", "success")
    return redirect(url_for("portal.visit", visit_id=v.id))


@portal_bp.route("/quotation/<int:quote_id>")
@login_required
@customer_required
def quotation(quote_id):
    q = db.session.get(Quotation, quote_id)
    if not q or q.contract.customer_id != current_user.id:
        abort(404)
    return render_template("portal/quotation.html", q=q, waiver_text=WAIVER_TEXT)


@portal_bp.route("/quotation/<int:quote_id>/decide", methods=["POST"])
@login_required
@customer_required
def quotation_decide(quote_id):
    q = db.session.get(Quotation, quote_id)
    if not q or q.contract.customer_id != current_user.id:
        abort(404)
    if q.status != "pending":
        flash("This quotation has already been decided.", "warning")
        return redirect(url_for("portal.quotation", quote_id=q.id))

    decision = request.form.get("decision")
    if decision == "approve":
        q.status = "approved"
        q.payment_mode = request.form.get("payment_mode", "cash")
        q.decided_at = datetime.utcnow()
        db.session.add(Payment(customer_id=current_user.id, contract_id=q.contract_id,
                               quotation_id=q.id, amount=q.total,
                               mode=q.payment_mode, status="pending",
                               reference=q.reference))
        db.session.add(CustomerJourneyEvent(
            customer_id=current_user.id, event_type="quote_accepted",
            description=f"Customer approved material quotation {q.reference} (₹{q.total:,.0f})",
            ref_type="contract", ref_id=q.contract_id))
        db.session.commit()
        notify_staff(f"Quotation {q.reference} APPROVED",
                     f"{current_user.name} approved ₹{q.total:,.0f} of materials.",
                     link=url_for("admin.visit", visit_id=q.visit_id) if q.visit_id
                          else url_for("admin.contract", contract_id=q.contract_id))
        # chime flash → base.html plays the success chime on the next page
        flash("Quotation approved. Our team will schedule the replacement.", "success_chime")
        return redirect(url_for("portal.contract", contract_id=q.contract_id))
    elif decision == "reject":
        # Rejecting a recommended replacement requires accepting the liability
        # waiver. The portal shows it as a modal and posts waiver_accepted=1.
        if request.form.get("waiver_accepted") != "1":
            flash("Please confirm the liability waiver to decline the replacement.", "warning")
            return redirect(url_for("portal.quotation", quote_id=q.id))
        q.status = "rejected"
        q.decided_at = datetime.utcnow()
        q.rejection_acknowledged = True
        q.waiver_text = WAIVER_TEXT
        db.session.add(CustomerJourneyEvent(
            customer_id=current_user.id, event_type="quote_rejected",
            description=f"Customer declined {q.reference} and accepted the liability waiver",
            ref_type="contract", ref_id=q.contract_id))
        db.session.commit()
        notify_staff(f"Quotation {q.reference} DECLINED (waiver accepted)",
                     f"{current_user.name} declined the replacement. Next visit proceeds as scheduled.",
                     link=url_for("admin.visit", visit_id=q.visit_id) if q.visit_id
                          else url_for("admin.contract", contract_id=q.contract_id))
        flash("Recorded. The next visit will proceed as scheduled.", "info")
        return redirect(url_for("portal.contract", contract_id=q.contract_id))
    return redirect(url_for("portal.contract", contract_id=q.contract_id))


@portal_bp.route("/quotation/<int:quote_id>/pdf")
@login_required
@customer_required
def quotation_pdf(quote_id):
    """Client-side PDF download for a visit-linked material quotation."""
    q = db.session.get(Quotation, quote_id)
    if not q or q.contract.customer_id != current_user.id:
        abort(404)
    pdf, filename = generate_material_quotation_pdf(q)
    if not pdf:
        abort(500)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


@portal_bp.route("/health-report/<int:report_id>/pdf")
@login_required
@customer_required
def health_report_pdf(report_id):
    """Client download of a fire health checkup report (ownership-checked)."""
    r = db.session.get(HealthCheckReport, report_id)
    if not r or not r.contract_id:
        abort(404)
    contract = db.session.get(Contract, r.contract_id)
    if not contract or contract.customer_id != current_user.id:
        abort(404)
    pdf = generate_health_report_pdf(r)
    if not pdf:
        abort(500)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{r.reference}.pdf")


@portal_bp.route("/requests")
@login_required
@customer_required
def requests_list():
    rs = ServiceRequest.query.filter_by(customer_id=current_user.id)\
        .order_by(ServiceRequest.created_at.desc()).all()
    return render_template("portal/requests.html", requests=rs)


@portal_bp.route("/notifications/read")
@login_required
def mark_read():
    Notification.query.filter_by(user_id=current_user.id, read=False)\
        .update({"read": True})
    db.session.commit()
    return redirect(request.referrer or url_for("portal.dashboard"))


@portal_bp.route("/notifications")
@login_required
@customer_required
def notifications():
    notes = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(100).all()
    return render_template("portal/notifications.html", notes=notes)


# ─────────────────────────────────────────────────────────────────
# Service Quotations (sales proposals)
# ─────────────────────────────────────────────────────────────────

@portal_bp.route("/service-quotations")
@login_required
@customer_required
def service_quotations():
    sqs = ServiceQuotation.query.filter_by(customer_id=current_user.id)\
        .order_by(ServiceQuotation.created_at.desc()).all()
    return render_template("portal/sq_list.html", quotations=sqs)


@portal_bp.route("/service-quotation/<int:sq_id>")
@login_required
@customer_required
def service_quotation(sq_id):
    sq = db.session.get(ServiceQuotation, sq_id)
    if not sq or sq.customer_id != current_user.id:
        abort(404)
    # Mark as viewed
    if sq.status == "sent":
        sq.status = "viewed"
        sq.viewed_at = datetime.utcnow()
        db.session.add(CustomerJourneyEvent(
            customer_id=current_user.id,
            event_type="quote_viewed",
            description=f"Quotation {sq.reference} viewed by customer",
            ref_type="service_quotation", ref_id=sq.id,
        ))
        db.session.commit()
    sales_phone = current_app.config.get("SALES_MANAGER_PHONE", "+919687266625")
    return render_template("portal/sq_detail.html", sq=sq, sales_phone=sales_phone)


@portal_bp.route("/service-quotation/<int:sq_id>/pdf")
@login_required
@customer_required
def service_quotation_pdf(sq_id):
    """Customer-facing PDF download (ownership-checked) — mirrors the staff route
    so the portal button doesn't hit the staff-only /ops endpoint (403)."""
    sq = db.session.get(ServiceQuotation, sq_id)
    if not sq or sq.customer_id != current_user.id:
        abort(404)
    pdf = generate_quotation_pdf(sq)
    if not pdf:
        abort(500)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{sq.reference}.pdf")


@portal_bp.route("/service-quotation/<int:sq_id>/accept", methods=["POST"])
@login_required
@customer_required
def service_quotation_accept(sq_id):
    sq = db.session.get(ServiceQuotation, sq_id)
    if not sq or sq.customer_id != current_user.id:
        abort(404)
    if sq.status not in ("sent", "viewed", "negotiation_requested"):
        flash("This quotation cannot be accepted at its current stage.", "warning")
        return redirect(url_for("portal.service_quotation", sq_id=sq_id))

    sq.status = "accepted"
    sq.responded_at = datetime.utcnow()
    db.session.add(CustomerJourneyEvent(
        customer_id=current_user.id,
        event_type="quote_accepted",
        description=f"Customer accepted {sq.reference} (₹{sq.grand_total:,.0f})",
        ref_type="service_quotation", ref_id=sq.id,
    ))
    db.session.commit()
    send_quote_accepted_alert(sq)
    notify_staff(
        f"Quotation {sq.reference} ACCEPTED",
        f"{sq.customer_name} accepted ₹{sq.grand_total:,.0f}. "
        f"{'Contract ' + sq.contract.reference + ' can now be activated.' if sq.contract else ''}".strip(),
        link=url_for("admin.contract", contract_id=sq.contract_id) if sq.contract_id
             else url_for("sq.detail_quotation", sq_id=sq.id))
    flash("Quotation accepted! Our team will contact you shortly to proceed.", "success_chime")
    return redirect(url_for("portal.service_quotation", sq_id=sq_id))


@portal_bp.route("/service-quotation/<int:sq_id>/negotiate", methods=["POST"])
@login_required
@customer_required
def service_quotation_negotiate(sq_id):
    sq = db.session.get(ServiceQuotation, sq_id)
    if not sq or sq.customer_id != current_user.id:
        abort(404)
    if sq.status not in ("sent", "viewed"):
        flash("Negotiation can only be requested on a pending quotation.", "warning")
        return redirect(url_for("portal.service_quotation", sq_id=sq_id))

    note = request.form.get("negotiation_note", "").strip()
    sq.status = "negotiation_requested"
    sq.negotiation_note = note
    sq.responded_at = datetime.utcnow()
    db.session.add(CustomerJourneyEvent(
        customer_id=current_user.id,
        event_type="negotiation_requested",
        description=f"Customer requested negotiation on {sq.reference}" + (f": {note[:80]}" if note else ""),
        ref_type="service_quotation", ref_id=sq.id,
    ))
    db.session.commit()
    send_negotiation_alert(sq)
    notify_staff(
        f"Negotiation requested on {sq.reference}",
        (f"{sq.customer_name}: {note[:120]}" if note else
         f"{sq.customer_name} wants to discuss the price / has a question."),
        link=url_for("sq.detail_quotation", sq_id=sq.id))
    flash("Your request has been sent. Our sales manager will call you shortly.", "info")
    return redirect(url_for("portal.service_quotation", sq_id=sq_id))


# ─────────────────────────────────────────────────────────────────
# Customer journey timeline
# ─────────────────────────────────────────────────────────────────

@portal_bp.route("/journey")
@login_required
@customer_required
def journey():
    events = (CustomerJourneyEvent.query
              .filter_by(customer_id=current_user.id)
              .order_by(CustomerJourneyEvent.created_at.desc())
              .all())
    return render_template("portal/journey.html", events=events)


# ─────────────────────────────────────────────────────────────────
# Wave 2 — Equipment detail page
# ─────────────────────────────────────────────────────────────────

@portal_bp.route("/equipment/<int:equipment_id>")
@login_required
@customer_required
def equipment_detail(equipment_id):
    """Full history for one piece of equipment: refills, visits, status."""
    eq = db.session.get(Equipment, equipment_id)
    if not eq:
        abort(404)
    # Ownership check via contract
    contract = db.session.get(Contract, eq.contract_id)
    if not contract or contract.customer_id != current_user.id:
        abort(404)
    # Visits where this contract was serviced (proxy for equipment serviced)
    visits = (Visit.query
              .filter_by(contract_id=eq.contract_id)
              .filter(Visit.status == "completed")
              .order_by(Visit.completed_date.desc())
              .all())
    return render_template("portal/equipment_detail.html",
                           eq=eq, contract=contract, visits=visits)
