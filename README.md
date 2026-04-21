# Amazon Rufus Scraper (POC)
# 🛒 Amazon Rufus Scraper (POC)

## 📌 Overview

This project demonstrates how to extract responses from Amazon Rufus (AI shopping assistant) using browser automation.

Given a query like:
> "Best hair serum for men"

The system captures:
- 🤖 AI-generated response
- 🛍️ Product recommendations
- 📊 Product details (name, price, rating, URL)
- 🏆 Ranking order

---

## 🧠 How It Works

Rufus does not return data in a simple API response. Instead, it uses **dynamic rendering and streaming responses**.

So we use a **2-step approach**:


User Query → Rufus → (Streaming / API) → Browser UI
↓
[1] Network Interception (Preferred)
↓
[2] DOM Extraction (Fallback)


---

## ⚙️ Tech Stack

- Python 🐍  
- Playwright 🎭 (browser automation)

---

## 📂 Project Structure


rufus-poc/
│
├── network_interceptor.py # Captures backend API calls
├── rufus_extractor.py # Scrapes UI (fallback)
├── requirements.txt
├── README.md
└── output/
└── sample_output.json


---

## 🚀 Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt

2. Install browser
python -m playwright install chromium

▶️ Usage (Step-by-Step)

🔹 Step 1: Network Interception (Primary Method)
python network_interceptor.py

👉 What happens:
A browser opens automatically
You log in manually
Open Rufus (chat icon)
Enter query (e.g., Best hair serum for men)
Script captures all backend responses

🖥️ Example Flow
Open Amazon → Login → Open Rufus → Type Query
                                 ↓
                     Capture Network Calls
                                 ↓
                     Save JSON Output
                     
📁 Output
output/rufus_network.json
🔍 What to check in output

Look for:

products
recommendations
title, price, rating


🔹 Step 2: DOM Extraction (Fallback)

If API data is not accessible or Rufus uses streaming:

python rufus_extractor.py
👉 What happens:
Browser opens
You manually run Rufus
Script reads visible UI
Extracts product details


📁 Output
output/rufus_result.json


📊 Sample Output
{
  "query": "Best hair serum for men",
  "responseText": "Here are some top-rated hair serums...",
  "products": [
    {
      "rank": 1,
      "name": "L'Oreal Hair Serum",
      "price": "$12.99",
      "rating": "4.5 stars",
      "url": "https://amazon.com/dp/EXAMPLE"
    },
    {
      "rank": 2,
      "name": "Dove Men+Care Serum",
      "price": "$9.99",
      "rating": "4.4 stars",
      "url": "https://amazon.com/dp/EXAMPLE2"
    }
  ]
}
🧠 Key Concepts
🔹 Network Interception

Captures backend API responses directly from browser traffic.

🔹 DOM Scraping

Extracts data from visible UI elements.

🔹 Streaming Responses

Rufus sends responses in chunks instead of a single JSON response.