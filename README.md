---
title: Leads
emoji: 📈
colorFrom: indigo
colorTo: blue
sdk: docker
pinned: false
---

# Lead Scraper - AI-Powered Business Outreach Tool

A full-stack lead generation and outreach tool that scrapes business data from Google Maps and Manta, then uses AI (Groq) to generate personalized WhatsApp and email messages.

## Features

- **Multi-Source Scraping** - Google Maps (Playwright) + Manta.com (BeautifulSoup)
- **AI-Generated Messages** - Groq LLM creates personalized outreach for each lead
- **Bulk Email** - Send AI-crafted emails via Gmail SMTP to all leads at once
- **Bulk WhatsApp** - Open AI-generated WhatsApp messages one-by-one with human-like delays (30-90s) to avoid bans
- **Contact Tracking** - Leads are marked as contacted (Email/WhatsApp) with timestamps
- **Lead Management** - Filter, search, edit emails, export CSV, deduplicate
- **Responsive UI** - Works on desktop, tablet, and mobile
- **Dark Theme** - Modern dark UI built with vanilla HTML/CSS/JS

## Tech Stack

- **Backend:** Python, Flask
- **Scraping:** Playwright (Google Maps), BeautifulSoup + cloudscraper (Manta)
- **AI:** Groq API (LLaMA 3.3 70B)
- **Email:** Gmail SMTP with App Password
- **Frontend:** Vanilla HTML, CSS, JavaScript
- **Deployment:** Docker, Hugging Face Spaces

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/AbdulHannan031/lead-scraper.git
cd lead-scraper
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
GROQ_API_KEY=your_groq_api_key
GMAIL_EMAIL=your_gmail@gmail.com
GMAIL_APP_PASSWORD=your_gmail_app_password
```

### 4. Run

```bash
python app.py
```

Open `http://localhost:5000` in your browser.

## How It Works

1. **Search** - Enter a keyword (e.g. "restaurants") and location (e.g. "New York")
2. **Scrape** - App scrapes Google Maps and/or Manta for business listings
3. **Review** - Browse leads in the table, add email addresses, filter by status
4. **AI Generate** - Click "AI Generate" to create a personalized message per lead
5. **Send** - Bulk email via Gmail or bulk WhatsApp with anti-ban delays
6. **Track** - Contacted leads are marked with WA/EM badges

## Deployment

### Hugging Face Spaces (Free)

1. Create a new Space with **Docker** SDK
2. Add secrets in Settings: `GROQ_API_KEY`, `GMAIL_EMAIL`, `GMAIL_APP_PASSWORD`
3. Push your code to the Space repo

## Author

**Abdul Hannan** - Full Stack Developer
Email: abdulhannan03086@gmail.com
GitHub: [AbdulHannan031](https://github.com/AbdulHannan031)
