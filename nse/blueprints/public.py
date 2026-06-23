from flask import (Blueprint, render_template, request, redirect, url_for, flash)
from flask_login import current_user

from ..extensions import db
from ..models import AMCPlan, Contract, ServiceRequest, Enquiry, User
from ..utils import notify

public_bp = Blueprint("public", __name__)


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
            application_notes=f.get("notes"),
            total_visits=plan.visits_per_year if plan else 4,
            price=plan.price if plan else 0,
            payment_mode=f.get("payment_mode", "cash"),
        )
        # Link to an existing customer account by phone if there is one.
        existing = User.query.filter_by(phone=f.get("phone"), role="customer").first()
        if existing:
            contract.customer_id = existing.id
        db.session.add(contract)
        db.session.commit()
        return render_template("public/submitted.html",
                               kind="AMC application", reference=contract.reference,
                               message="Our maintenance team will review your application and "
                                       "call you to confirm the schedule and activate your contract.")
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
        sr = ServiceRequest(
            request_type="noc",
            name=f.get("name"),
            phone=f.get("phone"),
            email=f.get("email"),
            area=f.get("area"),
            location=f.get("location"),
            description=f.get("description"),
            payment_mode=f.get("payment_mode", "cash"),
            status="new",
        )
        db.session.add(sr)
        db.session.commit()
        return render_template("public/submitted.html",
                               kind="NOC request", reference=sr.reference,
                               message="Our team will review your NOC requirement and get back "
                                       "to you with the documents and process needed.")
    return render_template("public/noc.html")


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
