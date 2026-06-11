"""
Cold email campaign runner for buildanewsite.com.

Offer: professional website, $100/mo, 1-year contract, all maintenance + 3 edits/mo.

Usage:
  python -m outreach.campaign_runner --vertical small_business --leads 100
  python -m outreach.campaign_runner --vertical hvac --leads 50 --location "Texas" --dry-run

Env vars required: APOLLO_API_KEY, SMARTLEAD_API_KEY, ANTHROPIC_API_KEY, SENDER_NAME
"""

import argparse
import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from outreach.verticals import VERTICALS, SEQUENCE_STEPS
from outreach.apollo_client import ApolloClient
from outreach.lead_enricher import enrich_lead, score_lead
from outreach.copy_gen import generate_openers_batch
from outreach.smartlead_client import SmartleadClient

MIN_SCORE = 30


def _check_env():
    missing = [v for v in ("APOLLO_API_KEY", "SMARTLEAD_API_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(v)]
    if missing:
        print(f"[error] Missing env vars: {', '.join(missing)}")
        sys.exit(1)


def run(vertical_key, max_leads, location, dry_run, sender_name, campaign_name):
    cfg = VERTICALS[vertical_key]
    print(f"\n=== buildanewsite.com — {cfg['label']} ===\n")

    # 1. Apollo
    print(f"[1/5] Fetching up to {max_leads} leads from Apollo...")
    apollo = ApolloClient()
    leads = apollo.search_people_paginated(
        keywords=cfg["apollo_keywords"],
        titles=cfg["apollo_titles"],
        industries=cfg["apollo_industries"],
        locations=[location] if location else None,
        max_leads=max_leads,
    )
    print(f"      {len(leads)} leads with verified emails.")
    if not leads:
        print("[warn] No leads returned.")
        sys.exit(0)

    # 2. Enrich
    print(f"[2/5] Scanning websites ({len(leads)} leads)...")
    for i, lead in enumerate(leads, 1):
        enrich_lead(lead)
        if i % 10 == 0:
            print(f"      {i}/{len(leads)}...")

    for lead in leads:
        lead["score"] = score_lead(lead)
    qualified = sorted(
        [l for l in leads if l["score"] >= MIN_SCORE],
        key=lambda l: l["score"], reverse=True,
    )
    print(f"      {len(qualified)} qualify (score ≥ {MIN_SCORE}).")
    if not qualified:
        sys.exit(0)

    # 3. Openers
    print(f"[3/5] Generating openers via Claude ({len(qualified)} leads)...")
    for lead in qualified:
        lead["vertical_label"] = cfg["label"]
        lead["sender_name"] = sender_name
    generate_openers_batch(qualified, cfg["label"])
    print("      Done.")

    if dry_run:
        print("\n[dry-run] First 3 leads:\n")
        for lead in qualified[:3]:
            print(json.dumps({k: lead.get(k) for k in (
                "first_name", "company_name", "email", "city",
                "website", "pain_signals", "opener", "score",
            )}, indent=2))
        print(f"\n[dry-run] {len(qualified)} leads ready. Remove --dry-run to upload.")
        return

    # 4. Smartlead campaign
    print("[4/5] Setting up Smartlead campaign...")
    sl = SmartleadClient()
    name = campaign_name or f"buildanewsite — {cfg['label']}"
    campaign = sl.get_or_create_campaign(name)
    cid = campaign["id"]
    print(f"      '{name}' (id={cid})")

    if campaign.get("status") == "CREATED":
        accounts = sl.list_email_accounts()
        if accounts:
            sl.attach_email_accounts(cid, [a["id"] for a in accounts])
            print(f"      Attached {len(accounts)} sending account(s).")
        else:
            print("[warn] No email accounts found — add pre-warmed inboxes in Smartlead before activating.")

    steps = [
        {**s, "email_body": s["email_body"].replace("{{sender_name}}", sender_name)}
        for s in SEQUENCE_STEPS
    ]
    sl.add_sequence(cid, steps)
    print("      Sequence uploaded (day 0 / 3 / 7).")

    # 5. Upload leads
    print(f"[5/5] Uploading {len(qualified)} leads...")
    results = sl.add_leads_chunked(cid, qualified)
    uploaded = sum(r.get("upload_count", 0) for r in results)
    print(f"      {uploaded} leads added.\n")
    print(f"Activate when ready → https://app.smartlead.ai/app/campaigns/{cid}/leads\n")


def main():
    parser = argparse.ArgumentParser(description="buildanewsite.com cold email campaign")
    parser.add_argument("--vertical", choices=list(VERTICALS.keys()), required=True)
    parser.add_argument("--leads", type=int, default=50)
    parser.add_argument("--location", default=None, help="e.g. 'Texas' or 'Chicago, Illinois'")
    parser.add_argument("--campaign-name", default=None)
    parser.add_argument("--sender-name", default=os.environ.get("SENDER_NAME", "Alex"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    _check_env()
    run(args.vertical, args.leads, args.location, args.dry_run, args.sender_name, args.campaign_name)


if __name__ == "__main__":
    main()
