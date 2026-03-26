"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/geo_context.py

Adds geolocation context to session and alert documents.
Uses the geopy library with IP-based lookup as a fallback.

Note: IP-based geolocation is approximate (city-level only).
      For office use, a fixed known-location whitelist is recommended.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_ip_address() -> str:
    """Return the public IP address of the current machine."""
    try:
        import requests
        resp = requests.get("https://api.ipify.org", timeout=5)
        return resp.text.strip()
    except Exception as exc:
        logger.debug("Could not fetch public IP: %s", exc)
        return "unknown"


def get_geo_context(ip: Optional[str] = None) -> dict:
    """
    Return approximate geolocation for *ip* (or current public IP).

    Returns
    -------
    dict
        Keys: ip, country, city, lat, lon  (all str/float or None)
    """
    ip = ip or get_ip_address()
    result = {"ip": ip, "country": None, "city": None, "lat": None, "lon": None}

    try:
        from geopy.geocoders import Nominatim
        import requests

        # Use ip-api for a quick city-level lookup (no API key required)
        resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
        data = resp.json()
        if data.get("status") == "success":
            result.update({
                "country": data.get("country"),
                "city": data.get("city"),
                "lat": data.get("lat"),
                "lon": data.get("lon"),
            })
    except Exception as exc:
        logger.debug("Geolocation lookup failed: %s", exc)

    return result
