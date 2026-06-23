from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session, current_app)
from flask_login import login_user, logout_user, login_required, current_user

from ..extensions import db
from ..models import User
from ..utils import generate_otp, verify_otp

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _home_for(user):
    return url_for("admin.dashboard") if user.is_staff else url_for("portal.dashboard")


@auth_bp.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect(_home_for(current_user))
    return render_template("auth/login.html")


# --------------------------------------------------------------------------- #
# Customer login via phone OTP
# --------------------------------------------------------------------------- #
@auth_bp.route("/otp/request", methods=["POST"])
def otp_request():
    phone = (request.form.get("phone") or "").strip()
    if len(phone) < 8:
        flash("Please enter a valid phone number.", "danger")
        return redirect(url_for("auth.login"))
    code = generate_otp(phone)
    session["otp_phone"] = phone
    # Dev flow: surface the code on screen (replace with real SMS in production).
    dev_code = code if not current_app.config.get("AI_ENABLED_SMS") else None
    flash("OTP sent to your phone.", "info")
    return render_template("auth/verify.html", phone=phone, dev_code=dev_code)


@auth_bp.route("/otp/verify", methods=["POST"])
def otp_verify():
    phone = session.get("otp_phone") or request.form.get("phone")
    code = (request.form.get("code") or "").strip()
    name = (request.form.get("name") or "").strip()
    if not phone or not verify_otp(phone, code):
        flash("Invalid or expired OTP. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(phone=phone, role="customer").first()
    if not user:
        user = User(role="customer", phone=phone, name=name or f"Customer {phone[-4:]}")
        db.session.add(user)
        db.session.commit()
    elif name and user.name.startswith("Customer "):
        user.name = name
        db.session.commit()

    login_user(user)
    session.pop("otp_phone", None)
    flash(f"Welcome, {user.name}!", "success")
    return redirect(_home_for(user))


# --------------------------------------------------------------------------- #
# Staff login via email + password
# --------------------------------------------------------------------------- #
@auth_bp.route("/staff", methods=["POST"])
def staff_login():
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    user = User.query.filter_by(email=email).first()
    if user and user.is_staff and user.check_password(password):
        login_user(user)
        flash(f"Welcome back, {user.name}.", "success")
        return redirect(_home_for(user))
    flash("Invalid staff credentials.", "danger")
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("public.home"))
