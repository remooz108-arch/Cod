"""
Vertical configs for buildanewsite.com cold outreach.

Offer: professional website, $100/mo, 1-year contract, all maintenance + 3 edits/mo.
"""

VERTICALS = {
    "hvac": {
        "label": "HVAC / Heating & Cooling",
        "apollo_titles": ["Owner", "Co-Owner", "President", "CEO", "General Manager"],
        "apollo_keywords": ["HVAC", "heating and cooling", "air conditioning", "furnace repair", "heat pump"],
        "apollo_industries": ["construction", "facilities services"],
    },
    "plumbing": {
        "label": "Plumbing",
        "apollo_titles": ["Owner", "Co-Owner", "President", "CEO", "General Manager", "Master Plumber"],
        "apollo_keywords": ["plumbing", "plumber", "pipe repair", "drain cleaning", "water heater"],
        "apollo_industries": ["construction", "facilities services"],
    },
    "dental": {
        "label": "Dental Practice",
        "apollo_titles": ["Owner", "Dentist", "Practice Owner", "Office Manager", "DDS", "DMD"],
        "apollo_keywords": ["dental practice", "dentist", "orthodontist", "family dentistry", "cosmetic dentistry"],
        "apollo_industries": ["hospital & health care", "health, wellness and fitness"],
    },
    "trades": {
        "label": "Trades & Home Services",
        "apollo_titles": ["Owner", "Co-Owner", "President", "CEO", "General Manager"],
        "apollo_keywords": [
            "electrician", "roofing", "landscaping", "painting contractor",
            "general contractor", "flooring", "remodeling", "pest control",
            "cleaning service", "lawn care", "pool service",
        ],
        "apollo_industries": ["construction", "facilities services", "consumer services"],
    },
    "small_business": {
        "label": "Small Business",
        "apollo_titles": ["Owner", "Co-Owner", "Founder", "President", "CEO", "Managing Director", "General Manager"],
        "apollo_keywords": ["local business", "small business", "family owned", "independent"],
        "apollo_industries": [
            "retail", "consumer services", "food & beverages", "restaurants",
            "automotive", "real estate", "accounting", "construction", "facilities services",
        ],
    },
}

# Smartlead variable placeholders: {{first_name}}, {{company_name}}, {{opener}}, {{vertical_label}}
SEQUENCE_STEPS = [
    {
        "seq_number": 1,
        "seq_delay_details": {"delay_in_days": 0},
        "subject": "quick question about {{company_name}}",
        "email_body": (
            "Hi {{first_name}},\n\n"
            "{{opener}}\n\n"
            "We build and fully maintain websites for {{vertical_label}} businesses — "
            "$100/mo, includes hosting, all maintenance, and 3 edits a month. "
            "Most clients are live within a week.\n\n"
            "Worth a quick 15-minute call?\n\n"
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
            "Just bumping this in case it got buried — "
            "$100/mo, we handle everything, you get 3 edits a month whenever you need changes.\n\n"
            "Does this week work for a quick call?\n\n"
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
            "Last nudge — if the timing isn't right, no worries at all.\n\n"
            "If you ever want to see what we've built for other {{vertical_label}} businesses, "
            "just reply and I'll send some examples over.\n\n"
            "{{sender_name}}\n"
            "buildanewsite.com"
        ),
    },
]
