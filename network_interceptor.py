"""
Amazon Rufus — Network Interceptor (Final)
==========================================
Every Rufus query is APPENDED to output/rufus_result.json
No previous results are ever overwritten.

Run: python network_interceptor.py
"""

import json, re, os
from datetime import datetime
from playwright.sync_api import sync_playwright

OUTPUT_DIR     = "output"
RESULT_FILE    = os.path.join(OUTPUT_DIR, "rufus_result.json")
RAW_DIR        = os.path.join(OUTPUT_DIR, "raw_streams")
RUFUS_ENDPOINT = "/rufus/cl/streaming"


# ── Parser ────────────────────────────────────────────

def parse_sse(raw):
    chunks = []
    for block in re.split(r'\n\n+', raw.strip()):
        ev = {}
        for line in block.splitlines():
            if line.startswith("event:"): ev["event"] = line[6:].strip()
            elif line.startswith("data:"):
                try:    ev["data"] = json.loads(line[5:].strip())
                except: ev["data"] = line[5:].strip()
        if "event" in ev and "data" in ev:
            chunks.append(ev)
    return chunks


def deep_text(node):
    if isinstance(node, str):  return node
    if isinstance(node, list): return " ".join(deep_text(c) for c in node)
    if isinstance(node, dict):
        if node.get("type") == "text": return deep_text(node.get("children", ""))
        if "children" in node:         return deep_text(node["children"])
    return ""


def get_query(chunks):
    for c in chunks:
        if c["event"] != "affordance": continue
        data = c["data"]
        if not isinstance(data, dict): continue
        for s in data.get("sections", []):
            html = s.get("content", {}).get("data", "") if isinstance(s.get("content"), dict) else ""
            m = re.search(r'rufus-customer-text-wrap[^>]*>.*?<span[^>]*><span>([^<]+)</span>', html, re.DOTALL)
            if m: return m.group(1).strip()
    return ""


def get_response_text(chunks):
    best = ""
    for c in chunks:
        if c["event"] != "inference" or not isinstance(c["data"], dict): continue
        for patch in c["data"].get("patches", []):
            if "markdown_processor" not in patch.get("groupId", ""): continue
            if patch.get("op") not in ("add", "replace"): continue
            text = deep_text(patch.get("value", {})).strip()
            if len(text) > len(best): best = text
    return best


def get_products(chunks):
    products, seen_asins, groups = [], set(), {}
    for c in chunks:
        if c["event"] != "inference" or not isinstance(c["data"], dict): continue
        for patch in c["data"].get("patches", []):
            gid = patch.get("groupId", "")
            if not gid.startswith("asin_cards_"): continue
            val = patch.get("value", {})
            if not isinstance(val, dict): continue
            groups.setdefault(gid, []).append(val)
    for nodes in groups.values():
        for node in nodes:
            find_cards(node, seen_asins, products)
    for i, p in enumerate(products):
        p["rank"] = i + 1
    return products


def find_cards(node, seen_asins, products):
    if not isinstance(node, dict): return
    if node.get("type") == "box":
        on_press = node.get("onPress", {})
        if isinstance(on_press, dict):
            m = re.search(r'/dp/([A-Z0-9]{10})', on_press.get("url", ""))
            if m:
                asin = m.group(1)
                if asin not in seen_asins:
                    seen_asins.add(asin)
                    products.append(parse_card(node, asin))
                return
    for child in node.get("children", []):
        find_cards(child, seen_asins, products)


def parse_card(box, asin):
    name = price = rating = badge = None

    def walk(node):
        nonlocal name, price, rating, badge
        if not isinstance(node, dict): return
        t = node.get("type", "")
        if t == "text" and node.get("lines") and not name:
            text = deep_text(node.get("children", [])).strip()
            if text: name = text
        if t == "rating":
            rating = f"{node.get('valueString','?')} out of 5 stars ({node.get('count','?')} ratings)"
        if t == "price" and not node.get("strikethrough") and not price:
            w = node.get("wholeValue", "")
            if w: price = f"{node.get('currencySymbol','$')}{w}.{node.get('fractionalValue','')}"
        if t == "text":
            raw = deep_text(node.get("children", "")).lower()
            if "amazon's choice" in raw: badge = "Amazon's Choice"
            elif "best seller"   in raw: badge = "Best Seller"
        for child in node.get("children", []): walk(child)

    walk(box)

    if not name:
        for child in box.get("children", []):
            if isinstance(child, dict) and child.get("type") == "image":
                alt = child.get("altText", "").strip()
                if alt: name = alt; break

    if name: name = re.sub(r'\s*\(Packaging May Vary\)', '', name).strip()

    return {
        "rank":   0,
        "name":   name,
        "asin":   asin,
        "url":    f"https://www.amazon.com/dp/{asin}",
        "price":  price,
        "rating": rating,
        "badge":  badge,
    }


# ── Save: APPEND to existing JSON ─────────────────────

def load_existing():
    """Load existing results file, return list of past sessions."""
    if not os.path.exists(RESULT_FILE):
        return []
    try:
        with open(RESULT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Support both old single-result and new multi-session format
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "sessions" in data:
            return data["sessions"]
        if isinstance(data, dict) and "query" in data:
            return [data]   # wrap single old result
    except Exception:
        pass
    return []


def save_all(sessions):
    """Save all sessions to rufus_result.json."""
    output = {
        "total_searches": len(sessions),
        "last_updated":   datetime.now().isoformat(),
        "sessions":       sessions,
    }
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


def build_and_save(raw_body, fallback_query="", session_num=1):
    # Save raw stream with timestamp so nothing is overwritten
    os.makedirs(RAW_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = os.path.join(RAW_DIR, f"stream_{ts}.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write(raw_body)

    # Parse
    chunks   = parse_sse(raw_body)
    query    = get_query(chunks) or fallback_query
    response = get_response_text(chunks)
    products = get_products(chunks)

    # Build this session's result
    new_session = {
        "search_number": session_num,
        "timestamp":     datetime.now().isoformat(),
        "query":         query,
        "responseText":  response,
        "products":      products,
    }

    # Load existing + append + save
    existing = load_existing()
    existing.append(new_session)
    save_all(existing)

    # Terminal output
    print(f"\n{'═'*60}")
    print(f"  Search #{session_num}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"  Query: \"{query}\"")
    print(f"{'═'*60}")
    print(f"\n  Response:\n  {response[:220] or '(empty)'}\n")
    print(f"  Products ({len(products)} found):")
    for p in products:
        print(f"    #{p['rank']}  {p['name']}")
        print(f"         URL    : {p['url']}")
        print(f"         Price  : {p['price'] or 'N/A'}")
        print(f"         Rating : {p['rating'] or 'N/A'}")
        print(f"         Badge  : {p['badge'] or 'N/A'}")
    print(f"\n  ✅  Appended to {RESULT_FILE}  (total: {len(existing)} searches)")
    print(f"  📄  Raw stream  → {raw_path}")

    return new_session


# ── Main ──────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("━"*60)
    print("  Amazon Rufus — Network Interceptor")
    print("━"*60)
    print("  ✅  Every query is APPENDED — nothing is overwritten")
    print("  ✅  Raw streams saved individually in output/raw_streams/")
    print("  ✅  Browser stays open until YOU close it")
    print("━"*60 + "\n")

    # Count existing sessions so we continue numbering
    existing_count = len(load_existing())
    session_count  = [existing_count]

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

        def handle_route(route, request):
            if RUFUS_ENDPOINT not in request.url:
                route.continue_()
                return
            query = ""
            try:
                pd    = json.loads(request.post_data or "{}")
                query = pd.get("queryContext", {}).get("query", "")
            except Exception:
                pass
            if not query:
                route.continue_()
                return

            session_count[0] += 1
            n = session_count[0]
            print(f"  🎯 Search #{n}: \"{query}\" — fetching full stream...")

            response = route.fetch()
            raw      = response.body().decode("utf-8", errors="replace")
            print(f"     ✓ {len(raw):,} bytes, {raw.count('id:CHUNK')} chunks")

            build_and_save(raw, fallback_query=query, session_num=n)
            route.fulfill(response=response)

        page.route(f"**{RUFUS_ENDPOINT}**", handle_route)

        print("→ Opening amazon.com...\n")
        page.goto("https://www.amazon.com", wait_until="domcontentloaded")

        print("━"*60)
        print("  1. Log in to Amazon")
        print("  2. Click the Rufus button (chat/sparkle icon)")
        print('  3. Ask a question e.g. "best hair serum for men"')
        print("  4. Wait until all products are visible in Rufus")
        print("  5. Ask as many questions as you want — all saved!")
        print("  6. Close browser when done")
        print("━"*60)
        print("\n📡 Waiting for Rufus queries...\n")

        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            browser.close()
        except Exception:
            pass

    print(f"\n✅  Session ended. All results in {RESULT_FILE}")


if __name__ == "__main__":
    main()
