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


# Liability waiver a client must accept when rejecting a recommended material
# quotation raised during an AMC visit (Wave 6).
WAIVER_TEXT = (
    "I do not wish to replace the mentioned spare parts/equipments/tools as mentioned "
    "by the company and hereby, I take full responsibility if any fire incident happens "
    "after this AMC visit, and Northern Star Engineering is not responsible."
)


# AMC maintenance agreement — the click-through Terms & Conditions a customer
# must read and accept (in-app, app-store style) once their contract is activated.
# Bump AMC_AGREEMENT_VERSION whenever the clauses change so prior acceptances are
# distinguishable. The agreement is view-only — clients cannot download it.
AMC_AGREEMENT_VERSION = "1.0"
AMC_AGREEMENT_CLAUSES = [
    ("Scope of Service",
     "The Annual Maintenance Contract covers inspection, testing, and routine servicing "
     "of fire safety equipment at the registered site as per the agreed visit schedule. "
     "Only equipment listed at the time of contract activation is covered under this agreement."),
    ("Visit Schedule & Rescheduling",
     "Northern Star Engineering will conduct the agreed number of visits across the contract "
     "year, evenly spaced. The client must ensure site access on the scheduled date. If access "
     "is denied, that visit is forfeited. Rescheduling requests must be made at least 48 hours "
     "in advance."),
    ("Spare Parts & Materials",
     "Routine maintenance consumables are included. Replacement of damaged, expired, or "
     "non-functional parts is quoted separately. The client is not obligated to accept a "
     "material quotation, but Northern Star Engineering bears no liability for fire incidents "
     "attributable to equipment for which the client has declined recommended replacement "
     "(a waiver must be signed at the time of decline)."),
    ("Equipment Not Covered",
     "This contract does not cover equipment damaged due to misuse, vandalism, or acts of God; "
     "third-party-installed equipment; civil or electrical infrastructure (piping, wiring, boards); "
     "or equipment added to the site after activation without prior written intimation."),
    ("Client Obligations",
     "The client agrees to maintain the equipment in a clean and accessible state between visits; "
     "report any fault or damage immediately; not engage a third party to service the same "
     "equipment during the contract period; and ensure electrical supply and site access on "
     "visit days."),
    ("Liability Cap",
     "Northern Star Engineering's total liability under this agreement, for any reason, shall not "
     "exceed the annual contract fee paid. NSE is not liable for consequential losses, property "
     "damage, or bodily injury arising from equipment failure where the client has been notified "
     "of a fault and has not authorised repair or replacement."),
    ("Payment Terms",
     "The annual contract fee is due within 7 days of contract activation. Non-payment entitles "
     "Northern Star Engineering to suspend service until full payment is received. All amounts are "
     "inclusive of applicable GST (GST No. 24ALQPD0899P1ZD)."),
    ("Contract Renewal & Termination",
     "The contract is valid for 12 months from the activation date and does not auto-renew. "
     "Either party may terminate with 30 days' written notice; NSE will refund a pro-rated amount "
     "for unserved visits. No refund is payable if the client terminates after all visits are "
     "consumed."),
    ("Governing Law",
     "This agreement is subject to the laws of India. Any dispute arising under this agreement "
     "shall be subject to the exclusive jurisdiction of courts in Surat, Gujarat."),
]


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
def notify(user_id, title, body=None, link=None):
    if not user_id:
        return
    db.session.add(Notification(user_id=user_id, title=title, body=body, link=link))
    db.session.commit()


def notify_staff(title, body=None, link=None):
    """Fan a notification out to every staff member (admin + technician).

    Used for events the Ops Console must surface — e.g. a customer accepting or
    requesting negotiation on a quotation. Each staff user gets their own
    Notification row so the unread badge / bell works per-account.
    """
    from .models import User
    staff = User.query.filter(User.role.in_(["admin", "technician"])).all()
    for u in staff:
        db.session.add(Notification(user_id=u.id, title=title, body=body, link=link))
    db.session.commit()


def public_url(endpoint, **values):
    """Build a fully-qualified URL that is clickable on a client's phone.

    Priority:
      1. BASE_URL env var (set to ngrok / Vercel / production domain)
      2. Mac's LAN IP auto-detected via socket (same-WiFi use-case, dev only)
      3. Flask's url_for _external=True fallback (always works for localhost test)
    """
    import socket
    from flask import current_app
    base = current_app.config.get("BASE_URL", "").rstrip("/")
    if not base:
        # Try to auto-detect the LAN IP (works when client is on the same WiFi)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
            port = current_app.config.get("SERVER_PORT", 5055)
            base = f"http://{lan_ip}:{port}"
        except Exception:
            pass
    if base:
        path = url_for(endpoint, **values)
        return base + path
    return url_for(endpoint, _external=True, **values)


def rupees(amount):
    try:
        return "₹{:,.0f}".format(amount or 0)
    except (ValueError, TypeError):
        return f"₹{amount}"


# --------------------------------------------------------------------------- #
# WhatsApp click-to-send (free, no API). Builds a wa.me link that opens the
# sender's WhatsApp with the message pre-filled; they tap send. When a real
# WhatsApp Business API provider is wired later, swap the call sites for an
# automated send — the message-builders below can be reused verbatim.
# --------------------------------------------------------------------------- #
def normalise_phone(phone, country="91"):
    """Strip to digits and prepend the country code for a 10-digit Indian number."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 10:
        digits = country + digits
    return digits


def whatsapp_url(phone, text):
    """Return a wa.me click-to-chat URL with a pre-filled message.

    If `phone` is empty, returns a generic wa.me link (opens contact picker).
    """
    import urllib.parse
    digits = normalise_phone(phone)
    base = f"https://wa.me/{digits}" if digits else "https://wa.me/"
    return f"{base}?text={urllib.parse.quote(text)}"


# --------------------------------------------------------------------------- #
# UPI QR — builds a standard `upi://pay` deep link and renders it as a base64
# PNG so any UPI app (GPay/PhonePe/Paytm) can scan and pay the exact amount.
# Manual confirmation for now; a gateway webhook can confirm automatically later.
# --------------------------------------------------------------------------- #
def upi_link(vpa, payee_name, amount, note=""):
    import urllib.parse
    params = {
        "pa": vpa,
        "pn": payee_name,
        "am": f"{float(amount or 0):.2f}",
        "cu": "INR",
    }
    if note:
        params["tn"] = note
    return "upi://pay?" + urllib.parse.urlencode(params)


def upi_qr_data_uri(vpa, payee_name, amount, note=""):
    """Return (upi_link, data_uri_png) for a UPI QR, or (link, None) on failure."""
    link = upi_link(vpa, payee_name, amount, note)
    try:
        import io, base64, qrcode
        qr = qrcode.QRCode(version=None, box_size=8, border=2,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(link)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#16235b", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return link, f"data:image/png;base64,{b64}"
    except Exception:
        return link, None
