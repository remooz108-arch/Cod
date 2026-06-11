"""
Cold email campaign orchestration — CLI entry point.

Usage:
  python -m outreach.campaign_runner --vertical hvac --leads 50
  python -m outreach.campaign_runner --vertical dental --leads 100 --dry-run
  python -m outreach.campaign_runner --vertical plumbing --leads 75 --location "Texas"

What it does:
  1. Pulls leads from Apollo for the chosen vertical
  2. Enriches each lead (website check, pain signal detection)
  3. Generates a personalised opener via Claude
  4. Creates (or reuses) a Smartlead campaign with a 3-step sequence
  5. Uploads qualified leads to the campaign

Env vars required:
  APOLLO_API_KEY, SMARTLEAD_API_KEY, ANTHROPIC_API_KEY,
  SENDER_NAME (your name for sign-off, e.g. "Alex")
"""

import argparse
import json
import sys
import os
from dotenv import load_dotenv

load_dotenv()

from outreach.verticals import VERTICALS, SEQUENCE_STEPS
from outreach.apollo_client import ApolloClient
from outreach.lead_enricher import enrich_lead, score_lead
from outreach.copy_gen import generate_openers_batch
from outreach.smartlead_client import SmartleadClient

MIN_SCORE = 40  # skip leads with weak pain signals


def _check_env():
    missing = [v for v in ("APOLLO_API_KEY", "SMARTLEAD_API_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(v)]
    if missing:
        print(f"[error] Missing env vars: {', '.join(missing)}")
        sys.exit(1)


def run(
    vertical_key: str,
    max_leads: int,
    location: str | None,
    dry_run: bool,
    sender_name: str,
    campaign_name: str | None,
):
    cfg = VERTICALS[vertical_key]
    print(f"\n=== Cold email campaign: {cfg['label']} ===\n")

    # ------------------------------------------------------------------ #
    # 1. Pull leads from Apollo
    # ------------------------------------------------------------------ #
    print(f"[1/5] Fetching up to {max_leads} leads from Apollo...")
    apollo = ApolloClient()
    leads = apollo.search_people_paginated(
        keywords=cfg["apollo_keywords"],
        titles=cfg["apollo_titles"],
        industries=cfg["apollo_industries"],
        locations=[location] if location else None,
        max_leads=max_leads,
    )
    print(f"      Found {len(leads)} leads with verified emails.")

    if not leads:
        print("[warn] No leads returned. Check your Apollo API key and search params.")
        sys.exit(0)

    # ------------------------------------------------------------------ #
    # 2. Enrich leads — website check + pain signal detection
    # ------------------------------------------------------------------ #
    print(f"[2/5] Enriching {len(leads)} leads (website scan)...")
    for i, lead in enumerate(leads, 1):
        enrich_lead(lead)
        if i % 10 == 0:
            print(f"      {i}/{len(leads)} enriched...")

    # Score and filter
    for lead in leads:
        lead["score"] = score_lead(lead)
    qualified = [l for l in leads if l["score"] >= MIN_SCORE]
    print(f"      {len(qualified)} leads qualify (score ≥ {MIN_SCORE}).")

    if not qualified:
        print("[warn] No leads passed the pain-signal threshold.")
        sys.exit(0)

    # ------------------------------------------------------------------ #
    # 3. Generate personalised openers via Claude
    # ------------------------------------------------------------------ #
    print(f"[3/5] Generating personalised openers for {len(qualified)} leads...")
    for lead in qualified:
        lead["vertical_label"] = cfg["label"]
        lead["offer"] = cfg["offer"]
        lead["outcome"] = cfg["outcome"]
        lead["sender_name"] = sender_name

    generate_openers_batch(qualified, cfg["label"])
    print("      Done.")

    if dry_run:
        print("\n[dry-run] Sample of first 3 leads:\n")
        for lead in qualified[:3]:
            print(json.dumps({k: lead[k] for k in ("first_name", "company_name", "email", "pain_signals", "opener", "score")}, indent=2))
        print(f"\n[dry-run] Would have uploaded {len(qualified)} leads to Smartlead. Exiting.")
        return

    # ------------------------------------------------------------------ #
    # 4. Create/reuse Smartlead campaign + sequence
    # ------------------------------------------------------------------ #
    print("[4/5] Setting up Smartlead campaign...")
    sl = SmartleadClient()
    name = campaign_name or f"AI Outreach — {cfg['label']}"
    campaign = sl.get_or_create_campaign(name)
    campaign_id = campaign["id"]
    print(f"      Campaign '{name}' (id={campaign_id})")

    # Attach all available sending accounts if campaign is new
    if campaign.get("status") == "CREATED":
        accounts = sl.list_email_accounts()
        if accounts:
            ids = [a["id"] for a in accounts]
            sl.attach_email_accounts(campaign_id, ids)
            print(f"      Attached {len(ids)} sending account(s).")
        else:
            print("[warn] No email accounts found in Smartlead. Add pre-warmed inboxes first.")

    # Build sequence with sender_name substituted
    steps = []
    for step in SEQUENCE_STEPS:
        steps.append({
            **step,
            "email_body": step["email_body"].replace("{{sender_name}}", sender_name),
        })
    sl.add_sequence(campaign_id, steps)
    print("      3-step sequence uploaded.")

    # ------------------------------------------------------------------ #
    # 5. Upload leads
    # ------------------------------------------------------------------ #
    print(f"[5/5] Uploading {len(qualified)} leads to campaign...")
    results = sl.add_leads_chunked(campaign_id, qualified)
    uploaded = sum(r.get("upload_count", 0) for r in results)
    print(f"      Upload complete. {uploaded} leads added.\n")

    print("All done. Campaign is ready — activate it in the Smartlead dashboard.")
    print(f"Campaign URL: https://app.smartlead.ai/app/campaigns/{campaign_id}/leads\n")


def main():
    parser = argparse.ArgumentParser(description="Run a cold email campaign.")
    parser.add_argument(
        "--vertical",
        choices=list(VERTICALS.keys()),
        required=True,
        help="Target vertical: hvac | plumbing | dental",
    )
    parser.add_argument(
        "--leads",
        type=int,
        default=50,
        help="Max number of leads to source (default: 50)",
    )
    parser.add_argument(
        "--location",
        default=None,
        help="Location filter for Apollo search (e.g. 'Texas', 'Chicago, Illinois')",
    )
    parser.add_argument(
        "--campaign-name",
        default=None,
        help="Custom campaign name (defaults to vertical name)",
    )
    parser.add_argument(
        "--sender-name",
        default=os.environ.get("SENDER_NAME", "Alex"),
        help="Your name for email sign-offs (or set SENDER_NAME env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and enrich leads but don't upload to Smartlead",
    )
    args = parser.parse_args()

    _check_env()
    run(
        vertical_key=args.vertical,
        max_leads=args.leads,
        location=args.location,
        dry_run=args.dry_run,
        sender_name=args.sender_name,
        campaign_name=args.campaign_name,
    )


if __name__ == "__main__":
    main()
