import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from nameparser import HumanName

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS

try:
    from google import genai
    HAS_GOOGLE_GENAI = True
except ImportError:
    HAS_GOOGLE_GENAI = False


# ==============================================================================
# SECTION 8 & 16: STRICT NON-PERSON WORDS & HUMAN NAME LEXICON
# ==============================================================================

REJECT_NAME_FRAGMENTS = [
    "has been", "borrowed husband", "and operator", "responsible for", "phoneemail",
    "brings over", "same day handy", "meet the owner", "our founder", "about us",
    "contact us", "privacy policy", "terms of service", "all rights reserved",
    "cookie policy", "home page", "view profile", "read more", "click here",
    "learn more", "business owner", "franchise owner", "co-founder", "managing partner",
    "managing director", "general manager", "executive director", "show all", "show more",
    "get quote", "free estimate", "quote get"
]

NON_PERSON_WORDS = {
    "construction", "roofing", "roof", "roofs", "crafters", "services", "service", "contractor", "contractors",
    "company", "inc", "llc", "ltd", "corp", "corporation", "group", "solutions", "handyman", "plumbing",
    "electrical", "hvac", "auto", "car", "care", "dental", "clinic", "hospital", "store", "shop", "center",
    "club", "bar", "grill", "cafe", "bazaar", "market", "bakery", "kitchen", "house", "studio", "press",
    "media", "agency", "consulting", "management", "enterprises", "holdings", "partners", "ventures",
    "capital", "logistics", "tech", "technology", "software", "digital", "design", "creative", "global",
    "international", "national", "american", "texas", "houston", "dallas", "austin", "karachi", "pakistan",
    "stone", "castle", "food", "tower", "clock", "ez", "tx", "same", "day", "handy", "borrowed", "husband",
    "was", "been", "has", "have", "had", "is", "are", "were", "be", "being", "by", "for", "with", "about",
    "from", "team", "our", "your", "their", "owner", "founder", "president", "ceo", "business", "location",
    "page", "site", "contact", "info", "phone", "email", "address", "search", "google", "bing", "linkedin",
    "facebook", "twitter", "instagram", "yelp", "bbb", "chamber", "review", "rating", "stars", "details",
    "overview", "home", "story", "who", "we", "us", "they", "them", "more", "less", "all", "rights",
    "reserved", "privacy", "policy", "terms", "conditions", "copyright", "link", "url", "http", "https",
    "www", "com", "net", "org", "co", "io", "and", "or", "not", "but", "also", "just", "like", "such",
    "than", "then", "into", "over", "under", "after", "before", "between", "through", "during", "without",
    "within", "along", "following", "across", "behind", "beyond", "plus", "except", "until", "upon",
    "towards", "inside", "outside", "near", "off", "out",
    "quote", "quotes", "get", "got", "free", "estimate", "estimates", "call", "now", "book", "online",
    "appointment", "schedule", "today", "view", "click", "read", "send", "message", "submit", "form",
    "menu", "order", "projects", "reviews", "gallery", "faq", "faqs", "blog", "news", "careers", "jobs",
    "apply", "login", "sign", "up", "in", "portal", "client", "customer", "support", "help", "map",
    "directions", "locations", "hours", "open", "close", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "commercial", "residential", "industrial", "master", "top", "best", "quality", "prime", "pro",
    "professional", "experts", "specialists", "depot", "mart", "express", "fast", "quick", "direct",
    "web", "city", "state", "street", "road", "avenue", "drive", "suite", "unit", "building"
}

COMMON_TITLES = [
    r"\bMr\.\b", r"\bMs\.\b", r"\bMrs\.\b", r"\bDr\.\b",
    r"\bOwner\b", r"\bFounder\b", r"\bPresident\b", r"\bCEO\b",
    r"\bCo-Founder\b", r"\bProprietor\b", r"\bPrincipal\b"
]

PHONE_INVALID_PATTERNS = [
    r"^\d{1,2}\.\d+$",       # Coordinates e.g. 033.1502614
    r"^\d{4}-\d{2}-\d{2}$",   # Dates e.g. 2024-05-01
    r"^\d{5}$",              # ZIP codes
    r"^\d{10,15}\.\d+$",     # Analytics IDs
]


# ==============================================================================
# 1. PHONE HELPERS & VALIDATION (Sections 9, 10, 11)
# ==============================================================================

def clean_text(text):
    if not text:
        return ""
    return " ".join(str(text).split()).strip()

def is_valid_phone(phone_str):
    if not phone_str:
        return False
    phone_clean = clean_text(phone_str)
    
    digits_only = re.sub(r"\D", "", phone_clean)
    if len(digits_only) < 7 or len(digits_only) > 15:
        return False
        
    for pattern in PHONE_INVALID_PATTERNS:
        if re.search(pattern, phone_clean):
            return False
            
    return True

def normalize_phone_number(phone_str):
    if not is_valid_phone(phone_str):
        return ""
    phone_clean = clean_text(phone_str)
    return phone_clean

def extract_phones_from_text(text):
    if not text:
        return []
    phone_regex = r"(\+?\d{1,3}[\s\-.()]?)?\(?\d{3}\)?[\s\-.()]?\d{3}[\s\-.()]?\d{4}"
    valid_phones = []
    
    raw_matches = re.finditer(phone_regex, text)
    for match in raw_matches:
        raw_phone = match.group(0).strip()
        if is_valid_phone(raw_phone):
            valid_phones.append(normalize_phone_number(raw_phone))
            
    return list(dict.fromkeys(valid_phones))


# ==============================================================================
# 2. NAME VALIDATION & CLEANING (Section 8)
# ==============================================================================

def is_valid_owner_name(name):
    if not name:
        return False
    name_clean = clean_text(name)
    name_lower = name_clean.lower()
    
    if len(name_clean) < 3 or len(name_clean) > 40:
        return False
        
    for frag in REJECT_NAME_FRAGMENTS:
        if frag in name_lower:
            return False
            
    if re.search(r"[0-9@#$%^&*()_+={}\[\]\\|/<>?:;]", name_clean):
        return False
        
    hn = HumanName(name_clean)
    if not hn.first or not hn.last:
        return False
        
    words = name_clean.split()
    if len(words) < 2 or len(words) > 4:
        return False
        
    # EVERY word in the name must start with an uppercase letter
    for w in words:
        w_strip = w.strip(".,-")
        if not w_strip:
            continue
        if not w_strip[0].isupper():
            return False
        if w_strip.lower() in NON_PERSON_WORDS:
            return False
            
    return True

def clean_owner_name(raw_name):
    if not raw_name:
        return ""
    name = clean_text(raw_name)
    for title_pat in COMMON_TITLES:
        name = re.sub(title_pat, "", name, flags=re.IGNORECASE)
    name = clean_text(name)
    if is_valid_owner_name(name):
        return name
    return ""


# ==============================================================================
# 3. PUBLIC SEARCH QUERY GENERATOR & EXECUTOR (Sections 4, 5, 6)
# ==============================================================================

def execute_ddg_search(query, max_results=6):
    results = []
    try:
        ddgs = DDGS()
        ddg_gen = ddgs.text(query, max_results=max_results)
        if ddg_gen:
            for r in ddg_gen:
                results.append({
                    "title": clean_text(r.get("title", "")),
                    "snippet": clean_text(r.get("body", "")),
                    "url": r.get("href", "")
                })
    except Exception as e:
        print(f"  [Search Warning] DDG search error for query '{query}': {e}")
    return results

def search_public_evidence(business_name, city="", state=""):
    snippets = []
    queries = [
        f'"{business_name}" owner',
        f'"{business_name}" "owned by"',
        f'"{business_name}" founder',
        f'"{business_name}" "founded by"',
        f'"{business_name}" "owner and operator"',
        f'site:linkedin.com/in "{business_name}" owner',
        f'site:facebook.com "{business_name}" owner',
        f'site:bbb.org "{business_name}"',
        f'site:chamberofcommerce.com "{business_name}"'
    ]
    if city or state:
        loc_str = f"{city} {state}".strip()
        queries.insert(1, f'"{business_name}" "{loc_str}" owner')
        
    for q in queries:
        print(f"  [Searching Web] Query: {q}")
        res = execute_ddg_search(q, max_results=4)
        for item in res:
            text_block = f"Source: {item['url']}\nTitle: {item['title']}\nSnippet: {item['snippet']}"
            snippets.append(text_block)
        time.sleep(0.5)
        
    return snippets


# ==============================================================================
# 4. DEEP WEBSITE CRAWLER FOR OWNER DETAILS (Sections 2 & 3)
# ==============================================================================

TARGET_NAV_KEYWORDS = [
    "about", "team", "owner", "leadership", "founder", "story", "management", "contact"
]

def crawl_website_for_owner_evidence(website_url, max_pages=5):
    evidence_blocks = []
    phone_from_website = ""
    
    if not website_url or not website_url.startswith("http"):
        return evidence_blocks, phone_from_website
        
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(website_url, headers=headers, timeout=10)
        if resp.status_code >= 400:
            return evidence_blocks, phone_from_website
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        body_text = clean_text(soup.get_text(" "))
        evidence_blocks.append(f"Source: {website_url} (Homepage)\nContent: {body_text[:2000]}")
        
        phones = extract_phones_from_text(body_text)
        if phones and not phone_from_website:
            phone_from_website = phones[0]
            
        base_domain = urlparse(website_url).netloc.lower().replace("www.", "")
        internal_links = set()
        
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full_url = urljoin(website_url, href)
            parsed = urlparse(full_url)
            domain = parsed.netloc.lower().replace("www.", "")
            
            if domain == base_domain:
                link_text = clean_text(a.get_text(" ")).lower()
                href_lower = full_url.lower()
                if any(kw in href_lower or kw in link_text for kw in TARGET_NAV_KEYWORDS):
                    internal_links.add(full_url)
                    
        for page_url in list(internal_links)[:max_pages]:
            try:
                p_resp = requests.get(page_url, headers=headers, timeout=8)
                if p_resp.status_code < 400:
                    p_soup = BeautifulSoup(p_resp.text, "html.parser")
                    p_text = clean_text(p_soup.get_text(" "))
                    evidence_blocks.append(f"Source: {page_url}\nContent: {p_text[:2500]}")
                    
                    if not phone_from_website:
                        p_phones = extract_phones_from_text(p_text)
                        if p_phones:
                            phone_from_website = p_phones[0]
            except Exception:
                pass
            time.sleep(0.3)
            
    except Exception as e:
        print(f"  [Website Crawl Warning] Could not crawl {website_url}: {e}")
        
    return evidence_blocks, phone_from_website


# ==============================================================================
# 5. EVIDENCE ANALYZER & LLM RULE (Section 16)
# ==============================================================================

OWNER_ROLE_PATTERNS = [
    # Pattern 1: "founded by Frank Stilley" or "owned by Jacey Gray"
    r"\b(?:founded by|owned by|started by|established by|led by)\s+([A-Z][a-z]{1,19}(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]{1,19}(?:\-[A-Z][a-z]{1,19})?)\b",
    
    # Pattern 2: "Frank Stilley, Owner" or "Jacey Gray - Founder"
    r"\b([A-Z][a-z]{1,19}(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]{1,19}(?:\-[A-Z][a-z]{1,19})?)\s*(?:,|\-|\:|\=|\(|\))\s*(?:is\s+)?(?:the\s+)?(?:owner|founder|co-founder|president|proprietor|franchise owner|franchisee|owner & operator|owner and operator|principal|ceo)\b",
    
    # Pattern 3: "Owner: Frank Stilley" or "Founder: Jacey Gray"
    r"\b(?:owner|founder|co-founder|president|proprietor|franchise owner|franchisee|ceo)\s*(?:,|\:|\-|\=|\bby\b|\bis\b|\bwas\b)\s*([A-Z][a-z]{1,19}(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]{1,19}(?:\-[A-Z][a-z]{1,19})?)\b",
    
    # Pattern 4: "Frank Stilley founded..." or "Jacey Gray owns..."
    r"\b([A-Z][a-z]{1,19}(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]{1,19}(?:\-[A-Z][a-z]{1,19})?)\s+(?:founded|owns|started|established)\b"
]

def analyze_evidence_with_llm(business_name, evidence_list):
    """
    Uses Google GenAI SDK if API key available; otherwise returns None.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key or not HAS_GOOGLE_GENAI:
        return None
        
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""
You are an evidence analyzer. Based ONLY on the supplied public evidence text below, identify the person explicitly supported as the owner, founder, franchise owner, proprietor, principal, president or equivalent controlling operator of the business "{business_name}".

Rules:
1. Only identify a real person's name (e.g. John Smith, Frank Stilley, Jacey Gray).
2. If evidence is ambiguous, missing, or unsupported, output: UNKNOWN
3. Never invent names from general knowledge.

Evidence:
{chr(10).join(evidence_list[:10])}

Output EXACTLY in this format:
Owner Name: <Name or UNKNOWN>
Confidence: <high/medium/low>
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        text = response.text.strip()
        match = re.search(r"Owner Name:\s*(.+)", text)
        if match:
            cand = match.group(1).strip()
            cleaned = clean_owner_name(cand)
            if cleaned:
                return cleaned
    except Exception as e:
        print(f"  [LLM Warning] GenAI call failed: {e}")
        
    return None

def analyze_evidence_for_owner(business_name, evidence_list):
    """
    Evaluates evidence text for explicit ownership connection.
    Implements Section 16 LLM Rule logic strictly based on public evidence.
    Returns: (owner_name, owner_phone, role, confidence)
    """
    # 1. Try GenAI LLM API if key is present
    llm_name = analyze_evidence_with_llm(business_name, evidence_list)
    if llm_name:
        return llm_name, "", "Owner", "high"
        
    # 2. High-precision rule-based evidence analyzer
    candidate_scores = {}
    found_owner_phone = ""
    
    combined_evidence = "\n\n".join(evidence_list)
    
    for pattern in OWNER_ROLE_PATTERNS:
        matches = re.finditer(pattern, combined_evidence, re.IGNORECASE)
        for match in matches:
            candidate = match.group(1).strip()
            cleaned = clean_owner_name(candidate)
            if cleaned:
                candidate_scores[cleaned] = candidate_scores.get(cleaned, 0) + 1
                
    if candidate_scores:
        top_candidate = max(candidate_scores, key=candidate_scores.get)
        
        name_esc = re.escape(top_candidate)
        match_near = re.search(f"{name_esc}.{{0,100}}?({extract_phones_from_text(combined_evidence)[0] if extract_phones_from_text(combined_evidence) else ''})", combined_evidence, re.DOTALL)
        if match_near and match_near.group(1):
            found_owner_phone = match_near.group(1)
            
        confidence = "high" if candidate_scores[top_candidate] >= 2 else "medium"
        return top_candidate, found_owner_phone, "Owner", confidence
        
    return "UNKNOWN", "", "", "none"


# ==============================================================================
# 6. INTEGRATED LEAD RESEARCH FUNCTION (Main Entrypoint per listing)
# ==============================================================================

def research_and_verify_lead(listing_data):
    """
    Takes Google Maps listing data, runs deep multi-source research,
    applies owner validation, phone priority hierarchy, and returns final verified record or None (if skipped).
    """
    biz_name = listing_data.get("name", "")
    gmaps_phone = listing_data.get("phone_number", "")
    website_url = listing_data.get("website_link", "")
    g_rating = listing_data.get("google_rating", "")
    g_reviews = listing_data.get("review_count", "")
    address = listing_data.get("address", "")
    
    city, state = "", ""
    if address:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2:
            city = parts[-2]
        if len(parts) >= 1:
            state = parts[-1]
            
    print(f"\n[Researching Lead] Business: {biz_name} | City: {city}")
    
    all_evidence = []
    website_phone = ""
    
    # 1. Crawl Official Website if present
    if website_url:
        print(f"  [Step 1] Crawling website: {website_url}")
        web_evidence, website_phone = crawl_website_for_owner_evidence(website_url)
        all_evidence.extend(web_evidence)
        
    # 2. Search Public Internet Sources (Google / Bing / DDG / LinkedIn / BBB / Chamber)
    print(f"  [Step 2] Executing public web searches for owner...")
    web_search_evidence = search_public_evidence(biz_name, city, state)
    all_evidence.extend(web_search_evidence)
    
    # 3. Analyze Evidence for Owner (LLM / Evidence Rule Section 16)
    owner_name, owner_prof_phone, role, confidence = analyze_evidence_for_owner(biz_name, all_evidence)
    
    print(f"  [Step 3] Owner Evidence Result -> Name: {owner_name} | Confidence: {confidence}")
    
    # SECTION 17 RULE: If Owner Name cannot be verified, skip the lead.
    if owner_name == "UNKNOWN" or not is_valid_owner_name(owner_name):
        print(f"  [SKIP LEAD] Unverified owner for: {biz_name}")
        return None
        
    # SECTION 10 & 11 PHONE PRIORITY HIERARCHY:
    final_phone = ""
    if owner_prof_phone and is_valid_phone(owner_prof_phone):
        final_phone = owner_prof_phone
        print(f"  [Phone Priority 1] Selected Owner Professional Phone: {final_phone}")
    elif website_phone and is_valid_phone(website_phone):
        final_phone = website_phone
        print(f"  [Phone Priority 2] Selected Business Website Phone: {final_phone}")
    elif gmaps_phone and is_valid_phone(gmaps_phone):
        final_phone = gmaps_phone
        print(f"  [Phone Priority 4] Fallback to Google Maps Phone: {final_phone}")
        
    # SECTION 17 RULE: If no valid phone exists anywhere, skip lead.
    if not final_phone:
        print(f"  [SKIP LEAD] No valid phone found anywhere for: {biz_name}")
        return None
        
    # SECTION 20 FINAL SPREADSHEET OUTPUT SCHEMA (Exact 6 columns):
    return {
        "Owner Name": owner_name,
        "Business Name": biz_name,
        "Owner Phone Number": final_phone,
        "Website URL": website_url,
        "Google Rating": g_rating,
        "Review Count": g_reviews
    }
