from datetime import datetime, date, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort)
from flask_login import login_required, current_user

from ..extensions import db
from ..models import (User, AMCPlan, Contract, Visit, VisitPhoto, Equipment,
                      RefillRecord, Quotation, QuotationItem, ServiceRequest,
                      Payment, Enquiry)
from ..utils import staff_required, save_upload, notify

admin_bp = Blueprint("admin", __name__, url_prefix="/ops")


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
    return render_template("admin/dashboard.html",
                           pending_apps=pending_apps, active=active,
                           open_emergencies=open_emergencies, open_noc=open_noc,
                           new_enquiries=new_enquiries, upcoming=upcoming,
                           due_refills=due_refills[:10])


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
    return render_template("admin/contract.html", c=c, techs=techs)


@admin_bp.route("/contract/<int:contract_id>/activate", methods=["POST"])
@login_required
@staff_required
def activate_contract(contract_id):
    c = db.session.get(Contract, contract_id) or abort(404)
    f = request.form
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
    c.price = int(f.get("price") or c.price or 0)
    c.status = "active"

    # Generate evenly-spaced scheduled visits across the year.
    if not c.visits:
        interval = max(1, 365 // n_visits)
        for i in range(n_visits):
            db.session.add(Visit(contract_id=c.id, visit_number=i + 1,
                                 scheduled_date=start + timedelta(days=interval * i),
                                 status="scheduled"))
    db.session.commit()
    notify(c.customer_id, "AMC activated",
           f"Your contract {c.reference} is active with {n_visits} scheduled visits.")
    flash(f"Contract {c.reference} activated with {n_visits} visits.", "success")
    return redirect(url_for("admin.contract", contract_id=c.id))


@admin_bp.route("/contract/<int:contract_id>/payment", methods=["POST"])
@login_required
@staff_required
def contract_payment(contract_id):
    c = db.session.get(Contract, contract_id) or abort(404)
    c.payment_status = request.form.get("payment_status", c.payment_status)
    c.payment_mode = request.form.get("payment_mode", c.payment_mode)
    db.session.commit()
    flash("Payment status updated.", "success")
    return redirect(url_for("admin.contract", contract_id=c.id))


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
            v.scheduled_date = datetime.strptime(f.get("scheduled_date"), "%Y-%m-%d").date()
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
        db.session.commit()
        if v.status == "completed":
            notify(v.contract.customer_id, f"{v.label} completed",
                   f"Service report and photos are now available for {v.contract.reference}.")
        flash("Visit updated.", "success")
        return redirect(url_for("admin.visit", visit_id=v.id))
    return render_template("admin/visit.html", v=v, techs=techs)


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
           f"Next due {e.next_refill_date.strftime('%d %b %Y') if e.next_refill_date else 'TBD'}.")
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
               f"Quotation {q.reference} (₹{q.total:,.0f}) is ready for your review.")
        flash(f"Quotation {q.reference} created and sent to the customer.", "success")
        return redirect(url_for("admin.contract", contract_id=c.id))
    return render_template("admin/new_quotation.html", c=c)


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
                   f"Status: {sr.status}. ETA: {sr.team_eta or 'TBD'}.")
        flash("Service request updated.", "success")
        return redirect(url_for("admin.service_request", req_id=sr.id))
    return render_template("admin/request.html", sr=sr, techs=techs)


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
