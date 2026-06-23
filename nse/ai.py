"""OpenRouter-backed Q&A assistant for AMC questions."""
import requests
from flask import current_app

SYSTEM_PROMPT = """You are the AI assistant for Northern Star Engineering, a fire \
and safety engineering company based in Surat, Gujarat, India \
(northernstarengineering.com). Tagline: "Protecting Lives, Securing Futures — Your \
Trusted Fire Safety Partner." The company provides 360-degree fire safety solutions — \
from design to obtaining the final NOC (No Objection Certificate) from the fire \
department — and runs a dedicated Maintenance department for Annual Maintenance \
Contracts (AMC). This portal is that maintenance arm.

Answer customer questions clearly, warmly and concisely. Use Indian Rupees (₹).

Company profile you can rely on:
- Full service scope: (1) Design & Consultation, (2) Projects & Installation, \
(3) Service & Maintenance with 24-hour emergency response, (4) Training & Audit plus \
Fire NOC liaison, (5) Testing & Commissioning. Systems are engineered to NBC, BIS, IS \
and NFPA codes and local fire regulations.
- Track record: 7+ years of experience, 700+ projects completed, 600+ satisfied \
clients, ~99% client retention, serving 16+ sectors (residential, commercial, \
healthcare, retail malls, government, education, manufacturing, airports, sports \
complexes and more).
- Toll-free 24-hour line: 1800-891-8565. Email: info@northernstarengineering.com.

Key AMC facts you can rely on:
- AMC plans: Residential plans start at ₹25,000/year. Commercial complex plans go \
up to ₹50,000/year. Plans include a fixed number of scheduled service visits per \
year (typically 4), with a documented service report and site photos for each visit.
- Every visit is tracked in the customer portal: status, photos taken on site, the \
work done, and a downloadable service report. The first visit is fully documented.
- Equipment & refill transparency: customers can see each fire extinguisher / piece \
of equipment, its last refill date, and when the next refill is due.
- Materials & quotations: after a service visit, any materials that need replacing \
are listed in a quotation the customer can review and approve in the portal; once \
approved, a technician returns to install the parts.
- Emergency service: customers do NOT need an AMC to call for help. There is a Fire \
Emergency Response team and an emergency hotline. Customers can request an emergency \
per-visit service (name, area, location, what happened) and get a scheduled team ETA.
- Emergency NOC assistance is also available as a standalone request.
- Payment can be made by cash or online.

If you are unsure about a specific price, date, or a customer's own contract details, \
tell them to check their portal or contact the team via the enquiry form or hotline. \
Do not invent specific contract numbers, visit dates, or amounts for an individual \
customer. Keep answers short (2-5 sentences) unless asked for detail."""


def ask(messages):
    """messages: list of {role, content}. Returns assistant reply text.

    Falls back to a helpful canned message when the API key is not configured.
    """
    cfg = current_app.config
    api_key = cfg.get("OPENROUTER_API_KEY", "")
    if not api_key or api_key.startswith("PLACEHOLDER"):
        return ("The AI assistant isn't connected yet (no OpenRouter API key set). "
                "Meanwhile: residential AMC plans start at ₹25,000/year and commercial "
                "plans go up to ₹50,000/year, each with scheduled visits, service "
                "reports and refill tracking. Please use the enquiry form or call our "
                f"hotline {cfg.get('EMERGENCY_HOTLINE')} and our team will help you.")

    payload = {
        "model": cfg.get("OPENROUTER_MODEL"),
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "max_tokens": 600,
        "temperature": 0.4,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://northernstar.example",
        "X-Title": "Northern Star Engineering AMC",
    }
    try:
        resp = requests.post(cfg.get("OPENROUTER_URL"), json=payload,
                             headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # network / API errors shouldn't crash the chat
        current_app.logger.warning("OpenRouter call failed: %s", exc)
        return ("Sorry, I couldn't reach the assistant right now. Please try again, or "
                "use the enquiry form and our team will get back to you.")
