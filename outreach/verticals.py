"""
Per-vertical configuration: Apollo search params, pain signals, and email angles.
"""

VERTICALS = {
    "hvac": {
        "label": "HVAC / Heating & Cooling",
        "apollo_titles": [
            "Owner", "Co-Owner", "President", "CEO", "General Manager", "Operations Manager"
        ],
        "apollo_keywords": [
            "HVAC", "heating and cooling", "air conditioning", "furnace repair",
            "AC repair", "heat pump"
        ],
        "apollo_industries": ["construction", "facilities services"],
        "pain_signals": {
            "no_booking": "no online booking or scheduling system on their website",
            "phone_only": "phone-only intake — every job request goes to voicemail",
            "no_reviews": "no Google review response strategy",
        },
        "offer": (
            "an AI tool that handles after-hours booking, auto-responds to review requests, "
            "and follows up on estimates — for $100/mo flat"
        ),
        "outcome": "clients typically recapture 3-5 after-hours jobs per week that would have gone to a competitor",
    },
    "plumbing": {
        "label": "Plumbing",
        "apollo_titles": [
            "Owner", "Co-Owner", "President", "CEO", "General Manager", "Master Plumber"
        ],
        "apollo_keywords": [
            "plumbing", "plumber", "pipe repair", "drain cleaning", "water heater"
        ],
        "apollo_industries": ["construction", "facilities services"],
        "pain_signals": {
            "no_booking": "no online booking — customers can't self-schedule a service call",
            "phone_only": "misses leads when the truck is on a job and nobody answers",
            "no_estimates": "no automated estimate follow-up system",
        },
        "offer": (
            "an AI assistant that captures and qualifies leads 24/7, books jobs, "
            "and follows up on open quotes — for $100/mo flat"
        ),
        "outcome": "most plumbing shops recover 4-6 missed calls per week just in the first month",
    },
    "dental": {
        "label": "Dental Practice",
        "apollo_titles": [
            "Owner", "Dentist", "Practice Owner", "Office Manager", "Practice Manager",
            "Dental Director", "DDS", "DMD"
        ],
        "apollo_keywords": [
            "dental practice", "dentist", "orthodontist", "dental office",
            "family dentistry", "cosmetic dentistry"
        ],
        "apollo_industries": ["hospital & health care", "health, wellness and fitness"],
        "pain_signals": {
            "no_booking": "no self-serve patient scheduling — front desk handles every appointment manually",
            "no_reminders": "no automated appointment reminder or recall system",
            "no_reviews": "not actively collecting Google reviews after visits",
        },
        "offer": (
            "an AI front-desk layer that handles self-serve booking, sends appointment reminders, "
            "and auto-requests reviews — for $100/mo flat"
        ),
        "outcome": "practices typically cut no-show rates by 30-40% and add 8-12 new reviews per month",
    },
}

# Email sequence templates — Smartlead variable syntax: {{variable_name}}
# Custom lead fields we populate: {{opener}}, {{pain_signal}}, {{offer}}, {{outcome}}

SEQUENCE_STEPS = [
    {
        "seq_number": 1,
        "seq_delay_details": {"delay_in_days": 0},
        "subject": "quick question about {{company_name}}",
        "email_body": (
            "Hi {{first_name}},\n\n"
            "{{opener}}\n\n"
            "We built {{offer}}.\n\n"
            "{{outcome}}. No contracts, cancel any time.\n\n"
            "Worth a 15-minute call this week?\n\n"
            "{{sender_name}}"
        ),
    },
    {
        "seq_number": 2,
        "seq_delay_details": {"delay_in_days": 3},
        "subject": "Re: quick question about {{company_name}}",
        "email_body": (
            "Hi {{first_name}},\n\n"
            "Just wanted to bump this in case it got buried.\n\n"
            "The short version: {{offer}}, and {{outcome}}.\n\n"
            "Happy to show you exactly how it works in 15 minutes. Does this week work?\n\n"
            "{{sender_name}}"
        ),
    },
    {
        "seq_number": 3,
        "seq_delay_details": {"delay_in_days": 7},
        "subject": "Re: quick question about {{company_name}}",
        "email_body": (
            "Hi {{first_name}},\n\n"
            "Last nudge — if the timing isn't right, totally understand.\n\n"
            "If things change and you want to see how other {{vertical_label}} owners "
            "are using this, just reply and I'll send over a quick demo.\n\n"
            "{{sender_name}}"
        ),
    },
]
