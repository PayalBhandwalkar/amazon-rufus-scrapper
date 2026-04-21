"""
Rufus Stream Parser
Run: python parse_stream.py
Reads output/rufus_raw_stream.txt → output/rufus_result.json
"""
import json, re, os

INPUT  = os.path.join("output", "rufus_raw_stream.txt")
OUTPUT = os.path.join("output", "rufus_result.json")


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
        if node.get("type") == "text": return deep_text(node.get("children",""))
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
    """
    The AI intro text lives in groupId='markdown_processor_...'
    We want the LONGEST final value at path '/' for that group only.
    """
    best = ""
    for c in chunks:
        if c["event"] != "inference" or not isinstance(c["data"], dict): continue
        for patch in c["data"].get("patches", []):
            gid = patch.get("groupId", "")
            # Only the markdown_processor group has the intro sentence
            if "markdown_processor" not in gid: continue
            if patch.get("op") not in ("add","replace"): continue
            # use any path, take longest overall
            text = deep_text(patch.get("value", {})).strip()
            if len(text) > len(best):
                best = text
    return best


def get_products(chunks):
    """
    Each product is an asinCard box inside groupId='asin_cards_...'
    The box has:
      - onPress.url  → /dp/ASIN  (product URL)
      - children[0]  → image (altText = product name fallback)
      - children[1]  → container with: name (text/lines:2), rating, price
    The asinFooter patch adds a description line.
    """
    products   = []
    seen_asins = set()

    # Collect all patch values grouped by groupId
    groups = {}
    for c in chunks:
        if c["event"] != "inference" or not isinstance(c["data"], dict): continue
        for patch in c["data"].get("patches", []):
            gid = patch.get("groupId","")
            if not gid.startswith("asin_cards_"): continue
            val = patch.get("value",{})
            if not isinstance(val, dict): continue
            if gid not in groups: groups[gid] = []
            groups[gid].append(val)

    # Extract asinCard boxes from each group
    for gid, nodes in groups.items():
        for node in nodes:
            find_asin_cards(node, seen_asins, products)

    for i, p in enumerate(products):
        p["rank"] = i + 1
    return products


def find_asin_cards(node, seen_asins, products):
    if not isinstance(node, dict): return
    # An asinCard box: type=box with onPress containing /dp/ASIN
    if node.get("type") == "box":
        on_press = node.get("onPress", {})
        if isinstance(on_press, dict):
            url = on_press.get("url","")
            m = re.search(r'/dp/([A-Z0-9]{10})', url)
            if m:
                asin = m.group(1)
                if asin not in seen_asins:
                    seen_asins.add(asin)
                    products.append(parse_card(node, asin))
                return
    for child in node.get("children", []):
        find_asin_cards(child, seen_asins, products)


def parse_card(box, asin):
    name = price = rating = badge = None

    def walk(node):
        nonlocal name, price, rating, badge
        if not isinstance(node, dict): return

        t = node.get("type","")

        # Product name: text node with lines=2
        if t == "text" and node.get("lines") and not name:
            children = node.get("children",[])
            text = deep_text(children).strip()
            if text: name = text

        # Rating
        if t == "rating":
            rating = f"{node.get('valueString','?')} out of 5 stars ({node.get('count','?')} ratings)"

        # Price (not strikethrough, not per-unit)
        if t == "price" and not node.get("strikethrough") and not price:
            w = node.get("wholeValue","")
            f = node.get("fractionalValue","")
            s = node.get("currencySymbol","$")
            if w: price = f"{s}{w}.{f}"

        # Badge detection in any text
        if t == "text":
            raw = deep_text(node.get("children","")).lower()
            if "amazon's choice" in raw: badge = "Amazon's Choice"
            elif "best seller"   in raw: badge = "Best Seller"

        for child in node.get("children",[]):
            walk(child)

    walk(box)

    # Fallback name from image altText
    if not name:
        for child in box.get("children",[]):
            if isinstance(child, dict) and child.get("type") == "image":
                alt = child.get("altText","").strip()
                if alt: name = alt; break

    # Clean up name
    if name:
        name = re.sub(r'\s*\(Packaging May Vary\)', '', name).strip()

    return {
        "rank":   0,
        "name":   name,
        "asin":   asin,
        "url":    f"https://www.amazon.com/dp/{asin}",
        "price":  price,
        "rating": rating,
        "badge":  badge,
    }


def main():
    os.makedirs("output", exist_ok=True)
    if not os.path.exists(INPUT):
        print(f"❌ Not found: {INPUT}\n   Run network_interceptor.py first.")
        return

    with open(INPUT, encoding="utf-8") as f:
        raw = f.read()

    chunks   = parse_sse(raw)
    query    = get_query(chunks)
    response = get_response_text(chunks)
    products = get_products(chunks)

    result = {"query": query, "responseText": response, "products": products}

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n✅  Saved → {OUTPUT}")


if __name__ == "__main__":
    main()
