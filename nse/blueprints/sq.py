"""
nse/blueprints/sq.py  — Service Quotations blueprint  (/ops/sq/*)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Handles the full lifecycle of sales quotations for all service types
(AMC / NOC / Refilling / Emergency).

This is distinct from the existing Quotation model (which handles
material-replacement quotes during active AMC visits).
"""
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, abort, send_file, current_app)
from flask_login import login_required, current_user

from ..extensions import db
from ..models import (ServiceQuotation, ServiceQuotationItem,
                      CustomerJourneyEvent, User, Contract,
                      RefillOrder, ServiceRequest, InventoryItem)
from ..utils import staff_required, notify
from ..pdf_generator import generate_quotation_pdf
from ..email_service import (send_quotation_email, send_quote_accepted_alert,
                              send_negotiation_alert)
import io

sq_bp = Blueprint("sq", __name__, url_prefix="/ops/sq")


# ─────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────

def _log_event(customer_id, event_type, description, ref_type=None, ref_id=None):
    if not customer_id:
        return
    ev = CustomerJourneyEvent(
        customer_id=customer_id,
        event_type=event_type,
        description=description,
        ref_type=ref_type,
        ref_id=ref_id,
        created_by_id=current_user.id if current_user.is_authenticated else None,
    )
    db.session.add(ev)


# ─────────────────────────────────────────────────────────────────
# List
# ─────────────────────────────────────────────────────────────────

@sq_bp.route("/")
@login_required
@staff_required
def list_quotations():
    status_filter = request.args.get("status", "")
    stype_filter  = request.args.get("stype", "")

    q = ServiceQuotation.query.order_by(ServiceQuotation.created_at.desc())
    if status_filter:
        q = q.filter(ServiceQuotation.status == status_filter)
    if stype_filter:
        q = q.filter(ServiceQuotation.service_type == stype_filter)

    quotations = q.all()
    return render_template("admin/sq_list.html",
                           quotations=quotations,
                           status_filter=status_filter,
                           stype_filter=stype_filter)


# ─────────────────────────────────────────────────────────────────
# New
# ─────────────────────────────────────────────────────────────────

@sq_bp.route("/new", methods=["GET", "POST"])
@login_required
@staff_required
def new_quotation():
    # Pre-fill from linked records if ?contract_id=X / ?sr_id=X / ?ro_id=X
    contract = db.session.get(Contract, request.args.get("contract_id", type=int))
    sr       = db.session.get(ServiceRequest, request.args.get("sr_id", type=int))
    ro       = db.session.get(RefillOrder,    request.args.get("ro_id", type=int))

    if request.method == "POST":
        f = request.form
        sq = ServiceQuotation(
            service_type     = f.get("service_type", "amc"),
            customer_name    = f.get("customer_name", "").strip(),
            customer_phone   = f.get("customer_phone", "").strip(),
            customer_email   = f.get("customer_email", "").strip(),
            project_name     = f.get("project_name", "").strip(),
            customer_address = f.get("customer_address", "").strip(),
            gst_percent      = float(f.get("gst_percent") or 18),
            valid_days       = int(f.get("valid_days") or 7),
            notes            = f.get("notes", "").strip(),
            contract_id      = f.get("contract_id") or None,
            refill_order_id  = f.get("refill_order_id") or None,
            service_request_id = f.get("service_request_id") or None,
            created_by_id    = current_user.id,
            status           = "draft",
        )
        # Link to customer User if email matches
        if sq.customer_email:
            cu = User.query.filter_by(email=sq.customer_email, role="customer").first()
            if cu:
                sq.customer_id = cu.id

        sq.generate_number()
        db.session.add(sq)
        db.session.flush()

        # Parse line items (dynamic rows)
        descs     = f.getlist("item_desc")
        cats      = f.getlist("item_category")
        units     = f.getlist("item_unit")
        qtys      = f.getlist("item_qty")
        rates     = f.getlist("item_rate")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            item = ServiceQuotationItem(
                quotation_id = sq.id,
                category     = cats[i] if i < len(cats) else "General",
                description  = desc.strip(),
                unit         = units[i] if i < len(units) else "Job",
                quantity     = float(qtys[i] or 1) if i < len(qtys) else 1,
                rate         = float(rates[i] or 0) if i < len(rates) else 0,
                sort_order   = i,
            )
            db.session.add(item)

        _log_event(sq.customer_id, "quote_requested",
                   f"Quotation {sq.reference} created (draft)",
                   "service_quotation", sq.id)
        db.session.commit()
        flash(f"Quotation {sq.reference} created.", "success")
        return redirect(url_for("sq.detail_quotation", sq_id=sq.id))

    inventory = InventoryItem.query.filter_by(active=True)\
        .order_by(InventoryItem.category, InventoryItem.name).all()
    return render_template("admin/sq_new.html",
                           contract=contract, sr=sr, ro=ro,
                           inventory=inventory)


# ─────────────────────────────────────────────────────────────────
# Detail / Edit
# ─────────────────────────────────────────────────────────────────

@sq_bp.route("/<int:sq_id>", methods=["GET", "POST"])
@login_required
@staff_required
def detail_quotation(sq_id):
    sq = db.session.get(ServiceQuotation, sq_id) or abort(404)

    if request.method == "POST":
        action = request.form.get("action", "save")

        if action == "save" and sq.is_editable:
            f = sq
            sq.customer_name    = request.form.get("customer_name", sq.customer_name).strip()
            sq.customer_phone   = request.form.get("customer_phone", sq.customer_phone or "").strip()
            sq.customer_email   = request.form.get("customer_email", sq.customer_email or "").strip()
            sq.project_name     = request.form.get("project_name", sq.project_name or "").strip()
            sq.customer_address = request.form.get("customer_address", sq.customer_address or "").strip()
            sq.gst_percent      = float(request.form.get("gst_percent") or sq.gst_percent)
            sq.valid_days       = int(request.form.get("valid_days") or sq.valid_days)
            sq.notes            = request.form.get("notes", sq.notes or "").strip()

            # Replace all items
            for item in sq.items:
                db.session.delete(item)
            db.session.flush()

            descs = request.form.getlist("item_desc")
            cats  = request.form.getlist("item_category")
            units = request.form.getlist("item_unit")
            qtys  = request.form.getlist("item_qty")
            rates = request.form.getlist("item_rate")

            for i, desc in enumerate(descs):
                if not desc.strip():
                    continue
                db.session.add(ServiceQuotationItem(
                    quotation_id = sq.id,
                    category     = cats[i] if i < len(cats) else "General",
                    description  = desc.strip(),
                    unit         = units[i] if i < len(units) else "Job",
                    quantity     = float(qtys[i] or 1) if i < len(qtys) else 1,
                    rate         = float(rates[i] or 0) if i < len(rates) else 0,
                    sort_order   = i,
                ))
            db.session.commit()
            flash("Quotation updated.", "success")

        elif action == "send":
            # Generate PDF and email to customer
            pdf = generate_quotation_pdf(sq)
            if pdf and sq.customer_email:
                send_quotation_email(sq, pdf)
                sq.status = "sent"
                sq.sent_at = datetime.utcnow()
                if sq.customer_id:
                    notify(sq.customer_id, f"Quotation {sq.reference} sent",
                           f"Your quotation for {sq.project_name or sq.service_type.upper()} is ready.",
                           link=url_for("portal.service_quotation", sq_id=sq.id))
                _log_event(sq.customer_id, "quote_sent",
                           f"Quotation {sq.reference} emailed to {sq.customer_email}",
                           "service_quotation", sq.id)
                db.session.commit()
                flash(f"Quotation emailed to {sq.customer_email}.", "success")
            elif pdf:
                sq.status = "sent"
                sq.sent_at = datetime.utcnow()
                db.session.commit()
                flash("Quotation marked as sent (no email — no customer email on file).", "warning")
            else:
                flash("PDF generation failed. Check server logs.", "danger")

        elif action == "respond_negotiation":
            sq.staff_response = request.form.get("staff_response", "").strip()
            db.session.commit()
            flash("Response saved.", "success")

        elif action == "revise_send":
            # Revise line-item rates in place and re-send to the customer for a
            # fresh acceptance. Used to settle a negotiation_requested quote.
            sq.staff_response = request.form.get("staff_response", sq.staff_response or "").strip()
            for item in sq.items:
                raw = request.form.get(f"rate_{item.id}")
                if raw not in (None, ""):
                    try:
                        item.rate = float(raw)
                    except ValueError:
                        pass
            db.session.flush()
            pdf = generate_quotation_pdf(sq)
            sq.status = "sent"
            sq.sent_at = datetime.utcnow()
            sq.negotiation_note = None          # cleared; superseded by the revision
            if pdf and sq.customer_email:
                send_quotation_email(sq, pdf)
            if sq.customer_id:
                notify(sq.customer_id, f"Revised quotation {sq.reference}",
                       f"We've updated your quote to ₹{sq.grand_total:,.0f}. Please review and accept or reply.",
                       link=url_for("portal.service_quotation", sq_id=sq.id))
            _log_event(sq.customer_id, "quote_sent",
                       f"Revised quotation {sq.reference} re-sent (₹{sq.grand_total:,.0f})",
                       "service_quotation", sq.id)
            db.session.commit()
            flash(f"Revised quotation re-sent to the customer (₹{sq.grand_total:,.0f}).", "success")

        return redirect(url_for("sq.detail_quotation", sq_id=sq.id))

    journey = (CustomerJourneyEvent.query
               .filter_by(ref_type="service_quotation", ref_id=sq.id)
               .order_by(CustomerJourneyEvent.created_at.asc())
               .all()) if sq.customer_id else []

    return render_template("admin/sq_detail.html", sq=sq, journey=journey)


# ─────────────────────────────────────────────────────────────────
# PDF download
# ─────────────────────────────────────────────────────────────────

@sq_bp.route("/<int:sq_id>/pdf")
@login_required
@staff_required
def download_pdf(sq_id):
    sq = db.session.get(ServiceQuotation, sq_id) or abort(404)
    pdf = generate_quotation_pdf(sq)
    if not pdf:
        abort(500)
    return send_file(
        io.BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{sq.reference}.pdf",
    )
