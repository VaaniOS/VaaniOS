"""
Linguistic vocabulary for English / romanised-Hindi (Hinglish) instructions.

This is language knowledge, not business data: it contains no customer
names, SKUs, prices or catalogue entries. Product *category* nouns
("cement", "rods") let the compiler find where a product phrase ends; the
brand/variant in front of them is kept verbatim and resolved downstream.
"""

from vaaniflow.semantic.text import phrases

# Canonical unit for each spoken unit form.
UNITS: dict[str, str] = {
    **dict.fromkeys(("bag", "bags", "bori", "boriyan", "bora", "katta", "katte"), "bag"),
    **dict.fromkeys(("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"), "kg"),
    **dict.fromkeys(("gram", "grams"), "g"),
    **dict.fromkeys(("ton", "tons", "tonne", "tonnes"), "tonne"),
    **dict.fromkeys(("quintal", "quintals"), "quintal"),
    **dict.fromkeys(("piece", "pieces", "pc", "pcs", "nos"), "piece"),
    **dict.fromkeys(("unit", "units"), "unit"),
    **dict.fromkeys(("litre", "litres", "liter", "liters"), "litre"),
    **dict.fromkeys(("metre", "metres", "meter", "meters"), "metre"),
    **dict.fromkeys(("feet", "ft"), "foot"),
    **dict.fromkeys(("box", "boxes"), "box"),
    **dict.fromkeys(("bundle", "bundles"), "bundle"),
}

CURRENCY_PREFIXES = frozenset({"₹", "rs", "inr"})
CURRENCY_SUFFIXES = frozenset({"rupees", "rupee", "rupaye", "rupaiye", "rupay", "rs", "inr", "/-"})
PER_WORDS = frozenset({"per", "each", "prati", "/"})
PRICE_CUES = frozenset({"rate", "price", "cost", "@", "bhav", "daam"})
PRICE_CUE_FILLERS = frozenset({"is", "of", "ka", "ki", "hai", ":", "=", "will", "be", "should"})

# Product category head nouns. A product phrase ends at the last head noun.
PRODUCT_HEADS = frozenset(
    {
        "cement",
        "steel",
        "rod",
        "rods",
        "bar",
        "bars",
        "tmt",
        "sariya",
        "saria",
        "sand",
        "bajri",
        "gitti",
        "gravel",
        "aggregate",
        "brick",
        "bricks",
        "eent",
        "block",
        "blocks",
        "tile",
        "tiles",
        "pipe",
        "pipes",
        "sheet",
        "sheets",
        "wire",
        "paint",
        "putty",
        "concrete",
        "plywood",
        "beam",
        "beams",
        "mesh",
        "nails",
    }
)

BUSINESS_SUFFIXES = frozenset(
    {
        "builders",
        "buildtech",
        "buildcon",
        "constructions",
        "construction",
        "traders",
        "trading",
        "infra",
        "infrastructure",
        "works",
        "enterprises",
        "industries",
        "associates",
        "developers",
        "contractors",
        "corporation",
        "company",
        "pvt",
        "ltd",
        "hardware",
        "stores",
        "suppliers",
        "agencies",
        "projects",
        "realty",
        "estates",
        "sons",
    }
)

# Tokens that can never be part of a customer or product name.
NAME_STOPWORDS = frozenset(
    {
        # action verbs / auxiliaries
        "dispatch", "send", "sent", "bhej", "bhejo", "bhejna", "bhejdo", "bhijwa", "bhijwao",
        "ship", "deliver", "delivery", "karo", "kar", "karna", "kardo", "karke", "kare",
        "karein", "karne", "do", "dena", "de", "dijiye", "lagana", "lagao", "laga", "banao",
        "bana", "banake", "create", "make", "prepare", "generate", "cancel", "update",
        "change", "modify", "check", "approve", "approval", "use", "apply", "give",
        "please", "pls", "bolo", "batao", "bata", "bataya", "bola", "tha", "thi", "hai",
        # documents / commercial nouns
        "invoice", "bill", "billing", "rate", "price", "cost", "quote", "quotation", "order",
        "gst", "plus", "including", "stock", "inventory", "whatsapp", "message", "sms",
        # function words
        "and", "aur", "then", "phir", "to", "for", "of", "ko", "ka", "ki", "ke", "se", "me",
        "mein", "pe", "par", "at", "on", "by", "from", "the", "a", "an", "is", "are", "was",
        "jo", "wahi", "same", "usual", "with", "as", "it", "them", "that", "this", "those",
        "mujhe", "mera", "hum", "main", "aap", "unko", "isko", "usko", "liye", "wala", "wali",
        # interjections / politeness / greetings
        "arre", "arey", "hey", "oye", "suno", "haan", "ok", "okay", "achha", "bhai",
        "ji", "sir", "hello", "hi", "namaste", "namaskar", "good", "morning", "thanks",
        "thank", "dear", "yes", "you",
        # correction markers
        "actually", "sorry", "no", "nahi", "nahin", "matlab", "rather", "wait",
        # urgency
        "turant", "jaldi", "urgent", "urgently", "immediately", "asap", "now", "abhi",
        "fauran", "emergency",
        # existence / question words
        "what", "how", "kya", "kitna", "kitne", "much", "many", "everything", "all", "sab",
    }
)  # fmt: skip

INTERJECTIONS = frozenset({"arre", "are", "arey", "hey", "oye", "suno", "haan", "ok", "okay"})

URGENCY_HIGH = phrases(
    [
        "urgent",
        "urgently",
        "immediately",
        "asap",
        "right away",
        "right now",
        "turant",
        "jaldi",
        "abhi ke abhi",
        "fauran",
    ]
)
URGENCY_CRITICAL = phrases(["emergency", "critical"])

TAX_EXCLUSIVE = phrases(
    [
        "plus gst",
        "+ gst",
        "gst extra",
        "gst alag",
        "gst additional",
        "excluding gst",
        "exclusive of gst",
        "gst exclusive",
        "gst lagake",
    ]
)
TAX_INCLUSIVE = phrases(
    ["including gst", "inclusive of gst", "gst included", "gst inclusive", "with gst included"]
)
TAX_BARE = phrases(["gst"])

# Correction markers. Standalone "no"/"nahi" are handled separately because
# they are only markers when followed by punctuation.
CORRECTION_MARKERS = phrases(
    [
        "actually",
        "sorry",
        "i mean",
        "make that",
        "make it",
        "change that to",
        "change it to",
        "rather",
        "no wait",
        "no no",
        "nahi nahi",
        "nahin nahin",
        "matlab",
        "mera matlab",
    ]
)
SOFT_NEGATION_MARKERS = frozenset({"no", "nahi", "nahin", "galat"})

# Tense cues used to orient bidirectional Hindi day words ("kal", "parso").
PAST_TENSE_CUES = frozenset(
    {
        "tha", "thi", "bataya", "batayi", "bola", "boli", "kaha", "diya", "liya", "kiya",
        "gaya", "gayi", "mila", "was", "were", "said", "told", "quoted", "discussed", "gave",
        "agreed", "ago", "pehle",
    }
)  # fmt: skip
FUTURE_TENSE_CUES = frozenset(
    {
        "karo", "karna", "kardo", "karenge", "karega", "karegi", "kardena", "dena", "dijiye",
        "bhejo", "bhejna", "bhejdo", "bhejenge", "lagana", "lagao", "will", "shall",
        "aayega", "aayegi", "chahiye",
    }
)  # fmt: skip
WEAK_FUTURE_CUES = frozenset({"dispatch", "deliver", "send", "ship", "please"})
