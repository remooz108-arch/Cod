"""
Per-vertical configuration: Apollo search params, pain signals, and email angles.

Two services on offer:
  1. Web design — buildanewsite.com, $100/mo, 1-year contract, maintenance + 3 edits
  2. AI workflow consulting — set up automations, lead capture, follow-up, scheduling

The email leads with whichever pain signal is stronger for a given lead.
"""

# Shared offer lines — injected into email copy
OFFER_WEB = (
    "a professionally built, fully maintained website for $100/mo — "
    "includes hosting, unlimited updates, and 3 design edits a month (buildanewsite.com)"
)

OFFER_AI = (
    "simple AI workflow setup — automating the repetitive stuff like "
    "lead follow-up, appointment reminders, and quote requests — one-time or retainer"
)

OFFER_BUNDLE = (
    "a maintained website plus AI workflow setup to automate the day-to-day admin, "
    "all for $100/mo"
)

OUTCOME_WEB = (
    "most clients get a live, mobile-ready site within a week and start winning "
    "jobs they were losing to competitors with a better online presence"
)

OUTCOME_AI = (
    "most clients save 5-10 hours a week within the first month just by automating "
    "lead intake and follow-up"
)

VERTICALS = {
    "hvac": {
        "label": "HVAC / Heating & Cooling",
        "apollo_titles": [
            "Owner", "Co-Owner", "President", "CEO", "General Manager", "Operations Manager"
        ],
        "apollo_keywords": [
            "HVAC", "heating and cooling", "air conditioning", "furnace repair",
            "AC repair", "heat pump",
        ],
        "apollo_industries": ["construction", "facilities services"],
    },
    "plumbing": {
        "label": "Plumbing",
        "apollo_titles": [
            "Owner", "Co-Owner", "President", "CEO", "General Manager", "Master Plumber"
        ],
        "apollo_keywords": [
            "plumbing", "plumber", "pipe repair", "drain cleaning", "water heater",
        ],
        "apollo_industries": ["construction", "facilities services"],
    },
    "dental": {
        "label": "Dental Practice",
        "apollo_titles": [
            "Owner", "Dentist", "Practice Owner", "Office Manager", "Practice Manager",
            "DDS", "DMD",
        ],
        "apollo_keywords": [
            "dental practice", "dentist", "orthodontist", "dental office",
            "family dentistry", "cosmetic dentistry",
        ],
        "apollo_industries": ["hospital & health care", "health, wellness and fitness"],
    },
    "small_business": {
        "label": "Small Business",
        "apollo_titles": [
            "Owner", "Co-Owner", "Founder", "President", "CEO", "Managing Director",
            "General Manager", "Principal",
        ],
        "apollo_keywords": [
            "local business", "small business", "family owned", "independent",
        ],
        "apollo_industries": [
            "retail", "consumer services", "food & beverages", "restaurants",
            "automotive", "real estate", "accounting", "legal services",
            "health, wellness and fitness", "construction", "facilities services",
        ],
    },
    "trades": {
        "label": "Trades & Home Services",
        "apollo_titles": [
            "Owner", "Co-Owner", "President", "CEO", "General Manager",
        ],
        "apollo_keywords": [
            "electrician", "roofing", "landscaping", "painting contractor",
            "general contractor", "flooring", "remodeling", "pest control",
            "cleaning service", "lawn care", "pool service",
        ],
        "apollo_industries": ["construction", "facilities services", "consumer services"],
    },
}


# ── Email sequence ─────────────────────────────────────────────────────────────
# Custom Smartlead variables populated per lead:
#   {{opener}}         — Claude-generated personalised first line
#   {{primary_offer}}  — web or AI offer depending on strongest pain
#   {{primary_outcome}}
#   {{vertical_label}}
#   {{sender_name}}

SEQUENCE_STEPS = [
    {
        "seq_number": 1,
        "seq_delay_details": {"delay_in_days": 0},
        "subject": "quick question about {{company_name}}",
        "email_body": (
            "Hi {{first_name}},\n\n"
            "{{opener}}\n\n"
            "We help small businesses with two things: {{primary_offer}}.\n\n"
            "{{primary_outcome}}. No tech headaches on your end.\n\n"
            "Worth a quick 15-minute call to see if it's a fit?\n\n"
            "{{sender_name}}\n"
            "buildanewsite.com"
        ),
    },
    {
        "seq_number": 2,
        "seq_delay_details": {"delay_in_days": 3},
        "subject": "Re: quick question about {{company_name}}",
        "email_body": (
            "Hi {{first_name}},\n\n"
            "Just bumping this in case it got buried.\n\n"
            "Short version: {{primary_offer}}, and {{primary_outcome}}.\n\n"
            "Happy to walk you through it in 15 minutes — does this week work?\n\n"
            "{{sender_name}}\n"
            "buildanewsite.com"
        ),
    },
    {
        "seq_number": 3,
        "seq_delay_details": {"delay_in_days": 7},
        "subject": "Re: quick question about {{company_name}}",
        "email_body": (
            "Hi {{first_name}},\n\n"
            "Last nudge — if the timing isn't right, totally understand.\n\n"
            "If things change and you want to see what other {{vertical_label}} owners "
            "are doing with their online presence and back-office workflows, just reply "
            "and I'll send over a few examples.\n\n"
            "{{sender_name}}\n"
            "buildanewsite.com"
        ),
    },
]
