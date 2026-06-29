from datetime import datetime, date, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from flask_login import login_required, current_user
from sqlalchemy import or_

from ..extensions import db
from ..models import (User, AMCPlan, Contract, Visit, VisitPhoto, Equipment,
                      RefillRecord, Quotation, QuotationItem, ServiceRequest,
                      Payment, Enquiry, RefillOrder, RefillItem, FormAttachment,
                      VisitFeedback, CustomerJourneyEvent, ServiceQuotation,
                      VisitChecklistItem, InventoryItem, HealthCheckReport)
from ..utils import staff_required, save_upload, notify
from ..email_service import send_feedback_request, send_visit_confirmation

admin_bp = Blueprint("admin", __name__, url_prefix="/ops")


def _apply_reschedule(v, new_date):
    """Move a visit to a new date, logging it on the customer journey and
    notifying the client. Returns True if the date actually changed."""
    if not new_date or new_date == v.scheduled_date:
        return False
    old = v.scheduled_date
    if v.contract.customer_id:
        db.session.add(CustomerJourneyEvent(
            customer_id=v.contract.customer_id,
            event_type="visit_rescheduled",
            description=(f"{v.label} of {v.contract.reference} moved "
                         f"{('from ' + old.strftime('%d %b %Y') + ' ') if old else ''}"
                         f"to {new_date:%d %b %Y}"),
            ref_type="visit", ref_id=v.id,
            created_by_id=current_user.id))
        notify(v.contract.customer_id, f"{v.label} rescheduled",
               f"{v.label} for {v.contract.reference} is now on {new_date:%d %b %Y}.",
               link=url_for("portal.contract", contract_id=v.contract_id))
    v.scheduled_date = new_date
    return True


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
@admin_bp.route("/")
@login_required
@staff_required
def dashboard():
    pending_apps = Contract.query.filter_by(status="pending")\
        .order_by(Contract.created_at.desc()).all()
    active = Contract.query.filter_by(status="active").count()
    open_emergencies = ServiceRequest.query.filter(
        ServiceRequest.request_type == "emergency",
        ServiceRequest.status.notin_(["completed", "cancelled"])).all()
    open_noc = ServiceRequest.query.filter(
        ServiceRequest.request_type == "noc",
        ServiceRequest.status.notin_(["completed", "cancelled"])).all()
    new_enquiries = Enquiry.query.filter_by(status="new").count()
    upcoming = Visit.query.filter(
        Visit.status.in_(["scheduled", "in_progress"]),
        Visit.scheduled_date != None)\
        .order_by(Visit.scheduled_date).limit(8).all()
    # Equipment due soon / overdue
    equip = Equipment.query.filter(Equipment.next_refill_date != None).all()
    due_refills = [e for e in equip if e.refill_status in ("due_soon", "overdue")]
    due_refills.sort(key=lambda e: e.next_refill_date)
    open_refills = RefillOrder.query.filter(
        RefillOrder.status.notin_(["completed", "cancelled"]))\
        .order_by(RefillOrder.created_at.desc()).all()
    # Quotations needing staff action: a client requested negotiation (reply
    # needed) or accepted-but-not-yet-activated (ready to activate). An accepted
    # quote whose contract is already active needs nothing further, so drop it.
    sq_attention = [q for q in ServiceQuotation.query.filter(
        ServiceQuotation.status.in_(["negotiation_requested", "accepted"]))
        .order_by(ServiceQuotation.created_at.desc()).all()
        if q.status == "negotiation_requested"
        or q.contract is None or q.contract.status != "active"]
    return render_template("admin/dashboard.html",
                           pending_apps=pending_apps, active=active,
                           open_emergencies=open_emergencies, open_noc=open_noc,
                           new_enquiries=new_enquiries, upcoming=upcoming,
                           due_refills=due_refills[:10], open_refills=open_refills,
                           sq_attention=sq_attention)


# --------------------------------------------------------------------------- #
# Staff notifications (bell / popup feed)
# --------------------------------------------------------------------------- #
@admin_bp.route("/notifications")
@login_required
@staff_required
def notifications():
    from ..models import Notification
    notes = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(100).all()
    return render_template("admin/notifications.html", notes=notes)


# --------------------------------------------------------------------------- #
# AMC applications & contracts
# --------------------------------------------------------------------------- #
@admin_bp.route("/contracts")
@login_required
@staff_required
def contracts():
    status = request.args.get("status")
    q = Contract.query
    if status:
        q = q.filter_by(status=status)
    items = q.order_by(Contract.created_at.desc()).all()
    return render_template("admin/contracts.html", contracts=items, status=status)


@admin_bp.route("/contract/<int:contract_id>")
@login_required
@staff_required
def contract(contract_id):
    c = db.session.get(Contract, contract_id) or abort(404)
    techs = User.query.filter(User.role.in_(["technician", "admin"])).all()
    attachments = FormAttachment.query.filter_by(
        ref_type="contract", ref_id=contract_id, attachment_type="photo").all()
    return render_template("admin/contract.html", c=c, techs=techs,
                           attachments=attachments)


@admin_bp.route("/contract/<int:contract_id>/activate", methods=["POST"])
@login_required
@staff_required
def activate_contract(contract_id):
    c = db.session.get(Contract, contract_id) or abort(404)
    f = request.form

    # ── Gate: a linked AMC quote must be accepted by the client first ──────
    if not c.can_activate:
        q = c.amc_quote
        flash(f"Cannot activate yet — the customer has not accepted quotation "
              f"{q.reference} (currently: {q.status_label}). Activation unlocks "
              f"once the client accepts the price.", "warning")
        return redirect(url_for("admin.contract", contract_id=c.id))

    # Ensure a customer account exists (linked by phone).
    if not c.customer_id and c.applicant_phone:
        user = User.query.filter_by(phone=c.applicant_phone, role="customer").first()
        if not user:
            user = User(role="customer", name=c.applicant_name or "Customer",
                        phone=c.applicant_phone, email=c.applicant_email,
                        area=c.area, address=c.site_address)
            db.session.add(user)
            db.session.flush()
        c.customer_id = user.id

    start = datetime.strptime(f.get("start_date"), "%Y-%m-%d").date() \
        if f.get("start_date") else date.today()
    n_visits = int(f.get("total_visits") or c.total_visits or 4)
    c.start_date = start
    c.end_date = start + timedelta(days=365)
    c.total_visits = n_visits
    # Price is authoritative from the accepted quote when one exists — the figure
    # was already agreed in the quotation and must not be re-edited here.
    locked = c.quote_locked_price
    c.price = locked if locked is not None else int(f.get("price") or c.price or 0)
    c.status = "active"

    # Generate evenly-spaced scheduled visits across the year.
    if not c.visits:
        interval = max(1, 365 // n_visits)
        for i in range(n_visits):
            db.session.add(Visit(contract_id=c.id, visit_number=i + 1,
                                 scheduled_date=start + timedelta(days=interval * i),
                                 status="scheduled"))
    # Journey log + confirmation to client (quote reviewed → contract live).
    if c.customer_id:
        db.session.add(CustomerJourneyEvent(
            customer_id=c.customer_id, event_type="contract_activated",
            description=f"Contract {c.reference} activated with {n_visits} visits "
                        f"(₹{c.price:,.0f})",
            ref_type="contract", ref_id=c.id,
            created_by_id=current_user.id))
    db.session.commit()
    first = c.next_visit
    notify(c.customer_id, "AMC activated — schedule confirmed",
           f"Your contract {c.reference} is active with {n_visits} visits."
           + (f" First visit: {first.scheduled_date:%d %b %Y}." if first and first.scheduled_date else ""),
           link=url_for("portal.contract", contract_id=c.id))
    flash(f"Contract {c.reference} activated with {n_visits} visits.", "success_chime")
    return redirect(url_for("admin.contract", contract_id=c.id))


@admin_bp.route("/contract/<int:contract_id>/payment", methods=["POST"])
@login_required
@staff_required
def contract_payment(contract_id):
    c = db.session.get(Contract, contract_id) or abort(404)
    c.payment_status = request.form.get("payment_status", c.payment_status)
    c.payment_mode = request.form.get("payment_mode", c.payment_mode)
    if c.payment_status == "paid" and not c.payment_date:
        c.payment_date = date.today()
    if c.payment_status != "paid":
        c.payment_date = None
    db.session.commit()
    if c.payment_status == "paid" and c.customer_id:
        db.session.add(CustomerJourneyEvent(
            customer_id=c.customer_id, event_type="payment_received",
            description=f"Contract {c.reference} fee received (₹{c.price:,.0f})",
            ref_type="contract", ref_id=c.id, created_by_id=current_user.id))
        db.session.commit()
    flash("Payment status updated.", "success")
    return redirect(request.referrer or url_for("admin.contract", contract_id=c.id))


# --------------------------------------------------------------------------- #
# Visits
# --------------------------------------------------------------------------- #
@admin_bp.route("/visit/<int:visit_id>", methods=["GET", "POST"])
@login_required
@staff_required
def visit(visit_id):
    v = db.session.get(Visit, visit_id) or abort(404)
    techs = User.query.filter(User.role.in_(["technician", "admin"])).all()
    if request.method == "POST":
        f = request.form
        v.status = f.get("status", v.status)
        v.work_done = f.get("work_done")
        v.notes = f.get("notes")
        if f.get("technician_id"):
            v.technician_id = int(f.get("technician_id"))
        if f.get("scheduled_date"):
            new_date = datetime.strptime(f.get("scheduled_date"), "%Y-%m-%d").date()
            _apply_reschedule(v, new_date)
        if v.status == "completed" and not v.completed_date:
            v.completed_date = date.today()
        # Report upload
        report = request.files.get("report")
        path = save_upload(report, f"reports/contract{v.contract_id}", {"pdf", "png", "jpg", "jpeg"})
        if path:
            v.service_report_path = path
        # Photo uploads (multiple)
        for photo in request.files.getlist("photos"):
            p = save_upload(photo, f"visits/visit{v.id}", {"png", "jpg", "jpeg", "gif", "webp"})
            if p:
                db.session.add(VisitPhoto(visit_id=v.id, file_path=p,
                                          caption=f.get("photo_caption")))
        # ── Wave 2: save checklist items ──────────────────────────────────
        items_raw = f.get("checklist_items_json", "")
        if items_raw:
            import json as _json
            try:
                checklist_data = _json.loads(items_raw)
                # Delete existing, replace with submitted
                VisitChecklistItem.query.filter_by(visit_id=v.id).delete()
                for idx, it in enumerate(checklist_data):
                    if it.get("item", "").strip():
                        db.session.add(VisitChecklistItem(
                            visit_id=v.id,
                            item=it["item"].strip(),
                            status=it.get("status", "ok"),
                            note=it.get("note", "").strip() or None,
                            sort_order=idx,
                        ))
            except (ValueError, TypeError):
                pass
        db.session.commit()
        if v.status == "completed":
            notify(v.contract.customer_id,
                   f"🎉 Congratulations — your {v.label} is done!",
                   f"Your service report for {v.contract.reference} is ready. "
                   f"Please review, download it, and rate the service.",
                   link=url_for("portal.visit", visit_id=v.id) + "?chime=1")
            # Trigger post-visit feedback email
            _trigger_feedback(v)
            db.session.commit()
        flash("Visit updated.", "success")
        return redirect(url_for("admin.visit", visit_id=v.id))
    inventory = InventoryItem.query.filter_by(active=True)\
        .order_by(InventoryItem.category, InventoryItem.name).all()
    health_reports = HealthCheckReport.query.filter(
        or_(HealthCheckReport.visit_id == v.id,
            HealthCheckReport.contract_id == v.contract_id))\
        .order_by(HealthCheckReport.created_at.desc()).all()
    is_future = (v.scheduled_date > date.today()) if v.scheduled_date else False
    return render_template("admin/visit.html", v=v, techs=techs,
                           checklist_defaults=VisitChecklistItem.STANDARD_ITEMS,
                           inventory=inventory, health_reports=health_reports,
                           is_future=is_future)


# --------------------------------------------------------------------------- #
# Visit-linked material quotation (technician raises from inventory on-site)
# --------------------------------------------------------------------------- #
@admin_bp.route("/visit/<int:visit_id>/quotation", methods=["POST"])
@login_required
@staff_required
def visit_quotation(visit_id):
    """Technician raises a material quotation linked to this visit, picking from
    the inventory list, and it is instantly shared in-app with the client."""
    v = db.session.get(Visit, visit_id) or abort(404)
    f = request.form
    q = Quotation(contract_id=v.contract_id, visit_id=v.id,
                  notes=f.get("notes"), status="pending")
    db.session.add(q)
    db.session.flush()
    descs  = f.getlist("item_desc")
    qtys   = f.getlist("item_qty")
    prices = f.getlist("item_price")
    for d, qty, pr in zip(descs, qtys, prices):
        if d.strip():
            db.session.add(QuotationItem(
                quotation_id=q.id, description=d.strip(),
                quantity=int(qty or 1), unit_price=int(pr or 0)))
    if not q.items:
        db.session.rollback()
        flash("Add at least one item to raise a quotation.", "warning")
        return redirect(url_for("admin.visit", visit_id=v.id))
    db.session.commit()
    if v.contract.customer_id:
        notify(v.contract.customer_id, "New material quotation for approval",
               f"During {v.label} we recommend replacements totalling "
               f"₹{q.total:,.0f}. Please review and approve or decline.",
               link=url_for("portal.quotation", quote_id=q.id))
    flash(f"Quotation {q.reference} (₹{q.total:,.0f}) raised and shared with the client.",
          "success")
    return redirect(url_for("admin.visit", visit_id=v.id))


@admin_bp.route("/quotation/<int:quote_id>/payment", methods=["POST"])
@login_required
@staff_required
def quotation_payment(quote_id):
    """Technician/ops update the payment status of a visit-linked quote."""
    q = db.session.get(Quotation, quote_id) or abort(404)
    q.payment_status = request.form.get("payment_status", q.payment_status)
    q.payment_mode = request.form.get("payment_mode", q.payment_mode)
    if q.payment_status == "paid" and not q.payment_date:
        q.payment_date = date.today()
    if q.payment_status != "paid":
        q.payment_date = None
    db.session.commit()
    if q.payment_status == "paid" and q.contract and q.contract.customer_id:
        db.session.add(CustomerJourneyEvent(
            customer_id=q.contract.customer_id, event_type="payment_received",
            description=f"Payment received for quotation {q.reference} (₹{q.total:,.0f})",
            ref_type="contract", ref_id=q.contract_id,
            created_by_id=current_user.id))
        db.session.commit()
    flash(f"Quotation {q.reference} payment marked {q.payment_status}.", "success")
    return redirect(request.referrer or url_for("admin.visit", visit_id=q.visit_id))


@admin_bp.route("/visit/<int:visit_id>/reschedule", methods=["POST"])
@login_required
@staff_required
def reschedule_visit(visit_id):
    """Quick date change from the contract page (calendar picker per visit row)."""
    v = db.session.get(Visit, visit_id) or abort(404)
    ds = request.form.get("scheduled_date")
    if ds:
        new_date = datetime.strptime(ds, "%Y-%m-%d").date()
        if _apply_reschedule(v, new_date):
            db.session.commit()
            flash(f"{v.label} rescheduled to {new_date:%d %b %Y}. Client notified.", "success")
        else:
            flash("No change — same date.", "info")
    return redirect(request.referrer or url_for("admin.contract", contract_id=v.contract_id))


# --------------------------------------------------------------------------- #
# Equipment & refills
# --------------------------------------------------------------------------- #
@admin_bp.route("/contract/<int:contract_id>/equipment/add", methods=["POST"])
@login_required
@staff_required
def add_equipment(contract_id):
    c = db.session.get(Contract, contract_id) or abort(404)
    f = request.form
    e = Equipment(
        contract_id=c.id, name=f.get("name"), equip_type=f.get("equip_type"),
        location=f.get("location"), serial_no=f.get("serial_no"),
        refill_interval_months=int(f.get("refill_interval_months") or 12),
    )
    if f.get("install_date"):
        e.install_date = datetime.strptime(f.get("install_date"), "%Y-%m-%d").date()
    if f.get("last_refill_date"):
        e.last_refill_date = datetime.strptime(f.get("last_refill_date"), "%Y-%m-%d").date()
    e.recompute_next_refill()
    db.session.add(e)
    db.session.commit()
    flash("Equipment added.", "success")
    return redirect(url_for("admin.contract", contract_id=c.id))


@admin_bp.route("/equipment/<int:equip_id>/refill", methods=["POST"])
@login_required
@staff_required
def add_refill(equip_id):
    e = db.session.get(Equipment, equip_id) or abort(404)
    f = request.form
    rdate = datetime.strptime(f.get("refill_date"), "%Y-%m-%d").date() \
        if f.get("refill_date") else date.today()
    db.session.add(RefillRecord(equipment_id=e.id, refill_date=rdate,
                                performed_by=f.get("performed_by") or current_user.name,
                                notes=f.get("notes")))
    e.last_refill_date = rdate
    e.recompute_next_refill()
    db.session.commit()
    notify(e.contract.customer_id, "Equipment refilled",
           f"{e.name} was refilled on {rdate.strftime('%d %b %Y')}. "
           f"Next due {e.next_refill_date.strftime('%d %b %Y') if e.next_refill_date else 'TBD'}.",
           link=url_for("portal.contract", contract_id=e.contract_id))
    flash("Refill recorded and next-due date updated.", "success")
    return redirect(url_for("admin.contract", contract_id=e.contract_id))


# --------------------------------------------------------------------------- #
# Quotations
# --------------------------------------------------------------------------- #
@admin_bp.route("/contract/<int:contract_id>/quotation/new", methods=["GET", "POST"])
@login_required
@staff_required
def new_quotation(contract_id):
    c = db.session.get(Contract, contract_id) or abort(404)
    if request.method == "POST":
        f = request.form
        q = Quotation(contract_id=c.id, notes=f.get("notes"), status="pending")
        if f.get("visit_id"):
            q.visit_id = int(f.get("visit_id"))
        db.session.add(q)
        db.session.flush()
        descs = request.form.getlist("item_desc")
        qtys = request.form.getlist("item_qty")
        prices = request.form.getlist("item_price")
        for d, qty, pr in zip(descs, qtys, prices):
            if d.strip():
                db.session.add(QuotationItem(
                    quotation_id=q.id, description=d.strip(),
                    quantity=int(qty or 1), unit_price=int(pr or 0)))
        db.session.commit()
        notify(c.customer_id, "New quotation for approval",
               f"Quotation {q.reference} (₹{q.total:,.0f}) is ready for your review.",
               link=url_for("portal.quotation", quote_id=q.id))
        flash(f"Quotation {q.reference} created and sent to the customer.", "success")
        return redirect(url_for("admin.contract", contract_id=c.id))
    return render_template("admin/new_quotation.html", c=c)


# --------------------------------------------------------------------------- #
# Wave 6 — Fire System Health Checkup Report (FSHCR)
# --------------------------------------------------------------------------- #
def _collect_health_payload(f):
    """Build the JSON answer payload from a submitted health-report form."""
    import json as _json
    payload = {}
    for _title, qs in HealthCheckReport.SECTIONS:
        for key, _label in qs:
            payload[key] = f.get(key, "")
    for key, _label, has_count in HealthCheckReport.HYDRANT_ITEMS:
        payload[key] = f.get(key, "")
        if has_count:
            payload[key + "_nos"] = f.get(key + "_nos", "")
    for key, _label in HealthCheckReport.PARTICULARS:
        payload[key] = f.get(key, "")
    for key, _label in HealthCheckReport.EXTRAS:
        payload[key] = f.get(key, "")
    payload["ex_other"] = f.get("ex_other", "")
    payload["remarks"] = f.get("remarks", "")
    # Floor-wise table — JSON string built client-side
    floors_raw = f.get("floors_json", "")
    try:
        payload["floors"] = _json.loads(floors_raw) if floors_raw else []
    except (ValueError, TypeError):
        payload["floors"] = []
    return payload


@admin_bp.route("/health-reports")
@login_required
@staff_required
def health_reports():
    reports = HealthCheckReport.query.order_by(
        HealthCheckReport.created_at.desc()).all()
    return render_template("admin/health_reports.html", reports=reports)


@admin_bp.route("/health-report/new", methods=["GET", "POST"])
@admin_bp.route("/health-report/<int:report_id>", methods=["GET", "POST"])
@login_required
@staff_required
def health_report(report_id=None):
    r = db.session.get(HealthCheckReport, report_id) if report_id else None
    if report_id and not r:
        abort(404)
    if request.method == "POST":
        f = request.form
        if r is None:
            r = HealthCheckReport(created_by_id=current_user.id)
            db.session.add(r)
        r.contract_id = f.get("contract_id") or None
        r.visit_id = f.get("visit_id") or None
        r.property_name = f.get("property_name", "").strip()
        r.property_address = f.get("property_address", "").strip()
        r.property_contact = f.get("property_contact", "").strip()
        r.inspector_name = f.get("inspector_name", "").strip() or current_user.name
        r.inspector_contact = f.get("inspector_contact", "").strip()
        if f.get("report_date"):
            r.report_date = datetime.strptime(f.get("report_date"), "%Y-%m-%d").date()
        r.status = f.get("status", "draft")
        r.set_answers(_collect_health_payload(f))
        # Optional scanned-copy upload (fallback when the app form isn't used)
        scan = request.files.get("scan")
        path = save_upload(scan, "health_reports", {"pdf", "png", "jpg", "jpeg"})
        if path:
            r.scan_path = path
        db.session.commit()
        # Notify the client when finalised and linked to their contract
        if r.status == "completed" and r.contract_id and r.contract and r.contract.customer_id:
            notify(r.contract.customer_id, "Fire Health Check report ready",
                   f"Your fire system health checkup report {r.reference} is available to view and download.",
                   link=url_for("portal.contract", contract_id=r.contract_id))
        flash(f"Health checkup report {r.reference} saved.", "success")
        return redirect(url_for("admin.health_report", report_id=r.id))

    cid = request.args.get("contract_id", type=int)
    vid = request.args.get("visit_id", type=int)
    contract = db.session.get(Contract, cid) if cid else None
    visit = db.session.get(Visit, vid) if vid else None
    if visit and not contract:
        contract = visit.contract
    contracts = Contract.query.order_by(Contract.id.desc()).all()
    return render_template("admin/health_report_form.html", r=r, model=HealthCheckReport,
                           contract=contract, visit=visit, contracts=contracts)


@admin_bp.route("/health-report/<int:report_id>/pdf")
@login_required
@staff_required
def health_report_pdf(report_id):
    from ..pdf_generator import generate_health_report_pdf
    import io as _io
    from flask import send_file
    r = db.session.get(HealthCheckReport, report_id) or abort(404)
    pdf = generate_health_report_pdf(r)
    if not pdf:
        abort(500)
    return send_file(_io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=True, download_name=f"{r.reference}.pdf")


# --------------------------------------------------------------------------- #
# Service requests (emergency / NOC)
# --------------------------------------------------------------------------- #
@admin_bp.route("/requests")
@login_required
@staff_required
def requests_list():
    rtype = request.args.get("type")
    q = ServiceRequest.query
    if rtype:
        q = q.filter_by(request_type=rtype)
    items = q.order_by(ServiceRequest.created_at.desc()).all()
    return render_template("admin/requests.html", requests=items, rtype=rtype)


@admin_bp.route("/request/<int:req_id>", methods=["GET", "POST"])
@login_required
@staff_required
def service_request(req_id):
    sr = db.session.get(ServiceRequest, req_id) or abort(404)
    techs = User.query.filter(User.role.in_(["technician", "admin"])).all()
    if request.method == "POST":
        f = request.form
        sr.status = f.get("status", sr.status)
        sr.team_eta = f.get("team_eta")
        sr.amount = int(f.get("amount") or 0)
        sr.payment_mode = f.get("payment_mode", sr.payment_mode)
        sr.payment_status = f.get("payment_status", sr.payment_status)
        if f.get("assigned_technician_id"):
            sr.assigned_technician_id = int(f.get("assigned_technician_id"))
        if f.get("scheduled_date"):
            sr.scheduled_date = datetime.strptime(f.get("scheduled_date"), "%Y-%m-%dT%H:%M")
        db.session.commit()
        if sr.customer_id:
            notify(sr.customer_id, f"{sr.reference} update",
                   f"Status: {sr.status}. ETA: {sr.team_eta or 'TBD'}.",
                   link=url_for("portal.requests_list"))
        flash("Service request updated.", "success")
        return redirect(url_for("admin.service_request", req_id=sr.id))
    attachments = FormAttachment.query.filter_by(
        ref_type="service_request", ref_id=req_id).all()
    return render_template("admin/request.html", sr=sr, techs=techs,
                           attachments=attachments)


# --------------------------------------------------------------------------- #
# Extinguisher refill orders
# --------------------------------------------------------------------------- #
@admin_bp.route("/refills")
@login_required
@staff_required
def refills_list():
    items = RefillOrder.query.order_by(RefillOrder.created_at.desc()).all()
    return render_template("admin/refills.html", orders=items)


@admin_bp.route("/refill/<int:order_id>", methods=["GET", "POST"])
@login_required
@staff_required
def refill_order(order_id):
    o = db.session.get(RefillOrder, order_id) or abort(404)
    if request.method == "POST":
        f = request.form
        o.status = f.get("status", o.status)
        o.team_eta = f.get("team_eta")
        o.amount = int(f.get("amount") or 0)
        o.payment_mode = f.get("payment_mode", o.payment_mode)
        o.payment_status = f.get("payment_status", o.payment_status)
        if f.get("scheduled_date"):
            o.scheduled_date = datetime.strptime(f.get("scheduled_date"), "%Y-%m-%dT%H:%M")
        db.session.commit()
        if o.customer_id:
            notify(o.customer_id, f"{o.reference} update",
                   f"Status: {o.status}. ETA: {o.team_eta or 'TBD'}.",
                   link=url_for("portal.dashboard"))
        flash("Refill order updated.", "success")
        return redirect(url_for("admin.refill_order", order_id=o.id))
    return render_template("admin/refill.html", o=o)


# --------------------------------------------------------------------------- #
# Enquiries
# --------------------------------------------------------------------------- #
@admin_bp.route("/enquiries")
@login_required
@staff_required
def enquiries():
    items = Enquiry.query.order_by(Enquiry.created_at.desc()).all()
    return render_template("admin/enquiries.html", enquiries=items)


@admin_bp.route("/enquiry/<int:enq_id>/respond", methods=["POST"])
@login_required
@staff_required
def respond_enquiry(enq_id):
    e = db.session.get(Enquiry, enq_id) or abort(404)
    e.status = "responded"
    db.session.commit()
    flash("Marked as responded.", "success")
    return redirect(url_for("admin.enquiries"))


# --------------------------------------------------------------------------- #
# Technician performance dashboard
# --------------------------------------------------------------------------- #
@admin_bp.route("/technician-performance")
@login_required
@staff_required
def technician_performance():
    techs = User.query.filter(User.role.in_(["technician", "admin"])).all()

    stats = []
    for t in techs:
        # All visits assigned to this technician
        all_visits = Visit.query.filter_by(technician_id=t.id).all()
        completed  = [v for v in all_visits if v.status == "completed"]
        pending    = [v for v in all_visits if v.status in ("scheduled", "in_progress")]

        # On-time: completed_date <= scheduled_date (or no scheduled_date)
        on_time = sum(
            1 for v in completed
            if v.scheduled_date and v.completed_date and v.completed_date <= v.scheduled_date
        )

        # Feedback ratings
        feedbacks = VisitFeedback.query.filter_by(
            technician_id=t.id
        ).filter(VisitFeedback.rating_overall != None).all()  # noqa: E711

        avg_overall    = round(sum(f.rating_overall    for f in feedbacks) / len(feedbacks), 1) if feedbacks else None
        avg_quality    = round(sum(f.rating_quality    for f in feedbacks) / len(feedbacks), 1) if feedbacks else None
        avg_behaviour  = round(sum(f.rating_behaviour  for f in feedbacks) / len(feedbacks), 1) if feedbacks else None
        avg_punctuality= round(sum(f.rating_punctuality for f in feedbacks) / len(feedbacks), 1) if feedbacks else None
        avg_communication = round(sum(f.rating_communication for f in feedbacks) / len(feedbacks), 1) if feedbacks else None

        on_time_pct = round(on_time / len(completed) * 100) if completed else None

        stats.append({
            "tech": t,
            "total_visits": len(all_visits),
            "completed": len(completed),
            "pending": len(pending),
            "on_time": on_time,
            "on_time_pct": on_time_pct,
            "feedback_count": len(feedbacks),
            "avg_overall": avg_overall,
            "avg_quality": avg_quality,
            "avg_behaviour": avg_behaviour,
            "avg_punctuality": avg_punctuality,
            "avg_communication": avg_communication,
        })

    # Sort by avg overall rating desc, then by completed visits
    stats.sort(key=lambda s: (s["avg_overall"] or 0, s["completed"]), reverse=True)

    return render_template("admin/technician_performance.html", stats=stats)


# --------------------------------------------------------------------------- #
# Trigger feedback email (called after visit marked completed)
# --------------------------------------------------------------------------- #
def _trigger_feedback(visit: Visit) -> None:
    """Create a VisitFeedback stub and send the feedback email to the customer."""
    import secrets
    if not visit.contract or not visit.contract.customer_id:
        return
    # Don't create a second one if already exists
    if VisitFeedback.query.filter_by(visit_id=visit.id).first():
        return

    token = secrets.token_urlsafe(32)
    fb = VisitFeedback(
        visit_id=visit.id,
        customer_id=visit.contract.customer_id,
        technician_id=visit.technician_id,
        token=token,
    )
    db.session.add(fb)
    db.session.flush()

    # Build the full URL for the email
    from flask import url_for
    feedback_url = url_for("public.visit_feedback", token=token, _external=True)
    send_feedback_request(visit, token)


# ─────────────────────────────────────────────────────────────────
# Wave 6 — Financial dashboard (contract + visit-quote payments)
# ─────────────────────────────────────────────────────────────────
@admin_bp.route("/financials")
@login_required
@staff_required
def financials():
    """Contract-wise payment tracking: the AMC fee plus every visit-linked
    material quotation, each with paid/unpaid status and date."""
    contracts = Contract.query.filter(Contract.status.in_(["active", "expired"]))\
        .order_by(Contract.created_at.desc()).all()
    rows = []
    tot_contract_billed = tot_contract_paid = 0
    tot_quote_billed = tot_quote_paid = 0
    for c in contracts:
        vquotes = [q for q in c.quotations if q.visit_id and q.status == "approved"]
        c_paid = c.payment_status == "paid"
        tot_contract_billed += c.price or 0
        if c_paid:
            tot_contract_paid += c.price or 0
        q_billed = sum(q.total for q in vquotes)
        q_paid = sum(q.total for q in vquotes if q.is_paid)
        tot_quote_billed += q_billed
        tot_quote_paid += q_paid
        rows.append({"c": c, "c_paid": c_paid, "vquotes": vquotes,
                     "q_billed": q_billed, "q_paid": q_paid})
    totals = {
        "contract_billed": tot_contract_billed, "contract_paid": tot_contract_paid,
        "quote_billed": tot_quote_billed, "quote_paid": tot_quote_paid,
        "grand_billed": tot_contract_billed + tot_quote_billed,
        "grand_paid": tot_contract_paid + tot_quote_paid,
        "outstanding": (tot_contract_billed + tot_quote_billed)
                       - (tot_contract_paid + tot_quote_paid),
    }
    return render_template("admin/financials.html", rows=rows, totals=totals)


# ─────────────────────────────────────────────────────────────────
# Wave 3 — Visit Calendar
# ─────────────────────────────────────────────────────────────────

@admin_bp.route("/calendar")
@login_required
@staff_required
def calendar():
    """Monthly calendar view of all scheduled visits."""
    import calendar as _cal
    year  = request.args.get("year",  type=int, default=date.today().year)
    month = request.args.get("month", type=int, default=date.today().month)
    # Clamp
    if month < 1:  month = 12; year -= 1
    if month > 12: month = 1;  year += 1

    first_day = date(year, month, 1)
    last_day  = date(year, month, _cal.monthrange(year, month)[1])

    visits = (Visit.query
              .filter(Visit.scheduled_date >= first_day,
                      Visit.scheduled_date <= last_day)
              .order_by(Visit.scheduled_date)
              .all())

    # Group by day number
    by_day = {}
    for v in visits:
        day = v.scheduled_date.day
        by_day.setdefault(day, []).append(v)

    # Build calendar grid (list of weeks, each week = 7 day numbers / 0=blank)
    cal_grid = _cal.monthcalendar(year, month)
    month_name = first_day.strftime("%B %Y")
    prev_month = (month - 1) or 12
    prev_year  = year - 1 if month == 1 else year
    next_month = (month % 12) + 1
    next_year  = year + 1 if month == 12 else year

    return render_template("admin/calendar.html",
                           cal_grid=cal_grid, by_day=by_day,
                           month_name=month_name, year=year, month=month,
                           prev_month=prev_month, prev_year=prev_year,
                           next_month=next_month, next_year=next_year)


# ─────────────────────────────────────────────────────────────────
# Wave 3 — Analytics Dashboard
# ─────────────────────────────────────────────────────────────────

@admin_bp.route("/analytics")
@login_required
@staff_required
def analytics():
    """KPI analytics: contract revenue, visit completion, equipment health."""
    from sqlalchemy import func
    total_contracts  = Contract.query.count()
    active_contracts = Contract.query.filter_by(status="active").count()
    pending          = Contract.query.filter_by(status="pending").count()
    total_revenue    = db.session.query(func.sum(Contract.price))\
                         .filter(Contract.status.in_(["active", "expired"])).scalar() or 0
    total_visits     = Visit.query.count()
    completed_visits = Visit.query.filter_by(status="completed").count()
    completion_rate  = round(completed_visits / total_visits * 100) if total_visits else 0
    overdue_equip    = Equipment.query.filter(
                         Equipment.next_refill_date < date.today()).count()
    total_customers  = User.query.filter_by(role="customer").count()
    open_emergencies = ServiceRequest.query.filter(
                         ServiceRequest.request_type == "emergency",
                         ServiceRequest.status.notin_(["resolved", "closed"])).count()
    open_refills     = RefillOrder.query.filter(
                         RefillOrder.status.notin_(["completed", "cancelled"])).count()

    # Monthly contract activations (last 6 months)
    from datetime import datetime as _dt
    monthly = []
    for i in range(5, -1, -1):
        mo = date.today().replace(day=1)
        for _ in range(i):
            mo = (mo - timedelta(days=1)).replace(day=1)
        nxt = date(mo.year + (mo.month // 12), (mo.month % 12) + 1, 1)
        count = Contract.query.filter(
            Contract.created_at >= _dt.combine(mo, _dt.min.time()),
            Contract.created_at <  _dt.combine(nxt, _dt.min.time()),
        ).count()
        monthly.append({"label": mo.strftime("%b %Y"), "count": count})

    return render_template("admin/analytics.html",
                           total_contracts=total_contracts,
                           active_contracts=active_contracts,
                           pending=pending,
                           total_revenue=total_revenue,
                           completion_rate=completion_rate,
                           completed_visits=completed_visits,
                           total_visits=total_visits,
                           overdue_equip=overdue_equip,
                           total_customers=total_customers,
                           open_emergencies=open_emergencies,
                           open_refills=open_refills,
                           monthly=monthly)
