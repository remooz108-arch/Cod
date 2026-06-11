"""
Cold email campaign orchestration — CLI entry point.

Services:
  1. Web design  — buildanewsite.com, $100/mo, 1-year contract, maintenance + 3 edits
  2. AI workflows — automating lead follow-up, scheduling, admin

Usage:
  python -m outreach.campaign_runner --vertical small_business --leads 100
  python -m outreach.campaign_runner --vertical hvac --leads 50 --dry-run
  python -m outreach.campaign_runner --vertical trades --leads 75 --location "Texas"

Flow:
  1. Apollo  → fetch leads (owner/founder titles, target industry)
  2. Enrich  → website scan, detect web + workflow pain signals
  3. Claude  → generate personalised opener per lead
  4. Smartlead → create/reuse campaign, upload 3-step sequence, add leads

Env vars required:
  APOLLO_API_KEY, SMARTLEAD_API_KEY, ANTHROPIC_API_KEY, SENDER_NAME
"""

import argparse
import json
import sys
import os
from dotenv import load_dotenv

load_dotenv()

from outreach.verticals import (
    VERTICALS, SEQUENCE_STEPS,
    OFFER_WEB, OFFER_AI, OFFER_BUNDLE,
    OUTCOME_WEB, OUTCOME_AI,
)
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


def _pick_offer(lead: dict) -> tuple[str, str]:
    """Return (primary_offer, primary_outcome) based on detected pain."""
    pain = lead.get("primary_pain", "web")
    if pain == "both":
        return OFFER_BUNDLE, OUTCOME_WEB
    elif pain == "workflow":
        return OFFER_AI, OUTCOME_AI
    else:
        return OFFER_WEB, OUTCOME_WEB


def run(
    vertical_key: str,
    max_leads: int,
    location: str | None,
    dry_run: bool,
    sender_name: str,
    campaign_name: str | None,
):
    cfg = VERTICALS[vertical_key]
    print(f"\n=== buildanewsite.com outreach — {cfg['label']} ===\n")

    # ── 1. Fetch leads from Apollo ──────────────────────────────────────────
    print(f"[1/5] Fetching up to {max_leads} leads from Apollo...")
    apollo = ApolloClient()
    leads = apollo.search_people_paginated(
        keywords=cfg["apollo_keywords"],
        titles=cfg["apollo_titles"],
        industries=cfg["apollo_industries"],
        locations=[location] if location else None,
        max_leads=max_leads,
    )
    print(f"      Got {len(leads)} leads with verified emails.")
    if not leads:
        print("[warn] No leads returned — check your Apollo API key and plan limits.")
        sys.exit(0)

    # ── 2. Enrich — website scan + pain scoring ─────────────────────────────
    print(f"[2/5] Scanning websites for pain signals ({len(leads)} leads)...")
    for i, lead in enumerate(leads, 1):
        enrich_lead(lead)
        if i % 10 == 0:
            print(f"      {i}/{len(leads)} scanned...")

    for lead in leads:
        lead["score"] = score_lead(lead)
    qualified = sorted(
        [l for l in leads if l["score"] >= MIN_SCORE],
        key=lambda l: l["score"],
        reverse=True,
    )
    print(f"      {len(qualified)} leads qualify (score ≥ {MIN_SCORE}).")
    if not qualified:
        print("[warn] No leads passed the threshold. Try lowering MIN_SCORE or widening the search.")
        sys.exit(0)

    # Pain breakdown
    web_leads = sum(1 for l in qualified if l.get("primary_pain") == "web")
    wf_leads = sum(1 for l in qualified if l.get("primary_pain") == "workflow")
    both_leads = sum(1 for l in qualified if l.get("primary_pain") == "both")
    print(f"      Pitch split → web: {web_leads}, workflow: {wf_leads}, both: {both_leads}")

    # ── 3. Assign offers + generate openers ────────────────────────────────
    print(f"[3/5] Generating personalised openers via Claude...")
    for lead in qualified:
        offer, outcome = _pick_offer(lead)
        lead["primary_offer"] = offer
        lead["primary_outcome"] = outcome
        lead["vertical_label"] = cfg["label"]
        lead["sender_name"] = sender_name

    generate_openers_batch(qualified, cfg["label"])
    print("      Done.")

    if dry_run:
        print("\n[dry-run] Sample of first 3 leads:\n")
        for lead in qualified[:3]:
            print(json.dumps({
                k: lead.get(k)
                for k in ("first_name", "company_name", "email", "city",
                           "website", "primary_pain", "pain_signals", "opener", "score")
            }, indent=2))
        print(f"\n[dry-run] Would have uploaded {len(qualified)} leads to Smartlead. Exiting.")
        return

    # ── 4. Smartlead — create/reuse campaign + sequence ────────────────────
    print("[4/5] Setting up Smartlead campaign...")
    sl = SmartleadClient()
    name = campaign_name or f"buildanewsite — {cfg['label']}"
    campaign = sl.get_or_create_campaign(name)
    campaign_id = campaign["id"]
    print(f"      Campaign '{name}' (id={campaign_id})")

    if campaign.get("status") == "CREATED":
        accounts = sl.list_email_accounts()
        if accounts:
            sl.attach_email_accounts(campaign_id, [a["id"] for a in accounts])
            print(f"      Attached {len(accounts)} sending account(s).")
        else:
            print("[warn] No email accounts in Smartlead — add pre-warmed inboxes before activating.")

    steps = [
        {**s, "email_body": s["email_body"].replace("{{sender_name}}", sender_name)}
        for s in SEQUENCE_STEPS
    ]
    sl.add_sequence(campaign_id, steps)
    print("      3-step sequence uploaded (day 0, 3, 7).")

    # ── 5. Upload leads ─────────────────────────────────────────────────────
    print(f"[5/5] Uploading {len(qualified)} leads...")
    results = sl.add_leads_chunked(campaign_id, qualified)
    uploaded = sum(r.get("upload_count", 0) for r in results)
    print(f"      {uploaded} leads added.\n")

    print("Done. Activate the campaign in Smartlead when your inboxes are ready.")
    print(f"→ https://app.smartlead.ai/app/campaigns/{campaign_id}/leads\n")


def main():
    parser = argparse.ArgumentParser(description="Run a cold email campaign for buildanewsite.com + AI workflows.")
    parser.add_argument(
        "--vertical",
        choices=list(VERTICALS.keys()),
        required=True,
        help=f"Target vertical: {', '.join(VERTICALS.keys())}",
    )
    parser.add_argument("--leads", type=int, default=50, help="Max leads to source (default: 50)")
    parser.add_argument("--location", default=None, help="Location filter, e.g. 'Texas' or 'Chicago, Illinois'")
    parser.add_argument("--campaign-name", default=None, help="Override campaign name in Smartlead")
    parser.add_argument(
        "--sender-name",
        default=os.environ.get("SENDER_NAME", "Alex"),
        help="Your name for email sign-offs (or set SENDER_NAME env var)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch + enrich leads but don't upload to Smartlead")
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
