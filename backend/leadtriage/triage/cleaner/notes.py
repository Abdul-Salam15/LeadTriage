"""
PHASE 3.11: NOTES TEXT CLEANING & ANALYSIS

Process:
  1. Strip whitespace / normalize
  2. Fix encoding / line breaks
  3. Detect language (english vs other)
  4. Flag suspicious content:
     - SPAM, NOT_BUYER, WRONG_FIT, COMPETITOR, NOT_DECISION_MAKER, DUPLICATE
  5. Extract key signals via regex (no LLM)
  6. Text metrics (word count, sentences, engagement, specificity)
  7. Rule-based sentiment
  8. Extract key info (company type, pain category, tools, team size, timeline)
"""

from __future__ import annotations

import re

# --- Language detection (Phase 13: flag non-English while still processing) ---

# Rough Unicode script ranges: CJK, Cyrillic, Arabic, Greek, Devanagari, etc.
NON_LATIN_SCRIPT = re.compile(
    r"[\u0400-\u04FF\u0600-\u06FF\u0590-\u05FF\u0900-\u097F\u3040-\u30FF"
    r"\u3400-\u4DBF\u4E00-\u9FFF\uAC00-\uD7AF\u0370-\u03FF]"
)
# Heavy diacritic usage (é, ñ, ü, ç ...) often indicates non-English Latin scripts.
DIACRITIC_CHARS = re.compile(r"[àáâãäåæçèéêëìíîïñòóôõöøùúûüýÿß]")

# Common words that strongly indicate a specific non-English European language.
LANGUAGE_MARKER_WORDS = {
    "SPANISH": ["usted", "estamos", "queremos", "hola", "gracias", "necesitamos", "para", "contacto"],
    "FRENCH": ["bonjour", "nous", "merci", "avec", "notre", "votre", "pouvez", "solution"],
    "GERMAN": ["bitte", "wir", "unser", "ihre", "können", "gerne", "mit", "und"],
    "PORTUGUESE": ["olá", "nosso", "você", "precisamos", "contato", "obrigado"],
}


def detect_notes_language(text: str) -> dict:
    """Heuristic language detection. English/Pidgin still processed; clearly
    non-English scripts or strong marker words get flagged NON_ENGLISH."""
    if not text:
        return {"notes_language": "ENGLISH", "notes_language_confidence": 0.0, "notes_is_non_english": False}

    lowered = text.lower()
    total_chars = max(len([c for c in text if not c.isspace()]), 1)
    non_latin = len(NON_LATIN_SCRIPT.findall(text))
    diacritics = len(DIACRITIC_CHARS.findall(lowered))
    non_ascii_ratio = (non_latin + diacritics) / total_chars

    # Script-based detection is strong evidence.
    if non_latin > 0:
        ratio = non_latin / total_chars
        if ratio >= 0.02:
            return {
                "notes_language": "NON_ENGLISH",
                "notes_language_confidence": min(0.9, 0.5 + ratio),
                "notes_is_non_english": True,
            }

    # Diacritic-heavy text (e.g. Spanish/French/German without strong markers).
    if diacritics > 0 and non_ascii_ratio >= 0.10:
        return {
            "notes_language": "NON_ENGLISH",
            "notes_language_confidence": min(0.75, 0.4 + non_ascii_ratio),
            "notes_is_non_english": True,
        }

    # Strong marker-word evidence.
    best_lang, best_hits = None, 0
    for lang, words in LANGUAGE_MARKER_WORDS.items():
        hits = sum(1 for w in words if re.search(rf"\b{w}\b", lowered))
        if hits > best_hits:
            best_lang, best_hits = lang, hits
    if best_lang and best_hits >= 2:
        return {
            "notes_language": best_lang,
            "notes_language_confidence": min(0.85, 0.4 + 0.1 * best_hits),
            "notes_is_non_english": True,
        }

    return {
        "notes_language": "ENGLISH",
        "notes_language_confidence": max(0.2, 1.0 - non_ascii_ratio),
        "notes_is_non_english": False,
    }

# --- Flag patterns (ordered: spam, then non-buyer categories) ---

SPAM_PATTERNS = [
    r"won\s*[$£€]\s*\d",
    r"\$1,\d{3},000",
    r"click here to claim",
    r"buy followers",
    r"cheap smm panel",
    r"dm for rates",
    r"reply stop to opt out",
    r"backlink",
    r"high.?da backlinks",
    r"rank #1 guaranteed",
    r"bulk email",
    r"partner with us and rank",
]

NOT_BUYER_PATTERNS = [
    r"not looking to buy",
    r"not a buyer",
    r"not a direct buyer",
    r"not a client",
    r"looking for a role",
    r"looking for a job",
    r"looking for job",
    r"need developers",
    r"looking for work",
    r"attach(?:ing|ed)? my (?:cv|resume)",
    r"want to join your team",
    r"are you hiring",
    r"i'd love to join",
    r"job opportunity",
    r"loving what you do.*learning",
    r"free template or resources",
    r"not looking to purchase",
]

WRONG_FIT_PATTERNS = [
    r"offshore dev",
    r"offering dev team",
    r"hiring developers",
    r"job opportunity",
    r"place candidates",
    r"automation devs on our bench",
    r"embed a dev",
    r"embedded dev",
]

COMPETITOR_PATTERNS = [
    r"competing automation agency",
    r"i actually run a competing",
    r"run a competing",
    r"see how you package",
    r"seeing how you package",
    r"mostly researching the market",
    r"fellow agency owner",
]

NOT_DECISION_MAKER_PATTERNS = [
    r"vc here",
    r"portfolio compan",
    r"student doing project",
    r"university project",
    r"journalist",
    r"interview",
    r"final year student",
    r"cs student",
    r"bootcamp grad",
    r"research(?:er|ing)?",
    r"learning interest",
    r"can you share how you built",
    r"doing a university",
]

DUPLICATE_PATTERNS = [
    r"\(duplicate submission\)",
    r"\(duplicate\)",
    r"\[duplicate\]",
    r"\bduplicate\b",
]

# --- Key signal patterns ---

BUDGET_SIGNALS = {
    "budget_approved": r"budget\s+(?:is\s+|has been\s+)?approved",
    "budget_ready": r"budget.*ready",
    "has_budget": r"\bhave some budget\b",
    "budget_locked": r"budget\s+(?:not\s+)?locked",
    "price_sensitive": r"price sensitive",
    "no_budget": r"no real budget|can'?t really pay|tiny budget|budget way below|no budget",
}

TIMELINE_SIGNALS = {
    "timeline_asap": r"\basap\b",
    "timeline_this_month": r"this month|start asap|start this month|move in 2 weeks|within 2 weeks|this week",
    "timeline_quarter": r"this quarter|q[1-4]\b",
    "timeline_2_weeks": r"in the next 2 weeks|in 2 weeks|next 2 weeks",
    "timeline_month_decision": r"decision this month|decision in about a month",
    "timeline_urgent": r"urgent|priority|start asap|wants to start asap",
}

AUTHORITY_SIGNALS = {
    "i_make_the_call": r"i make the call",
    "decision_is_mine": r"decision is mine",
    "my_priority": r"this is my priority|my priority to solve",
    "loop_in_team": r"loop in the team",
    "not_sure_who_signs": r"not sure who signs off|not sure who signs",
}

COMPARISON_SIGNALS = {
    "comparing_options": r"comparing a few options|comparing options|evaluating",
    "exploring_options": r"exploring|curious about|not totally sure|not sure what we need",
    "ready_to_buy": r"want(?:s)? to start asap|ready to pilot|keen to move fast|want to start this month",
}

USE_CASE_KEYWORDS = {
    "Lead Routing": [r"lead rout", r"routing", r"manual lead rout"],
    "Follow-up Automation": [r"follow.?up", r"chasing", r"following up"],
    "Lead Enrichment": [r"enrich", r"scoring leads"],
    "Reporting": [r"report", r"client reports", r"building client reports"],
    "CRM Sync": [r"crm", r"hubspot", r"between apollo"],
    "Lead Qualification": [r"qualif", r"inbound leads"],
    "Inbox Triage": [r"triag", r"flooded shared inbox", r"shared inbox"],
    "Call Summaries": [r"call recording", r"summariz"],
    "Research & Outreach": [r"researching prospects", r"first-touch", r"drafting first-touch"],
    "Ad Budget Pacing": [r"pacing ad budgets", r"ad budgets", r"budgets across dozens"],
    "Copy-Paste Automation": [r"copy.?past", r"between spreadsheets"],
    "Chatbot": [r"chatbot", r"lead chatbot"],
}

PAIN_KEYWORDS = {
    "manual work": [r"by hand", r"manually", r"manual"],
    "time wasted": [r"eating our week", r"eating the week", r"wasted", r"takes too long"],
    "stale leads": [r"leads go stale", r"hot leads go stale"],
    "process pain": [r"pain", r"chasing"],
    "scaling": [r"dozens of accounts", r"40\+ clients", r"6 tools"],
}

TOOLS_KEYWORDS = {
    "Apollo": [r"apollo"],
    "HubSpot": [r"hubspot"],
    "Salesforce": [r"salesforce"],
    "Pipedrive": [r"pipedrive"],
    "Email": [r"\bemail"],
    "WhatsApp": [r"whatsapp"],
    "CRM": [r"\bcrm\b"],
    "Spreadsheets": [r"spreadsheet", r"excel", r"sheets"],
}

POSITIVE_WORDS = {"love", "great", "excited", "looking forward", "happy", "awesome", "excellent"}
NEGATIVE_WORDS = {
    "not interested", "no budget", "uncertain", "depends", "can't pay",
    "way below", "not a buyer", "vague", "not sure",
}

# Strong intent signals count as positive sentiment.
POSITIVE_INTENT = re.compile(
    r"budget approved|start asap|keen to move fast|this is my priority|want(?:s)? to start|ready to pilot|priority to solve",
    re.IGNORECASE,
)


def _count_paragraphs(text: str) -> int:
    """Count paragraphs separated by one or more newlines (blank or single \n)."""
    if not text:
        return 0
    return len([seg for seg in re.split(r"\n+", text) if seg.strip()])


def clean_notes(raw) -> dict:
    original = "" if raw is None else str(raw).strip()
    paragraph_count = _count_paragraphs(original)

    if original == "":
        return {
            "notes": "",
            "notes_original": "",
            "notes_is_missing": True,
            "notes_length_words": 0,
            "notes_paragraph_count": 0,
            "notes_engagement_level": "LOW",
            "notes_sentiment": "NEUTRAL",
            "notes_specificity": "LOW",
            "notes_quality_score": 0.0,
            "extracted_company_type": None,
            "extracted_pain_category": None,
            "extracted_signals": [],
            "flagged_as": [],
            "notes_is_suspicious": False,
            "notes_is_spam": False,
            "notes_indicates_buyer": False,
            "notes_flag": "MISSING_NOTES",
            "notes_language": "ENGLISH",
            "notes_language_confidence": 0.0,
            "notes_is_non_english": False,
        }

    # Normalize text.
    text = original.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text).strip()

    # Language detection (Phase 13): flag non-English but keep processing.
    language = detect_notes_language(text)

    flagged_as = []
    is_suspicious = False
    is_spam = False

    # Detect flags in priority order (duplicate first, spam first).
    if any(re.search(p, text, re.IGNORECASE) for p in DUPLICATE_PATTERNS):
        flagged_as.append("DUPLICATE")
        is_suspicious = True
    if any(re.search(p, text, re.IGNORECASE) for p in SPAM_PATTERNS):
        flagged_as.append("SPAM")
        is_suspicious = True
        is_spam = True
    if any(re.search(p, text, re.IGNORECASE) for p in NOT_BUYER_PATTERNS):
        flagged_as.append("NOT_BUYER")
    if any(re.search(p, text, re.IGNORECASE) for p in WRONG_FIT_PATTERNS):
        flagged_as.append("WRONG_FIT")
    if any(re.search(p, text, re.IGNORECASE) for p in COMPETITOR_PATTERNS):
        flagged_as.append("COMPETITOR")
        is_suspicious = True
    if any(re.search(p, text, re.IGNORECASE) for p in NOT_DECISION_MAKER_PATTERNS):
        flagged_as.append("NOT_DECISION_MAKER")

    # Signals.
    signals = []
    for name, pat in {**BUDGET_SIGNALS, **TIMELINE_SIGNALS, **AUTHORITY_SIGNALS, **COMPARISON_SIGNALS}.items():
        if re.search(pat, text, re.IGNORECASE):
            signals.append(name)

    # Use cases / pain points / tools.
    use_cases = []
    for uc, pats in USE_CASE_KEYWORDS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in pats):
            use_cases.append(uc)
    pain_points = []
    for pp, pats in PAIN_KEYWORDS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in pats):
            pain_points.append(pp)
    tools = []
    for tool, pats in TOOLS_KEYWORDS.items():
        if any(re.search(p, text, re.IGNORECASE) for p in pats):
            tools.append(tool)

    # Company type.
    company_type = None
    lower = text.lower()
    if re.search(r"influencer marketing", lower):
        company_type = "Influencer Marketing Agency"
    elif re.search(r"appointment-setting", lower):
        company_type = "Appointment-Setting Agency"
    elif re.search(r"cold email agency", lower):
        company_type = "Cold Email Agency"
    elif re.search(r"media buying|media agency", lower):
        company_type = "Media Buying Agency"
    elif re.search(r"outbound agency", lower):
        company_type = "Outbound Agency"
    elif re.search(r"seo agency", lower):
        company_type = "SEO Agency"
    elif re.search(r"performance marketing", lower):
        company_type = "Performance Marketing Agency"
    elif re.search(r"lead gen agency", lower):
        company_type = "Lead Gen Agency"
    elif re.search(r"\bagency\b", lower):
        company_type = "Agency"
    elif re.search(r"saas", lower):
        company_type = "SaaS"
    elif re.search(r"startup", lower):
        company_type = "Startup"
    elif re.search(r"car dealership|local business|ecom brand", lower):
        company_type = "Local/Ecom Business"

    # Pain category (primary = first matched use case).
    pain_category = use_cases[0] if use_cases else None

    # Team size from notes ("26 people", "43 people", "x-person team").
    team_match = re.search(r"(\d+)\s*(?:people|person\b|-person)", lower)
    team_size = int(team_match.group(1)) if team_match else None

    # Metrics.
    words = text.split()
    word_count = len(words)
    sentence_count = len([s for s in re.split(r"[.!?]+", text) if s.strip()])
    if word_count < 20:
        engagement = "LOW"
    elif word_count <= 50:
        engagement = "MEDIUM"
    else:
        engagement = "HIGH"

    specificity = "LOW"
    if tools or use_cases:
        specificity = "MEDIUM"
    if (tools and len(tools) >= 2) or len(use_cases) >= 2 or team_size:
        specificity = "HIGH"

    # Sentiment.
    sentiment = "NEUTRAL"
    if any(w in lower for w in NEGATIVE_WORDS):
        sentiment = "NEGATIVE"
    if any(w in lower for w in POSITIVE_WORDS) or POSITIVE_INTENT.search(lower):
        sentiment = "POSITIVE"
    if is_spam:
        sentiment = "SUSPICIOUS"

    # Quality score (heuristic).
    quality = 0.3
    if word_count >= 20:
        quality += 0.15
    if word_count >= 50:
        quality += 0.1
    if specificity == "HIGH":
        quality += 0.2
    elif specificity == "MEDIUM":
        quality += 0.1
    if "budget_approved" in signals:
        quality += 0.2
    if "timeline_urgent" in signals or "timeline_asap" in signals:
        quality += 0.1
    if is_spam or any(f in flagged_as for f in ("NOT_BUYER", "WRONG_FIT", "COMPETITOR")):
        quality = 0.0 if is_spam else min(quality, 0.2)
    quality = round(min(quality, 1.0), 2)

    indicates_buyer = (
        not is_spam
        and "NOT_BUYER" not in flagged_as
        and "WRONG_FIT" not in flagged_as
        and "COMPETITOR" not in flagged_as
        and "NOT_DECISION_MAKER" not in flagged_as
    )

    return {
        "notes": text,
        "notes_original": original,
        "notes_is_missing": False,
        "notes_length_words": word_count,
        "notes_paragraph_count": paragraph_count,
        "notes_sentence_count": sentence_count,
        "notes_engagement_level": engagement,
        "notes_sentiment": sentiment,
        "notes_specificity": specificity,
        "notes_quality_score": quality,
        "extracted_company_type": company_type,
        "extracted_pain_category": pain_category,
        "extracted_use_cases": use_cases,
        "extracted_pain_points": pain_points,
        "extracted_tools": tools,
        "extracted_team_size": team_size,
        "extracted_signals": signals,
        "flagged_as": flagged_as,
        "notes_is_suspicious": is_suspicious,
        "notes_is_spam": is_spam,
        "notes_indicates_buyer": indicates_buyer,
        "notes_flag": None,
        "notes_language": language["notes_language"],
        "notes_language_confidence": language["notes_language_confidence"],
        "notes_is_non_english": language["notes_is_non_english"],
    }
