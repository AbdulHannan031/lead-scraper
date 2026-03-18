import json
import os
import re
import hashlib
import urllib.parse
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import requests as http_requests
import queue
import threading
from flask import Flask, render_template, request, jsonify, Response

# Load .env file for local development
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())
from scraper import scrape_google_maps
from manta_scraper import scrape_manta

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GMAIL_EMAIL = os.environ.get("GMAIL_EMAIL", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

FREELANCER_PROFILE = """
Name: Abdul Hannan
Role: Full Stack Developer | Freelancer
Experience: 2+ years building responsive and scalable web applications
Completed: 50+ projects for global clients
Skills: React, Python, Flutter, Firebase, PHP, C#, Java, MongoDB, MySQL, JavaScript, C++
Education: Bachelor of Computer Science - SS CASE IT (3.54 CGPA)

Work Experience:
- Freelancing (2023 - Present) - 50+ projects for global clients
- Python Backend Developer at Coding The Brains (Aug 2025 - Nov 2025)
- Full Stack Developer at Saturn 7 Solution (2023 - 2025)
- Python/Web Developer Intern at Sir Syed CASE IT (Jun 2024 - Sep 2024)

Notable Projects:
- AI-powered satellite imagery evidence platform for legal professionals
- Restaurant management dashboards with voice assistant integration (Kallin AI)
- AI chatbots with RAG (George Avatar Chatbot for Dynavap)
- Gym Genius AI - AI-powered fitness assistant (Next.js, TypeScript, Firebase)
- Restaurant platforms (BeefnBunns, Kolachi, Lavie) for US clients
- WooCommerce plugins (fundraiser, square meter pricing)
- Automation bots for business workflows
- AI Mock Interviewer platform
- WordPress GPT-powered chatbot plugins
- PDF Whisper - AI document Q&A tool
- Coding Competition Platform with AI judging

Contact:
- Email: abdulhannan03086@gmail.com
- Phone: (+92) 3069881063
- Portfolio: Available on GitHub
- LinkedIn, GitHub, WhatsApp available

Specialties: Web apps, AI/ML integration, automation bots, WordPress plugins, mobile apps (Flutter), restaurant/e-commerce solutions
"""

app = Flask(__name__)

# In-memory lead storage (persisted to leads.json)
LEADS_FILE = os.path.join(os.path.dirname(__file__), "leads.json")


def load_leads():
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_leads(leads):
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2, ensure_ascii=False)


def generate_lead_id(lead):
    """Generate a unique ID based on name + phone + address to prevent duplicates."""
    key = (
        f"{lead.get('name', '').lower().strip()}"
        f"|{lead.get('phone', '').lower().strip()}"
        f"|{lead.get('address', '').lower().strip()}"
    )
    return hashlib.md5(key.encode()).hexdigest()


def deduplicate_leads(existing, new_leads):
    """Add only new leads that don't already exist."""
    existing_ids = {lead.get("id") for lead in existing}
    # Also check by name similarity
    existing_names = {lead.get("name", "").lower().strip() for lead in existing}
    added = []
    for lead in new_leads:
        lead_id = generate_lead_id(lead)
        name_lower = lead.get("name", "").lower().strip()
        if lead_id not in existing_ids and name_lower not in existing_names:
            lead["id"] = lead_id
            existing.append(lead)
            added.append(lead)
            existing_ids.add(lead_id)
            existing_names.add(name_lower)
    return existing, added


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def search():
    data = request.get_json()
    keyword = data.get("keyword", "")
    source = data.get("source", "google_maps")
    max_results = data.get("max_results", 20)
    scroll_count = data.get("scroll_count", 3)
    location = data.get("location", "")

    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400

    try:
        scraped = []

        if source in ("google_maps", "both"):
            search_term = f"{keyword} in {location}" if location else keyword
            gm_results = scrape_google_maps(
                search_term, max_results=max_results, scroll_count=scroll_count
            )
            for r in gm_results:
                r["source"] = "google_maps"
            scraped.extend(gm_results)

        if source in ("manta", "both"):
            manta_results = scrape_manta(keyword, location=location, max_pages=2)
            scraped.extend(manta_results)

        existing = load_leads()
        updated, added = deduplicate_leads(existing, scraped)
        save_leads(updated)

        return jsonify({
            "total_scraped": len(scraped),
            "new_added": len(added),
            "duplicates_skipped": len(scraped) - len(added),
            "leads": added,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search-stream")
def search_stream():
    """SSE endpoint for real-time scraping progress."""
    keyword = request.args.get("keyword", "")
    source = request.args.get("source", "google_maps")
    max_results = int(request.args.get("max_results", 20))
    scroll_count = int(request.args.get("scroll_count", 3))
    location = request.args.get("location", "")

    if not keyword:
        return jsonify({"error": "Keyword is required"}), 400

    progress_queue = queue.Queue()

    def on_progress(event, data):
        progress_queue.put({"event": event, "data": data})

    def run_scrape():
        scraped = []
        try:
            if source in ("google_maps", "both"):
                search_term = f"{keyword} in {location}" if location else keyword
                gm_results = scrape_google_maps(
                    search_term, max_results=max_results,
                    scroll_count=scroll_count, on_progress=on_progress
                )
                for r in gm_results:
                    r["source"] = "google_maps"
                scraped.extend(gm_results)

            if source in ("manta", "both"):
                on_progress("status", {"message": "Scraping Manta.com..."})
                manta_results = scrape_manta(keyword, location=location, max_pages=2)
                scraped.extend(manta_results)

            existing = load_leads()
            updated, added = deduplicate_leads(existing, scraped)
            save_leads(updated)

            progress_queue.put({"event": "complete", "data": {
                "total_scraped": len(scraped),
                "new_added": len(added),
                "duplicates_skipped": len(scraped) - len(added),
            }})
        except Exception as e:
            progress_queue.put({"event": "error", "data": {"message": str(e)}})

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()

    def generate():
        while True:
            try:
                msg = progress_queue.get(timeout=120)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg["event"] in ("complete", "error"):
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'event': 'heartbeat', 'data': {}})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/leads", methods=["GET"])
def get_leads():
    leads = load_leads()
    filter_type = request.args.get("filter", "all")
    search_query = request.args.get("q", "").lower()
    source_filter = request.args.get("source", "all")

    if filter_type == "with_website":
        leads = [l for l in leads if l.get("website")]
    elif filter_type == "without_website":
        leads = [l for l in leads if not l.get("website")]

    if source_filter != "all":
        leads = [l for l in leads if l.get("source") == source_filter]

    if search_query:
        leads = [
            l for l in leads
            if search_query in l.get("name", "").lower()
            or search_query in l.get("category", "").lower()
            or search_query in l.get("address", "").lower()
        ]

    return jsonify({"leads": leads, "total": len(leads)})


@app.route("/api/leads/<lead_id>", methods=["DELETE"])
def delete_lead(lead_id):
    leads = load_leads()
    leads = [l for l in leads if l.get("id") != lead_id]
    save_leads(leads)
    return jsonify({"success": True})


@app.route("/api/leads/clear", methods=["DELETE"])
def clear_leads():
    save_leads([])
    return jsonify({"success": True})


@app.route("/api/whatsapp-link", methods=["POST"])
def whatsapp_link():
    data = request.get_json()
    phone = data.get("phone", "")
    message = data.get("message", "")

    # Clean phone number - keep only digits and +
    clean_phone = re.sub(r"[^\d+]", "", phone)
    if clean_phone.startswith("0"):
        clean_phone = clean_phone[1:]

    encoded_msg = urllib.parse.quote(message)
    url = f"https://wa.me/{clean_phone}?text={encoded_msg}"
    return jsonify({"url": url})


@app.route("/api/email-link", methods=["POST"])
def email_link():
    data = request.get_json()
    email = data.get("email", "")
    subject = data.get("subject", "")
    body = data.get("body", "")

    encoded_subject = urllib.parse.quote(subject)
    encoded_body = urllib.parse.quote(body)
    url = f"mailto:{email}?subject={encoded_subject}&body={encoded_body}"
    return jsonify({"url": url})


@app.route("/api/leads/<lead_id>/contacted", methods=["POST"])
def mark_contacted(lead_id):
    """Mark a lead as contacted via email, whatsapp, or both."""
    data = request.get_json()
    channel = data.get("channel", "email")  # email, whatsapp, both

    leads = load_leads()
    for lead in leads:
        if lead.get("id") == lead_id:
            contacted = lead.get("contacted", {})
            if channel in ("email", "both"):
                contacted["email"] = True
                contacted["email_date"] = time.strftime("%Y-%m-%d %H:%M")
            if channel in ("whatsapp", "both"):
                contacted["whatsapp"] = True
                contacted["whatsapp_date"] = time.strftime("%Y-%m-%d %H:%M")
            lead["contacted"] = contacted
            break
    save_leads(leads)
    return jsonify({"success": True})


@app.route("/api/leads/<lead_id>/email", methods=["POST"])
def update_lead_email(lead_id):
    """Update email address for a lead."""
    data = request.get_json()
    email = data.get("email", "")
    leads = load_leads()
    for lead in leads:
        if lead.get("id") == lead_id:
            lead["email"] = email
            break
    save_leads(leads)
    return jsonify({"success": True})


def send_gmail(to_email, subject, body):
    """Send an email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = f"Abdul Hannan <{GMAIL_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Plain text version
    msg.attach(MIMEText(body, "plain"))

    # HTML version (convert newlines to <br>)
    html_body = body.replace("\n", "<br>")
    html = f"""<html><body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <p>{html_body}</p>
    </body></html>"""
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_EMAIL, to_email, msg.as_string())


def generate_ai_message(lead, message_type):
    """Generate an AI message for a lead. Returns dict with message/subject+body."""
    business_name = lead.get("name", "the business")
    category = lead.get("category", "")
    address = lead.get("address", "")
    rating = lead.get("rating", "")
    reviews = lead.get("reviews", "")
    website = lead.get("website", "")
    hours = lead.get("hours", "")

    lead_context = f"""Business Name: {business_name}
Category: {category}
Address: {address}
Rating: {rating} ({reviews} reviews)
Website: {'Yes - ' + website if website else 'No website'}
Hours: {hours}"""

    if message_type == "whatsapp":
        prompt = f"""You are writing a WhatsApp message on behalf of Abdul Hannan, a freelance Full Stack Developer.

FREELANCER PROFILE:
{FREELANCER_PROFILE}

TARGET BUSINESS:
{lead_context}

Write a short, friendly, professional WhatsApp message (max 150 words) to this business offering freelance web development services.
- Be conversational and warm (it's WhatsApp, not a formal email)
- Mention their business by name
- If they have no website, offer to build one. If they have a website, offer improvements/upgrades or additional tech services
- Reference their business category to show you've done research
- Include a clear call to action
- Sign off as Abdul Hannan
- Do NOT use any markdown formatting, emojis, or special characters
- Write plain text only"""
    else:
        prompt = f"""You are writing a professional email on behalf of Abdul Hannan, a freelance Full Stack Developer.

FREELANCER PROFILE:
{FREELANCER_PROFILE}

TARGET BUSINESS:
{lead_context}

Write a professional but warm email body (max 200 words) to this business offering freelance web development services.
- Address the business by name
- If they have no website, pitch building one. If they have a website, offer improvements, new features, or additional tech services
- Reference their business category to show genuine interest
- Mention relevant experience from the portfolio (pick 1-2 similar projects)
- Include a clear call to action
- Sign off as Abdul Hannan with contact details (email: abdulhannan03086@gmail.com, phone: +92 3069881063)
- Do NOT use any markdown formatting
- Write plain text only

Also generate a compelling email subject line.
Return the response in this exact format:
SUBJECT: <subject line here>
BODY: <email body here>"""

    response = http_requests.post(
        GROQ_API_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a professional copywriter specializing in B2B outreach messages for freelance developers. Write natural, personalized messages that don't sound templated."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 500,
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(f"Groq API error: {response.status_code}")

    result = response.json()
    ai_message = result["choices"][0]["message"]["content"].strip()

    if message_type == "email":
        subject = ""
        body = ai_message
        if "SUBJECT:" in ai_message and "BODY:" in ai_message:
            parts = ai_message.split("BODY:", 1)
            subject_part = parts[0]
            body = parts[1].strip() if len(parts) > 1 else ai_message
            subject = subject_part.replace("SUBJECT:", "").strip()
        return {"subject": subject, "body": body}
    else:
        return {"message": ai_message}


@app.route("/api/bulk-email", methods=["POST"])
def bulk_email():
    """Send AI-generated emails to all leads with email addresses via Gmail SMTP."""
    data = request.get_json()
    lead_ids = data.get("lead_ids", [])

    leads = load_leads()
    target_leads = [l for l in leads if l.get("id") in lead_ids and l.get("email")]

    if not target_leads:
        return jsonify({"error": "No leads with email addresses selected"}), 400

    results = []
    for lead in target_leads:
        try:
            ai_result = generate_ai_message(lead, "email")
            subject = ai_result.get("subject", "Web Development Services for Your Business")
            body = ai_result.get("body", "")

            send_gmail(lead["email"], subject, body)

            # Mark as contacted
            for l in leads:
                if l.get("id") == lead.get("id"):
                    contacted = l.get("contacted", {})
                    contacted["email"] = True
                    contacted["email_date"] = time.strftime("%Y-%m-%d %H:%M")
                    l["contacted"] = contacted

            results.append({
                "id": lead["id"],
                "name": lead.get("name"),
                "email": lead["email"],
                "status": "sent",
                "subject": subject,
            })
            time.sleep(2)  # Rate limit: 2 seconds between emails
        except Exception as e:
            results.append({
                "id": lead["id"],
                "name": lead.get("name"),
                "email": lead.get("email"),
                "status": "failed",
                "error": str(e),
            })

    save_leads(leads)
    sent = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "failed")
    return jsonify({"results": results, "sent": sent, "failed": failed})


@app.route("/api/bulk-whatsapp", methods=["POST"])
def bulk_whatsapp():
    """Generate AI messages for all leads with phone numbers and return WhatsApp links."""
    data = request.get_json()
    lead_ids = data.get("lead_ids", [])

    leads = load_leads()
    target_leads = [l for l in leads if l.get("id") in lead_ids and l.get("phone")]

    if not target_leads:
        return jsonify({"error": "No leads with phone numbers selected"}), 400

    results = []
    for lead in target_leads:
        try:
            ai_result = generate_ai_message(lead, "whatsapp")
            message = ai_result.get("message", "")

            clean_phone = re.sub(r"[^\d+]", "", lead.get("phone", ""))
            if clean_phone.startswith("0"):
                clean_phone = clean_phone[1:]

            encoded_msg = urllib.parse.quote(message)
            wa_url = f"https://wa.me/{clean_phone}?text={encoded_msg}"

            # Mark as contacted
            for l in leads:
                if l.get("id") == lead.get("id"):
                    contacted = l.get("contacted", {})
                    contacted["whatsapp"] = True
                    contacted["whatsapp_date"] = time.strftime("%Y-%m-%d %H:%M")
                    l["contacted"] = contacted

            results.append({
                "id": lead["id"],
                "name": lead.get("name"),
                "phone": lead.get("phone"),
                "status": "ready",
                "url": wa_url,
                "message": message,
            })
        except Exception as e:
            results.append({
                "id": lead["id"],
                "name": lead.get("name"),
                "phone": lead.get("phone"),
                "status": "failed",
                "error": str(e),
            })

    save_leads(leads)
    ready = sum(1 for r in results if r["status"] == "ready")
    return jsonify({"results": results, "ready": ready})


@app.route("/api/generate-message", methods=["POST"])
def generate_message():
    """Use Groq AI to generate a personalized outreach message."""
    data = request.get_json()
    lead = data.get("lead", {})
    message_type = data.get("type", "whatsapp")

    try:
        result = generate_ai_message(lead, message_type)
        return jsonify(result)
    except http_requests.exceptions.Timeout:
        return jsonify({"error": "Groq API request timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
