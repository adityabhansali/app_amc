import os
import random
import uuid
from datetime import datetime, timedelta
from functools import wraps

import requests
from flask import abort, current_app, flash, redirect, url_for
from flask_login import current_user
from werkzeug.utils import secure_filename

from .extensions import db
from .models import OtpCode, Notification


def staff_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_staff:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def customer_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "customer":
            flash("Please log in as a customer to view this.", "warning")
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)
    return wrapper


# --------------------------------------------------------------------------- #
# OTP helpers (dev flow — pluggable into a real SMS gateway later)
# --------------------------------------------------------------------------- #
def generate_otp(phone):
    code = f"{random.randint(0, 999999):06d}"
    otp = OtpCode(phone=phone, code=code,
                  expires_at=datetime.utcnow() + timedelta(minutes=10))
    db.session.add(otp)
    db.session.commit()
    # In production: send `code` via SMS here. For now we log it and return it so
    # the dev UI can display it.
    current_app.logger.info("OTP for %s is %s", phone, code)
    return code


def verify_otp(phone, code):
    otp = (OtpCode.query
           .filter_by(phone=phone, code=code, used=False)
           .order_by(OtpCode.id.desc())
           .first())
    if otp and otp.is_valid:
        otp.used = True
        db.session.commit()
        return True
    return False


# --------------------------------------------------------------------------- #
# File uploads
# --------------------------------------------------------------------------- #
def _allowed(filename, allowed_ext):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_ext


def save_upload(file_storage, subdir, allowed_ext):
    """Persist an uploaded file and return a reference for later rendering.

    Two backends, chosen at runtime:
      * Vercel Blob (when BLOB_READ_WRITE_TOKEN is set) — returns an absolute
        https:// URL. Used in production, where the local filesystem is
        read-only/ephemeral.
      * Local disk (dev) — writes under static/uploads/<subdir>/ and returns a
        path relative to the static folder (for url_for('static', filename=...)).

    Either form is resolved for templates/links by `upload_url()` below.
    """
    if not file_storage or not file_storage.filename:
        return None
    if not _allowed(file_storage.filename, allowed_ext):
        return None
    safe = secure_filename(file_storage.filename)
    unique = f"{uuid.uuid4().hex[:8]}_{safe}"

    token = current_app.config.get("BLOB_READ_WRITE_TOKEN")
    if token:
        return _save_to_blob(file_storage, f"{subdir}/{unique}", token)

    dest_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, unique))
    return f"uploads/{subdir}/{unique}"


def _save_to_blob(file_storage, pathname, token):
    """Upload bytes to Vercel Blob via its REST API; return the public URL.

    We add our own uuid prefix for uniqueness, so we disable Blob's random
    suffix to keep the pathname predictable. Raises on a failed upload so the
    caller doesn't silently store a broken reference.
    """
    data = file_storage.read()
    resp = requests.put(
        f"https://blob.vercel-storage.com/{pathname}",
        data=data,
        headers={
            "authorization": f"Bearer {token}",
            "x-api-version": "7",
            "x-content-type": file_storage.mimetype or "application/octet-stream",
            "x-add-random-suffix": "0",
            "access": "public",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["url"]


def upload_url(path):
    """Resolve a stored upload reference to a browser URL.

    Absolute (Blob) URLs are returned as-is; relative paths are served from the
    Flask static folder. Registered as the `upload_url` Jinja filter.
    """
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    return url_for("static", filename=path)


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def notify(user_id, title, body=None):
    if not user_id:
        return
    db.session.add(Notification(user_id=user_id, title=title, body=body))
    db.session.commit()


def rupees(amount):
    try:
        return "₹{:,.0f}".format(amount or 0)
    except (ValueError, TypeError):
        return f"₹{amount}"
