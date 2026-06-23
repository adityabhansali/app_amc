from datetime import datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort, send_from_directory, current_app)
from flask_login import login_required, current_user

from ..extensions import db
from ..models import (Contract, Visit, Quotation, ServiceRequest, Payment,
                      Notification)
from ..utils import customer_required, notify

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
    pending_quotes = [q for c in contracts for q in c.quotations if q.status == "pending"]
    notes = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(10).all()
    return render_template("portal/dashboard.html", contracts=contracts,
                           requests=requests_, pending_quotes=pending_quotes, notes=notes)


@portal_bp.route("/contract/<int:contract_id>")
@login_required
@customer_required
def contract(contract_id):
    c = _own_contract(contract_id)
    return render_template("portal/contract.html", c=c)


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


@portal_bp.route("/quotation/<int:quote_id>")
@login_required
@customer_required
def quotation(quote_id):
    q = db.session.get(Quotation, quote_id)
    if not q or q.contract.customer_id != current_user.id:
        abort(404)
    return render_template("portal/quotation.html", q=q)


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
        flash("Quotation approved. Our team will schedule the replacement visit.", "success")
    elif decision == "reject":
        q.status = "rejected"
        q.decided_at = datetime.utcnow()
        flash("Quotation rejected. You can contact us if you change your mind.", "info")
    db.session.commit()
    return redirect(url_for("portal.contract", contract_id=q.contract_id))


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
