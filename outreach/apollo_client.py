"""
Apollo.io API wrapper — people/org search for lead sourcing.

Docs: https://apolloio.github.io/apollo-api-docs/
Auth: X-Api-Key header (v1) or api_key in body (v1 mixed search).
"""

import os
import time
import requests
from typing import Optional

APOLLO_BASE = "https://api.apollo.io/v1"


class ApolloClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ["APOLLO_API_KEY"]
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key,
        })

    def search_people(
        self,
        keywords: list[str],
        titles: list[str],
        industries: list[str],
        locations: list[str] | None = None,
        per_page: int = 25,
        page: int = 1,
    ) -> list[dict]:
        """
        Search for people using mixed_people/search.
        Returns a flat list of lead dicts, each containing:
          id, first_name, last_name, email, title,
          organization.name, organization.website_url, organization.city, organization.state
        """
        payload = {
            "q_keywords": " OR ".join(keywords),
            "person_titles": titles,
            "organization_industry_tag_ids": [],
            "q_organization_keyword_tags": industries,
            "person_locations": locations or ["United States"],
            "email_status": ["verified", "guessed"],
            "per_page": per_page,
            "page": page,
        }

        resp = self.session.post(f"{APOLLO_BASE}/mixed_people/search", json=payload)
        resp.raise_for_status()
        data = resp.json()

        people = data.get("people", [])
        return [self._normalize(p) for p in people if p.get("email")]

    def search_people_paginated(
        self,
        keywords: list[str],
        titles: list[str],
        industries: list[str],
        locations: list[str] | None = None,
        max_leads: int = 100,
        per_page: int = 25,
    ) -> list[dict]:
        """Fetch up to max_leads results across multiple pages."""
        leads = []
        page = 1
        while len(leads) < max_leads:
            batch = self.search_people(
                keywords=keywords,
                titles=titles,
                industries=industries,
                locations=locations,
                per_page=per_page,
                page=page,
            )
            if not batch:
                break
            leads.extend(batch)
            page += 1
            # Respect Apollo's rate limit (600 req/min on most plans)
            time.sleep(0.2)

        return leads[:max_leads]

    @staticmethod
    def _normalize(p: dict) -> dict:
        org = p.get("organization") or {}
        return {
            "apollo_id": p.get("id", ""),
            "first_name": p.get("first_name", ""),
            "last_name": p.get("last_name", ""),
            "email": p.get("email", ""),
            "title": p.get("title", ""),
            "company_name": org.get("name", ""),
            "website": (org.get("website_url") or "").rstrip("/"),
            "city": p.get("city") or org.get("city", ""),
            "state": p.get("state") or org.get("state", ""),
            "phone": p.get("sanitized_phone", ""),
            "linkedin_url": p.get("linkedin_url", ""),
        }
