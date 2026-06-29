"""
nse/pdf_generator.py
~~~~~~~~~~~~~~~~~~~~
PDF generation for Northern Star Engineering documents.

Uses xhtml2pdf (pisa) to convert Jinja2-rendered HTML to PDF.
All templates live in nse/templates/pdf/.

Usage:
    from nse.pdf_generator import generate_quotation_pdf
    pdf_bytes = generate_quotation_pdf(quotation)
"""
from __future__ import annotations

import io
import logging
import os
from typing import Optional

from flask import render_template, current_app

log = logging.getLogger(__name__)


def _link_callback(uri: str, rel: str) -> str:
    """Resolve a template URI (e.g. /static/img/logo.png) to a local file path.

    xhtml2pdf cannot fetch `file://` URLs or app routes — it needs a real path on
    disk. This maps static URIs to the package's static folder so the logo and any
    other static assets embed correctly in the PDF.
    """
    try:
        root = current_app.root_path
    except Exception:
        return uri
    if uri.startswith("file://"):
        candidate = uri[len("file://"):]
    elif uri.startswith("/static/"):
        candidate = os.path.join(root, uri.lstrip("/"))
    elif uri.startswith("static/"):
        candidate = os.path.join(root, uri)
    else:
        candidate = uri
    return candidate if os.path.isfile(candidate) else uri


def _html_to_pdf(html: str) -> Optional[bytes]:
    """Convert an HTML string to PDF bytes using xhtml2pdf/pisa."""
    try:
        from xhtml2pdf import pisa

        buf = io.BytesIO()
        status = pisa.CreatePDF(
            src=html,
            dest=buf,
            encoding="utf-8",
            link_callback=_link_callback,
        )
        if status.err:
            log.error("xhtml2pdf error: %s", status.err)
            return None
        return buf.getvalue()
    except Exception as exc:              # noqa: BLE001
        log.error("PDF generation failed: %s", exc)
        return None


def generate_quotation_pdf(quotation) -> Optional[bytes]:
    """Render the service quotation as a PDF and return raw bytes."""
    company_name    = current_app.config.get("COMPANY_NAME", "Northern Star Engineering")
    company_address = current_app.config.get(
        "COMPANY_ADDRESS",
        "522-523, Western Business Park, Vesu, Surat-395 007"
    )
    company_phone   = current_app.config.get("COMPANY_PHONE", "9687266640")
    company_email   = current_app.config.get("COMPANY_EMAIL", "info@northernstarengineering.com")
    company_gst     = current_app.config.get("COMPANY_GST", "24ALQPD0899P1ZD")

    # Static URI for the logo; resolved to a real file by _link_callback above.
    logo_path = os.path.join(
        current_app.root_path, "static", "img", "logo-full.png"
    )
    logo_url = "/static/img/logo-full.png" if os.path.exists(logo_path) else ""

    html = render_template(
        "pdf/quotation.html",
        q=quotation,
        company_name=company_name,
        company_address=company_address,
        company_phone=company_phone,
        company_email=company_email,
        company_gst=company_gst,
        logo_url=logo_url,
    )
    return _html_to_pdf(html)


def _company_ctx() -> dict:
    """Shared company branding context for PDF templates."""
    return {
        "company_name": current_app.config.get("COMPANY_NAME", "Northern Star Engineering"),
        "company_address": current_app.config.get(
            "COMPANY_ADDRESS", "522-523, Western Business Park, Vesu, Surat-395 007"),
        "company_phone": current_app.config.get("COMPANY_PHONE", "9687266640"),
        "company_email": current_app.config.get("COMPANY_EMAIL", "info@northernstarengineering.com"),
        "company_gst": current_app.config.get("COMPANY_GST", "24ALQPD0899P1ZD"),
        "logo_url": "/static/img/logo-full.png" if os.path.exists(
            os.path.join(current_app.root_path, "static", "img", "logo-full.png")) else "",
    }


def generate_health_report_pdf(report) -> Optional[bytes]:
    """Render the Fire System Health Checkup Report as a branded PDF."""
    from .models import HealthCheckReport
    html = render_template(
        "pdf/health_report.html",
        r=report,
        answers=report.answers,
        model=HealthCheckReport,
        **_company_ctx(),
    )
    return _html_to_pdf(html)


def generate_material_quotation_pdf(quotation) -> tuple[Optional[bytes], str]:
    """Render a visit-linked material quotation as a PDF using the same NSE
    QUO format as ServiceQuotation PDFs.  Returns (bytes, filename)."""
    ctx = _company_ctx()
    html = render_template(
        "pdf/quotation.html",
        q=quotation,
        company_name=ctx["company_name"],
        company_address=ctx["company_address"],
        company_phone=ctx["company_phone"],
        company_email=ctx["company_email"],
        company_gst=ctx["company_gst"],
        logo_url=ctx["logo_url"],
    )
    pdf = _html_to_pdf(html)
    filename = f"{quotation.reference}.pdf"
    return pdf, filename


def generate_service_report_pdf(visit) -> Optional[bytes]:
    """Render a branded post-visit service report as a PDF."""
    html = render_template(
        "pdf/service_report.html",
        v=visit,
        **_company_ctx(),
    )
    return _html_to_pdf(html)
