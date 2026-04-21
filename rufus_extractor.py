"""
SCRIPT 2: Amazon Rufus — DOM Extractor (fallback)
==================================================
Use this if network_interceptor.py didn't find a clean JSON API.

What this does:
  1. Opens a real Chrome browser (visible)
  2. Goes to amazon.com
  3. Waits for you to log in + use Rufus manually
  4. Scrapes the Rufus panel from the DOM
  5. Saves structured result to output/rufus_result.json

How to run:
  python rufus_extractor.py
  QUERY="best shampoo for men" python rufus_extractor.py

Output:
  output/rufus_result.json
  output/rufus_screenshot.png
  output/rufus_dom_dump.html   (only if selectors fail — helps you debug)
"""

import json
import os
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright, Page

# ──────────────────────────────────────────────────────
#  CONFIGURATION — update selectors here if needed
# ──────────────────────────────────────────────────────

QUERY = os.environ.get("QUERY", "Best hair serum for men")

OUTPUT_DIR      = "output"
RESULT_FILE     = os.path.join(OUTPUT_DIR, "rufus_result.json")
SCREENSHOT_FILE = os.path.join(OUTPUT_DIR, "rufus_screenshot.png")
DOM_DUMP_FILE   = os.path.join(OUTPUT_DIR, "rufus_dom_dump.html")

# ── Selectors ──────────────────────────────────────────
# Each is a LIST. Script tries them in order, uses first match.
# Update these after checking rufus_dom_dump.html if scraping fails.

SELECTORS = {

    # The full Rufus panel container
    "rufus_panel": [
        '[id*="rufus"]',
        '[class*="rufus"]',
        '[data-testid*="rufus"]',
        '[aria-label*="Rufus"]',
    ],

    # The AI-generated text response block
    "response_text": [
        '[class*="rufus-response"]',
        '[class*="RufusResponse"]',
        '[class*="assistant-message"]',
        '[class*="response-text"]',
        '[data-testid*="response"]',
    ],

    # Individual product cards inside Rufus
    "product_cards": [
        '[class*="rufus-product"]',
        '[class*="ProductCard"]',
        '[class*="product-card"]',
        '[data-testid*="product"]',
        '[class*="rufus"] [class*="product"]',
    ],
}

# ── Fields inside each product card ───────────────────
CARD_SELECTORS = {
    "name":   ['[class*="product-title"]', '[class*="ProductTitle"]',
               '[class*="title"]', 'h3', 'h4', 'a'],
    "price":  ['[class*="price"]', '[data-testid*="price"]', '.a-price'],
    "rating": ['[aria-label*="stars"]', '[aria-label*="out of"]',
               '[class*="rating"]', '[class*="Rating"]'],
    "link":   ['a[href]'],
}


# ──────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────

def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def wait_for_enter(message: str):
    print(message)
    input()


def find_first(page: Page, selectors: list):
    """Try each selector in order, return (element, selector) for first match."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el:
                print(f"   ✅ Matched: {sel}")
                return el, sel
        except Exception:
            continue
    return None, None


def find_all(page: Page, selectors: list):
    """Try each selector, return (list_of_elements, selector) for first match."""
    for sel in selectors:
        try:
            els = page.query_selector_all(sel)
            if els:
                print(f"   ✅ Found {len(els)} items with: {sel}")
                return els, sel
        except Exception:
            continue
    return [], None


def text_from_card(card, selectors: list) -> str | None:
    """Extract text from first matching child inside a card element."""
    for sel in selectors:
        try:
            node = card.query_selector(sel)
            if node:
                text = node.inner_text().strip()
                if text:
                    return text
        except Exception:
            continue
    return None


def attr_from_card(card, selectors: list, attr: str) -> str | None:
    """Get an attribute value from first matching child."""
    for sel in selectors:
        try:
            node = card.query_selector(sel)
            if node:
                val = node.get_attribute(attr)
                if val:
                    return val
        except Exception:
            continue
    return None


# ──────────────────────────────────────────────────────
#  PRODUCT CARD SCRAPER
# ──────────────────────────────────────────────────────

def scrape_product_card(card, rank: int) -> dict:
    """Extract all fields from a single product card element."""

    name  = text_from_card(card, CARD_SELECTORS["name"])
    price = text_from_card(card, CARD_SELECTORS["price"])

    # Rating is usually in aria-label: "4.3 out of 5 stars"
    rating = None
    for sel in CARD_SELECTORS["rating"]:
        node = card.query_selector(sel)
        if node:
            rating = node.get_attribute("aria-label") or node.inner_text().strip()
            if rating:
                break

    # URL
    url = attr_from_card(card, CARD_SELECTORS["link"], "href")
    if url and not url.startswith("http"):
        url = "https://www.amazon.com" + url

    # ASIN from URL  e.g. /dp/B08XYZ1234
    asin = None
    if url:
        import re
        m = re.search(r'/dp/([A-Z0-9]{10})', url)
        if m:
            asin = m.group(1)

    # Badges: "Amazon's Choice", "Best Seller" etc.
    tags = []
    for sel in ['[class*="badge"]', '[class*="Badge"]', '[class*="tag"]', '[class*="label"]']:
        nodes = card.query_selector_all(sel)
        for n in nodes:
            t = n.inner_text().strip()
            if t and len(t) < 60:
                tags.append(t)

    return {
        "rank":   rank,
        "name":   name,
        "price":  price,
        "rating": rating,
        "url":    url,
        "asin":   asin,
        "tags":   list(set(tags)),   # deduplicate
    }


# ──────────────────────────────────────────────────────
#  DOM DUMP (debug helper)
# ──────────────────────────────────────────────────────

def dump_rufus_dom(page: Page):
    """
    If selectors fail, save the raw HTML of any Rufus-related
    element so you can inspect the real class names.
    """
    print("\n🔍 Saving DOM dump for debugging...")
    html = page.evaluate("""() => {
        const candidates = [
            ...document.querySelectorAll(
                '[id*="rufus"], [class*="rufus"], [data-testid*="rufus"]'
            )
        ];
        if (candidates.length === 0) return 'NO RUFUS ELEMENTS FOUND IN DOM';
        // Pick the largest container
        const biggest = candidates.sort(
            (a, b) => b.innerHTML.length - a.innerHTML.length
        )[0];
        return biggest.outerHTML.slice(0, 10000);
    }""")

    with open(DOM_DUMP_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"   Saved: {DOM_DUMP_FILE}")
    print("   Open this file → find real class names → update SELECTORS above.\n")


# ──────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────

def main():
    ensure_output_dir()

    print("━" * 52)
    print("  Amazon Rufus — DOM Extractor (Python)")
    print(f'  Query: "{QUERY}"')
    print("━" * 52)

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900}
        )

        page = context.new_page()
        page.goto("https://www.amazon.com", wait_until="domcontentloaded")

        # ── Instructions ───────────────────────────────────────
        print("\n━" * 52)
        print("  WHAT TO DO IN THE BROWSER:")
        print("  1. Log in to your Amazon account")
        print("  2. Click the Rufus button (chat / sparkle icon)")
        print(f'  3. Type: "{QUERY}"')
        print("  4. Wait for Rufus to fully load the response")
        print("     (products must be visible on screen)")
        print("  5. Come back here and press ENTER")
        print("━" * 52 + "\n")

        wait_for_enter("  → Press ENTER when Rufus has finished loading ...")

        print("\n→ Starting DOM extraction...\n")

        # ── Screenshot ─────────────────────────────────────────
        page.screenshot(path=SCREENSHOT_FILE)
        print(f"📸 Screenshot saved: {SCREENSHOT_FILE}\n")

        # ── Response text ──────────────────────────────────────
        print("→ Looking for AI response text...")
        response_text = None

        el, sel = find_first(page, SELECTORS["response_text"])
        if el:
            response_text = el.inner_text().strip()
        else:
            print("   ⚠️  Response text selector not matched.")

        # ── Product cards ──────────────────────────────────────
        print("\n→ Looking for product cards...")
        products = []

        cards, cards_sel = find_all(page, SELECTORS["product_cards"])

        if cards:
            for i, card in enumerate(cards):
                try:
                    product = scrape_product_card(card, rank=i + 1)
                    products.append(product)
                    print(f"   #{i+1} {product['name'] or '(no name)'}"
                          f"  |  {product['price'] or '?'}"
                          f"  |  {product['rating'] or '?'}")
                except Exception as e:
                    print(f"   ⚠️  Could not scrape card {i+1}: {e}")
        else:
            print("   ⚠️  No product cards found.")
            dump_rufus_dom(page)

        # ── Build final result ──────────────────────────────────
        result = {
            "query":         QUERY,
            "timestamp":     datetime.now().isoformat(),
            "responseText":  response_text or "(not captured — update SELECTORS)",
            "products":      products,
        }

        # ── Save ───────────────────────────────────────────────
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # ── Summary ────────────────────────────────────────────
        print("\n━" * 52)
        print("  RESULT SUMMARY")
        print("━" * 52)
        print(f"  Query      : {QUERY}")
        print(f"  Response   : {'✅ captured' if response_text else '❌ not found'}")
        print(f"  Products   : {len(products)} found")
        print(f"  Saved to   : {RESULT_FILE}")

        if not response_text or not products:
            print("\n  💡 If extraction was incomplete:")
            print(f"     1. Open {SCREENSHOT_FILE}")
            print("        → confirms browser saw the right page")
            print(f"     2. Open {DOM_DUMP_FILE} (if it was created)")
            print("        → find real class names used by Rufus")
            print("     3. Update SELECTORS at the top of this script")
            print("     4. Run again")

        print("━" * 52 + "\n")

        browser.close()

    # Print the result JSON to terminal too
    print("─" * 52)
    print("  OUTPUT JSON:")
    print("─" * 52)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
