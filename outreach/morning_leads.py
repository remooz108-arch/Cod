"""
Pulls fresh trades leads from Apollo every morning and sends them
to your iPhone via iMessage — name, company, phone, city, website pain.

Run manually:
  python -m outreach.morning_leads

Schedule it (runs at 8am Mon-Fri automatically):
  python -m outreach.morning_leads --install-cron
"""

import argparse
import os
import subprocess
import sys
from datetime import date
from dotenv import load_dotenv

load_dotenv()

from outreach.apollo_client import ApolloClient
from outreach.lead_enricher import enrich_lead
from outreach.verticals import VERTICALS


def send_imessage(to_number: str, message: str):
    safe = message.replace('"', "'").replace("\\", "")
    script = f'''
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "{to_number}" of targetService
    send "{safe}" to targetBuddy
end tell
'''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[warn] iMessage failed: {result.stderr.strip()}")
        print("[tip] Make sure Messages is open and signed in to iMessage.")


def format_message(leads: list[dict], vertical_label: str) -> str:
    today = date.today().strftime("%a %b %d")
    lines = [f"Cold calls — {today} ({vertical_label})", ""]

    for i, lead in enumerate(leads, 1):
        name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
        company = lead.get("company_name", "Unknown")
        phone = lead.get("phone", "") or "no phone"
        city = lead.get("city", "") or ""
        website = lead.get("website", "") or "no website"

        pain = ""
        signals = lead.get("pain_signals", [])
        if signals:
            pain = signals[0][:60]
        elif not lead.get("website_live"):
            pain = "no website"

        line = f"{i}. {name} - {company}"
        if city:
            line += f" ({city})"
        line += f"\n   {phone}"
        if pain:
            line += f"\n   {pain}"
        lines.append(line)
        lines.append("")

    return "\n".join(lines).strip()


def install_cron(vertical: str, lead_count: int, location: str | None):
    """Add a cron job that runs this script at 8am Mon-Fri."""
    script_path = os.path.abspath(__file__.replace(".pyc", ".py"))
    repo_path = os.path.dirname(os.path.dirname(script_path))
    python = sys.executable

    loc_flag = f"--location '{location}'" if location else ""
    cmd = (
        f"cd {repo_path} && {python} -m outreach.morning_leads "
        f"--vertical {vertical} --leads {lead_count} {loc_flag}"
    )
    cron_line = f"0 8 * * 1-5 {cmd}\n"

    # Read existing crontab
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    current = existing.stdout if existing.returncode == 0 else ""

    if "morning_leads" in current:
        print("[info] Cron job already exists. Remove it first with: crontab -e")
        return

    new_crontab = current + cron_line
    subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)
    print(f"Cron job installed. Will run at 8am Mon-Fri.")
    print(f"Command: {cmd}")


def run(vertical_key: str, lead_count: int, location: str | None):
    my_number = os.environ.get("MY_PHONE_NUMBER", "")
    if not my_number:
        print("[error] Set MY_PHONE_NUMBER in your .env file (e.g. +13055551234)")
        sys.exit(1)

    cfg = VERTICALS[vertical_key]
    print(f"Pulling {lead_count} leads for {cfg['label']}...")

    apollo = ApolloClient()
    leads = apollo.search_people_paginated(
        keywords=cfg["apollo_keywords"],
        titles=cfg["apollo_titles"],
        industries=cfg["apollo_industries"],
        locations=[location] if location else None,
        max_leads=lead_count,
    )

    # Only keep leads with a phone number
    leads = [l for l in leads if l.get("phone")]

    print(f"Enriching {len(leads)} leads with phone numbers...")
    for lead in leads:
        enrich_lead(lead)

    # Sort: no website first (easiest sell), then bad websites
    leads.sort(key=lambda l: l.get("web_score", 0), reverse=True)
    top = leads[:lead_count]

    if not top:
        print("No leads with phone numbers found.")
        return

    message = format_message(top, cfg["label"])
    print("\n--- Preview ---")
    print(message)
    print("---------------\n")
    send_imessage(my_number, message)
    print(f"Sent to {my_number}")


def main():
    parser = argparse.ArgumentParser(description="Morning cold call leads via iMessage")
    parser.add_argument("--vertical", choices=list(VERTICALS.keys()), default="trades")
    parser.add_argument("--leads", type=int, default=20, help="How many leads to send (default: 20)")
    parser.add_argument("--location", default=os.environ.get("TARGET_LOCATION"))
    parser.add_argument(
        "--install-cron",
        action="store_true",
        help="Install cron job to run automatically at 8am Mon-Fri",
    )
    args = parser.parse_args()

    if args.install_cron:
        install_cron(args.vertical, args.leads, args.location)
        return

    if not os.environ.get("APOLLO_API_KEY"):
        print("[error] APOLLO_API_KEY not set in .env")
        sys.exit(1)

    run(args.vertical, args.leads, args.location)


if __name__ == "__main__":
    main()
