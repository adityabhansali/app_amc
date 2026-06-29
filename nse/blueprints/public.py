from flask import (Blueprint, render_template, request, redirect, url_for, flash)
from flask_login import current_user

from ..extensions import db
from ..models import (AMCPlan, Contract, ServiceRequest, Enquiry, User,
                      RefillOrder, RefillItem, FormAttachment, VisitFeedback,
                      CustomerJourneyEvent, ServiceQuotation, ServiceQuotationItem)
from ..utils import notify, save_upload

public_bp = Blueprint("public", __name__)


def _save_attachments(files, ref_type, ref_id, att_type="photo"):
    """Save a list of FileStorage objects as FormAttachment rows."""
    for f in files:
        if not f or not f.filename:
            continue
        path = save_upload(f, f"form/{ref_type}/{ref_id}",
                           {"png", "jpg", "jpeg", "gif", "webp", "pdf"})
        if path:
            db.session.add(FormAttachment(
                ref_type=ref_type, ref_id=ref_id,
                file_path=path, attachment_type=att_type))


@public_bp.route("/")
def home():
    plans = AMCPlan.query.filter_by(active=True).order_by(AMCPlan.price).all()
    return render_template("public/home.html", plans=plans)


@public_bp.route("/plans")
def plans():
    residential = AMCPlan.query.filter_by(active=True, category="residential").order_by(AMCPlan.price).all()
    commercial = AMCPlan.query.filter_by(active=True, category="commercial").order_by(AMCPlan.price).all()
    return render_template("public/plans.html", residential=residential, commercial=commercial)


@public_bp.route("/apply", methods=["GET", "POST"])
def apply():
    plans = AMCPlan.query.filter_by(active=True).order_by(AMCPlan.category, AMCPlan.price).all()
    if request.method == "POST":
        f = request.form
        plan = db.session.get(AMCPlan, int(f.get("plan_id"))) if f.get("plan_id") else None
        # Merge voice note into notes (prepend so staff see it clearly)
        voice = (f.get("voice_note") or "").strip()
        notes = (f.get("notes") or "").strip()
        combined_notes = (f"[Voice note] {voice}\n\n{notes}".strip() if voice else notes) or None
        contract = Contract(
            plan_id=plan.id if plan else None,
            status="pending",
            site_name=f.get("site_name"),
            site_address=f.get("site_address"),
            area=f.get("area"),
            applicant_name=f.get("name"),
            applicant_phone=f.get("phone"),
            applicant_email=f.get("email"),
            property_type=f.get("property_type"),
            application_notes=combined_notes,
            voice_note=voice or None,
            total_visits=plan.visits_per_year if plan else 4,
            price=plan.price if plan else 0,
            payment_mode=f.get("payment_mode", "cash"),
        )
        existing = User.query.filter_by(phone=f.get("phone"), role="customer").first()
        if existing:
            contract.customer_id = existing.id
        db.session.add(contract)
        db.session.commit()

        # Save uploaded site photos
        _save_attachments(request.files.getlist("site_photos"), "contract", contract.id, "photo")

        # ── Auto-generate a ServiceQuotation so customer can view it immediately ──
        sq_ref = None
        if plan:
            from datetime import datetime as _dt
            sq = ServiceQuotation(
                service_type="amc",
                customer_name=f.get("name"),
                customer_phone=f.get("phone"),
                customer_email=f.get("email") or None,
                project_name=f.get("site_name") or None,
                customer_address=f.get("site_address") or None,
                status="sent",
                sent_at=_dt.utcnow(),
                contract_id=contract.id,
                customer_id=existing.id if existing else None,
                gst_percent=18.0,
                valid_days=7,
                notes=f"Property type: {f.get('property_type') or 'Not specified'}",
            )
            sq.generate_number()
            db.session.add(sq)
            db.session.flush()   # need sq.id before adding items

            # Build the description from plan features if available
            feature_lines = plan.feature_list[:4] if plan.feature_list else []
            detail = (
                f"{plan.visits_per_year} maintenance visits/year | "
                f"{plan.response_time} response time"
            )
            if feature_lines:
                detail += " | " + " | ".join(feature_lines)

            db.session.add(ServiceQuotationItem(
                quotation_id=sq.id,
                category="AMC Services",
                description=f"{plan.name} — Annual Maintenance Contract\n{detail}",
                unit="Year",
                quantity=1.0,
                rate=float(plan.price),
                sort_order=1,
            ))

            # Log journey event if customer already has an account
            if existing:
                db.session.add(CustomerJourneyEvent(
                    customer_id=existing.id,
                    event_type="quote_sent",
                    description=f"Quotation {sq.quotation_number} auto-generated for {plan.name}",
                    ref_type="service_quotation", ref_id=sq.id,
                ))
                notify(existing.id,
                       f"Your quotation {sq.quotation_number} is ready",
                       f"View and accept or negotiate your {plan.name} AMC quote in the portal.",
                       link=url_for("portal.service_quotation", sq_id=sq.id))

            sq_ref = sq.quotation_number

        db.session.commit()

        if sq_ref:
            msg = ("Your quotation has been prepared based on your selected plan. "
                   "Log in with your phone number to view it, accept the price, "
                   "or request a negotiation.")
        else:
            msg = ("Our maintenance team will review your application and "
                   "call you to confirm the schedule and activate your contract.")

        return render_template("public/submitted.html",
                               kind="AMC application", reference=contract.reference,
                               sq_ref=sq_ref, message=msg)
    selected = request.args.get("plan_id", type=int)
    return render_template("public/apply.html", plans=plans, selected=selected)


@public_bp.route("/emergency", methods=["GET", "POST"])
def emergency():
    if request.method == "POST":
        f = request.form
        sr = ServiceRequest(
            request_type="emergency",
            name=f.get("name"),
            phone=f.get("phone"),
            email=f.get("email"),
            area=f.get("area"),
            location=f.get("location"),
            description=f.get("description"),
            payment_mode=f.get("payment_mode", "cash"),
            status="new",
        )
        existing = User.query.filter_by(phone=f.get("phone"), role="customer").first()
        if existing:
            sr.customer_id = existing.id
        db.session.add(sr)
        db.session.commit()
        return render_template("public/submitted.html",
                               kind="Emergency visit request", reference=sr.reference,
                               message="Our Fire Emergency Response team has been alerted. "
                                       "We will call you shortly with the team's ETA. For an "
                                       "immediate response, please also call our hotline.")
    return render_template("public/emergency.html")


@public_bp.route("/noc", methods=["GET", "POST"])
def noc():
    if request.method == "POST":
        f = request.form
        # Voice note merges into description
        voice = (f.get("voice_note") or "").strip()
        desc = (f.get("description") or "").strip()
        combined_desc = (f"[Voice note] {voice}\n\n{desc}".strip() if voice else desc) or None
        sr = ServiceRequest(
            request_type="noc",
            name=f.get("name"),
            phone=f.get("phone"),
            email=f.get("email"),
            area=f.get("area"),
            location=f.get("location"),
            description=combined_desc,
            voice_note=voice or None,
            payment_mode=f.get("payment_mode", "cash"),
            status="new",
        )
        db.session.add(sr)
        db.session.commit()
        # Old NOC document upload
        noc_doc = request.files.get("noc_document")
        if noc_doc and noc_doc.filename:
            path = save_upload(noc_doc, f"form/service_request/{sr.id}",
                               {"pdf", "png", "jpg", "jpeg"})
            if path:
                sr.noc_document_path = path
        # Site photos
        _save_attachments(request.files.getlist("site_photos"),
                          "service_request", sr.id, "photo")
        db.session.commit()
        return render_template("public/submitted.html",
                               kind="NOC request", reference=sr.reference,
                               message="Our team will review your NOC requirement and get back "
                                       "to you with the documents and process needed.")
    return render_template("public/noc.html")


@public_bp.route("/refill", methods=["GET", "POST"])
def refill():
    if request.method == "POST":
        f = request.form
        order = RefillOrder(
            name=f.get("name"), phone=f.get("phone"), email=f.get("email"),
            area=f.get("area"), address=f.get("address"),
            service_mode=f.get("service_mode", "onsite"),
            payment_mode=f.get("payment_mode", "cash"),
            notes=f.get("notes"), status="new",
        )
        existing = User.query.filter_by(phone=f.get("phone"), role="customer").first()
        if existing:
            order.customer_id = existing.id
        types = f.getlist("item_type")
        caps = f.getlist("item_capacity")
        qtys = f.getlist("item_qty")
        for i, t in enumerate(types):
            t = (t or "").strip()
            if not t:
                continue
            cap = (caps[i].strip() if i < len(caps) else "")
            try:
                qty = int(qtys[i]) if i < len(qtys) and qtys[i] else 1
            except (ValueError, TypeError):
                qty = 1
            order.items.append(RefillItem(ext_type=t, capacity=cap, quantity=max(1, qty)))
        if not order.items:
            flash("Please add at least one extinguisher to refill.", "warning")
            return render_template("public/refill.html")
        db.session.add(order)
        db.session.commit()
        return render_template(
            "public/submitted.html", kind="Refill booking", reference=order.reference,
            message="Your extinguisher refill is booked. Our team will call to confirm "
                    "pickup/visit timing and the final amount after inspection.")
    return render_template("public/refill.html")


@public_bp.route("/enquiry", methods=["GET", "POST"])
def enquiry():
    if request.method == "POST":
        f = request.form
        e = Enquiry(
            name=f.get("name"), phone=f.get("phone"), email=f.get("email"),
            subject=f.get("subject"), message=f.get("message"),
        )
        db.session.add(e)
        db.session.commit()
        flash("Thanks! Your question has been sent — our team will reply soon.", "success")
        return redirect(url_for("public.enquiry"))
    return render_template("public/enquiry.html")


@public_bp.route("/faq")
def faq():
    return render_template("public/faq.html")


@public_bp.route("/about")
def about():
    return render_template("public/about.html")


@public_bp.route("/qr")
def qr():
    """Wave 3 — mobile QR code page: scan to open the app on any phone on the same WiFi."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"
    from flask import current_app
    port = current_app.config.get("PORT", 5055)
    url  = f"http://{local_ip}:{port}"
    return render_template("public/qr.html", url=url, local_ip=local_ip, port=port)


# ─────────────────────────────────────────────────────────────────
# Post-visit feedback (token-based, no login required)
# ─────────────────────────────────────────────────────────────────

@public_bp.route("/feedback/<token>", methods=["GET", "POST"])
def visit_feedback(token):
    fb = VisitFeedback.query.filter_by(token=token).first_or_404()

    if fb.is_submitted:
        return render_template("public/feedback_done.html", fb=fb)

    if request.method == "POST":
        f = request.form
        try:
            fb.rating_behaviour     = int(f.get("rating_behaviour", 0))
            fb.rating_quality       = int(f.get("rating_quality", 0))
            fb.rating_punctuality   = int(f.get("rating_punctuality", 0))
            fb.rating_communication = int(f.get("rating_communication", 0))
            fb.rating_overall       = int(f.get("rating_overall", 0))
            fb.comment = f.get("comment", "").strip()
        except (ValueError, TypeError):
            flash("Please rate all dimensions.", "danger")
            return redirect(url_for("public.visit_feedback", token=token))

        # Log journey event
        if fb.customer_id:
            db.session.add(CustomerJourneyEvent(
                customer_id=fb.customer_id,
                event_type="feedback_given",
                description=f"Feedback submitted for {fb.visit.label} — Overall: {fb.rating_overall}/5",
                ref_type="visit", ref_id=fb.visit_id,
            ))

        db.session.commit()
        return render_template("public/feedback_done.html", fb=fb)

    return render_template("public/feedback_form.html", fb=fb)
