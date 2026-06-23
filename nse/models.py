from datetime import datetime, date, timedelta

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db, login_manager


# --------------------------------------------------------------------------- #
# Users & auth
# --------------------------------------------------------------------------- #
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False, default="customer")  # customer/technician/admin
    name = db.Column(db.String(120), nullable=False)

    # Customers authenticate by phone (OTP); staff by email + password.
    phone = db.Column(db.String(20), unique=True)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(255))

    address = db.Column(db.String(255))
    area = db.Column(db.String(120))
    city = db.Column(db.String(120), default="Surat, Gujarat")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    contracts = db.relationship("Contract", backref="customer", lazy=True,
                                foreign_keys="Contract.customer_id")

    def set_password(self, raw):
        # pbkdf2 works on the system LibreSSL build (scrypt is unavailable there).
        self.password_hash = generate_password_hash(raw, method="pbkdf2:sha256")

    def check_password(self, raw):
        return bool(self.password_hash) and check_password_hash(self.password_hash, raw)

    @property
    def is_staff(self):
        return self.role in ("technician", "admin")

    @property
    def is_admin(self):
        return self.role == "admin"

    def __repr__(self):
        return f"<User {self.id} {self.role} {self.name}>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class OtpCode(db.Model):
    """One-time codes for customer phone login (dev flow / pluggable SMS)."""
    __tablename__ = "otp_codes"

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), nullable=False, index=True)
    code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_valid(self):
        return (not self.used) and datetime.utcnow() < self.expires_at


# --------------------------------------------------------------------------- #
# AMC plans & contracts
# --------------------------------------------------------------------------- #
class AMCPlan(db.Model):
    __tablename__ = "amc_plans"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # residential/commercial
    tier = db.Column(db.String(30))                      # Basic/Standard/Premium
    price = db.Column(db.Integer, nullable=False)        # rupees per year
    visits_per_year = db.Column(db.Integer, nullable=False, default=4)
    response_time = db.Column(db.String(60), default="48 hours")
    description = db.Column(db.Text)
    features = db.Column(db.Text)  # one feature per line
    active = db.Column(db.Boolean, default=True)

    @property
    def feature_list(self):
        return [f.strip() for f in (self.features or "").splitlines() if f.strip()]


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    plan_id = db.Column(db.Integer, db.ForeignKey("amc_plans.id"))

    status = db.Column(db.String(20), default="pending")  # pending/active/expired/cancelled
    site_name = db.Column(db.String(160))
    site_address = db.Column(db.String(255))
    area = db.Column(db.String(120))

    # Captured on application before a user account may exist.
    applicant_name = db.Column(db.String(120))
    applicant_phone = db.Column(db.String(20))
    applicant_email = db.Column(db.String(120))
    property_type = db.Column(db.String(60))
    application_notes = db.Column(db.Text)

    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    total_visits = db.Column(db.Integer, default=4)
    price = db.Column(db.Integer, default=0)
    payment_mode = db.Column(db.String(20), default="cash")    # cash/online
    payment_status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    plan = db.relationship("AMCPlan")
    visits = db.relationship("Visit", backref="contract", lazy=True,
                             cascade="all, delete-orphan", order_by="Visit.visit_number")
    equipment = db.relationship("Equipment", backref="contract", lazy=True,
                                cascade="all, delete-orphan")
    quotations = db.relationship("Quotation", backref="contract", lazy=True,
                                 cascade="all, delete-orphan")

    @property
    def reference(self):
        return f"AMC-{self.id:05d}"

    @property
    def completed_visits(self):
        return sum(1 for v in self.visits if v.status == "completed")

    @property
    def next_visit(self):
        upcoming = [v for v in self.visits if v.status in ("scheduled", "in_progress")]
        return min(upcoming, key=lambda v: v.scheduled_date or date.max) if upcoming else None


class Visit(db.Model):
    __tablename__ = "visits"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    visit_number = db.Column(db.Integer, nullable=False, default=1)
    scheduled_date = db.Column(db.Date)
    completed_date = db.Column(db.Date)
    status = db.Column(db.String(20), default="scheduled")  # scheduled/in_progress/completed/cancelled
    technician_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    work_done = db.Column(db.Text)
    notes = db.Column(db.Text)
    service_report_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    technician = db.relationship("User", foreign_keys=[technician_id])
    photos = db.relationship("VisitPhoto", backref="visit", lazy=True,
                             cascade="all, delete-orphan")

    @property
    def label(self):
        return f"Visit {self.visit_number}"


class VisitPhoto(db.Model):
    __tablename__ = "visit_photos"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"))
    file_path = db.Column(db.String(255), nullable=False)  # relative to static/
    caption = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


# --------------------------------------------------------------------------- #
# Equipment & refills
# --------------------------------------------------------------------------- #
class Equipment(db.Model):
    __tablename__ = "equipment"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    name = db.Column(db.String(160), nullable=False)        # e.g. ABC Dry Powder 6kg
    equip_type = db.Column(db.String(80))                   # extinguisher/hydrant/alarm/...
    location = db.Column(db.String(160))
    serial_no = db.Column(db.String(80))
    install_date = db.Column(db.Date)
    last_refill_date = db.Column(db.Date)
    refill_interval_months = db.Column(db.Integer, default=12)
    next_refill_date = db.Column(db.Date)

    refills = db.relationship("RefillRecord", backref="equipment", lazy=True,
                              cascade="all, delete-orphan", order_by="RefillRecord.refill_date.desc()")

    def recompute_next_refill(self):
        base = self.last_refill_date or self.install_date
        if base and self.refill_interval_months:
            months = self.refill_interval_months
            year = base.year + (base.month - 1 + months) // 12
            month = (base.month - 1 + months) % 12 + 1
            day = min(base.day, 28)
            self.next_refill_date = date(year, month, day)

    @property
    def days_to_refill(self):
        if not self.next_refill_date:
            return None
        return (self.next_refill_date - date.today()).days

    @property
    def refill_status(self):
        d = self.days_to_refill
        if d is None:
            return "unknown"
        if d < 0:
            return "overdue"
        if d <= 30:
            return "due_soon"
        return "ok"


class RefillRecord(db.Model):
    __tablename__ = "refill_records"

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"))
    refill_date = db.Column(db.Date, nullable=False, default=date.today)
    performed_by = db.Column(db.String(120))
    notes = db.Column(db.String(255))


# --------------------------------------------------------------------------- #
# Quotations (materials to replace)
# --------------------------------------------------------------------------- #
class Quotation(db.Model):
    __tablename__ = "quotations"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"))
    status = db.Column(db.String(20), default="pending")  # pending/approved/rejected
    notes = db.Column(db.Text)
    payment_mode = db.Column(db.String(20))               # chosen on approval
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime)

    items = db.relationship("QuotationItem", backref="quotation", lazy=True,
                            cascade="all, delete-orphan")

    @property
    def reference(self):
        return f"QT-{self.id:05d}"

    @property
    def total(self):
        return sum(i.amount for i in self.items)


class QuotationItem(db.Model):
    __tablename__ = "quotation_items"

    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey("quotations.id"))
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Integer, default=0)

    @property
    def amount(self):
        return (self.quantity or 0) * (self.unit_price or 0)


# --------------------------------------------------------------------------- #
# Emergency / NOC service requests
# --------------------------------------------------------------------------- #
class ServiceRequest(db.Model):
    __tablename__ = "service_requests"

    id = db.Column(db.Integer, primary_key=True)
    request_type = db.Column(db.String(20), default="emergency")  # emergency/noc
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))
    area = db.Column(db.String(120))
    location = db.Column(db.String(255))
    description = db.Column(db.Text)        # what happened

    status = db.Column(db.String(20), default="new")  # new/scheduled/dispatched/in_progress/completed/cancelled
    scheduled_date = db.Column(db.DateTime)
    team_eta = db.Column(db.String(80))
    assigned_technician_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    payment_mode = db.Column(db.String(20), default="cash")  # cash/online
    amount = db.Column(db.Integer, default=0)
    payment_status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    technician = db.relationship("User", foreign_keys=[assigned_technician_id])

    @property
    def reference(self):
        prefix = "NOC" if self.request_type == "noc" else "EMG"
        return f"{prefix}-{self.id:05d}"


# --------------------------------------------------------------------------- #
# Payments, enquiries, notifications
# --------------------------------------------------------------------------- #
class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"))
    service_request_id = db.Column(db.Integer, db.ForeignKey("service_requests.id"))
    quotation_id = db.Column(db.Integer, db.ForeignKey("quotations.id"))
    amount = db.Column(db.Integer, default=0)
    mode = db.Column(db.String(20), default="cash")     # cash/online
    status = db.Column(db.String(20), default="pending")  # pending/paid
    reference = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Enquiry(db.Model):
    __tablename__ = "enquiries"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(120))
    subject = db.Column(db.String(160))
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default="new")  # new/responded
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.String(255))
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
