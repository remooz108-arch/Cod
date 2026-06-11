"""
Smartlead API wrapper — campaign creation, sequence setup, and lead upload.

Base URL: https://server.smartlead.ai/api/v1
Auth: ?api_key=<key> query param on every request.

Docs: https://api.smartlead.ai/reference
"""

import os
import time
import requests
from typing import Optional

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"


class SmartleadClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ["SMARTLEAD_API_KEY"]
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _url(self, path: str) -> str:
        return f"{SMARTLEAD_BASE}/{path.lstrip('/')}?api_key={self.api_key}"

    # ------------------------------------------------------------------ #
    # Campaigns
    # ------------------------------------------------------------------ #

    def create_campaign(self, name: str, timezone: str = "America/New_York") -> dict:
        """Create a new campaign and return the full response dict."""
        payload = {
            "name": name,
            "client_id": None,
            "start_date": None,
            "end_date": None,
            "track_settings": ["DONT_TRACK_EMAIL_OPEN", "DONT_TRACK_LINK_CLICK"],
            "scheduler_cron_value": {
                "timezone": timezone,
                "days_of_the_week": [1, 2, 3, 4, 5],  # Mon–Fri
                "start_hour": "08:00",
                "end_hour": "18:00",
                "min_time_btw_emails": 5,
                "max_new_leads_per_day": 40,
            },
            "stop_lead_settings": "REPLY_TO_AN_EMAIL",
        }
        resp = self.session.post(self._url("campaigns/create"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def list_campaigns(self) -> list[dict]:
        resp = self.session.get(self._url("campaigns/"))
        resp.raise_for_status()
        return resp.json()

    def get_or_create_campaign(self, name: str) -> dict:
        """Return existing campaign by name, or create it."""
        for c in self.list_campaigns():
            if c.get("name") == name:
                return c
        return self.create_campaign(name)

    # ------------------------------------------------------------------ #
    # Email accounts
    # ------------------------------------------------------------------ #

    def list_email_accounts(self) -> list[dict]:
        resp = self.session.get(self._url("email-accounts/"))
        resp.raise_for_status()
        return resp.json()

    def attach_email_accounts(self, campaign_id: int, account_ids: list[int]) -> dict:
        """Attach pre-warmed sending mailboxes to a campaign."""
        payload = {"email_account_ids": account_ids}
        resp = self.session.post(
            self._url(f"campaigns/{campaign_id}/email-accounts"),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Sequences
    # ------------------------------------------------------------------ #

    def add_sequence(self, campaign_id: int, steps: list[dict]) -> dict:
        """
        Upload a multi-step email sequence to a campaign.

        Each step in `steps` should have:
          seq_number, seq_delay_details ({"delay_in_days": N}),
          subject, email_body
        """
        payload = {"sequences": steps}
        resp = self.session.post(
            self._url(f"campaigns/{campaign_id}/sequence"),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Leads
    # ------------------------------------------------------------------ #

    def add_leads(
        self,
        campaign_id: int,
        leads: list[dict],
        ignore_block_list: bool = False,
    ) -> dict:
        """
        Upload leads to a campaign.

        Each lead dict should contain at minimum:
          email, first_name, last_name
        Optional fields: company_name, website, phone_number, custom_fields (dict)
        """
        lead_list = []
        for lead in leads:
            entry = {
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "email": lead["email"],
                "company_name": lead.get("company_name", ""),
                "website": lead.get("website", ""),
                "phone_number": lead.get("phone", ""),
                "custom_fields": {
                    "opener": lead.get("opener", ""),
                    "pain_signal": (lead.get("pain_signals") or [""])[0],
                    "vertical_label": lead.get("vertical_label", ""),
                    "offer": lead.get("offer", ""),
                    "outcome": lead.get("outcome", ""),
                },
            }
            lead_list.append(entry)

        payload = {
            "lead_list": lead_list,
            "settings": {
                "ignore_global_block_list": ignore_block_list,
                "ignore_unsubscribe_list": False,
                "ignore_communication_limit": False,
                "skip_if_in_open_campaign": True,
                "skip_if_lead_was_contacted_recently_in_days": 90,
            },
        }
        resp = self.session.post(
            self._url(f"campaigns/{campaign_id}/leads"),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def add_leads_chunked(
        self, campaign_id: int, leads: list[dict], chunk_size: int = 50
    ) -> list[dict]:
        """Upload leads in chunks to stay within API limits."""
        results = []
        for i in range(0, len(leads), chunk_size):
            chunk = leads[i : i + chunk_size]
            result = self.add_leads(campaign_id, chunk)
            results.append(result)
            time.sleep(0.5)
        return results
