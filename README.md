# Amazon Rufus Scraper (POC)

## Overview
This project explores how to extract responses from Amazon Rufus (AI shopping assistant) using Playwright.

Given a query like:
"Best hair serum for men"

The system captures:
- AI-generated response
- Product recommendations
- Product details (name, price, rating, URL)
- Ranking order

---

## Approach

### 1. Network Interception
Capture backend API responses using Playwright.

### 2. DOM Extraction (Fallback)
If API is not accessible, scrape the UI.

---

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium