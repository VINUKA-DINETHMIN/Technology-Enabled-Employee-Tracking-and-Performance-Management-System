"""
R26-IT-042 — C3: Activity Monitoring
C3_activity_monitoring/src/geo_context.py

Adds geolocation context to session and alert documents.
Uses public IP intelligence providers to estimate city/region/country.

Note: IP-based geolocation is approximate (city-level only).
      For office use, a fixed known-location whitelist is recommended.
"""

from __future__ import annotations

import logging
import ipaddress
import math
from typing import Optional

logger = logging.getLogger(__name__)


def _to_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _clean_text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "none", "null", "n/a", "-"}:
        return None
    return text


def _is_public_ip(ip: Optional[str]) -> bool:
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_global
    except Exception:
        return False


def get_ip_address() -> str:
    """Return the public IP address of the current machine."""
    try:
        import requests
        for endpoint in ("https://api.ipify.org", "https://ifconfig.me/ip"):
            try:
                resp = requests.get(endpoint, timeout=5)
                ip = _clean_text(resp.text)
                if ip:
                    return ip
            except Exception:
                continue
    except Exception as exc:
        logger.debug("Could not fetch public IP: %s", exc)
        return "unknown"

    return "unknown"


def _lookup_ipwhois(ip: str, timeout: int = 5) -> dict:
    import requests

    resp = requests.get(f"https://ipwho.is/{ip}", timeout=timeout)
    data = resp.json() if resp is not None else {}
    if not data.get("success"):
        return {}
    return {
        "country": _clean_text(data.get("country")),
        "city": _clean_text(data.get("city")),
        "region": _clean_text(data.get("region")),
        "timezone": _clean_text(data.get("timezone", {}).get("id") if isinstance(data.get("timezone"), dict) else data.get("timezone")),
        "isp": _clean_text(data.get("connection", {}).get("isp") if isinstance(data.get("connection"), dict) else data.get("isp")),
        "org": _clean_text(data.get("connection", {}).get("org") if isinstance(data.get("connection"), dict) else data.get("org")),
        "asn": _clean_text(data.get("connection", {}).get("asn") if isinstance(data.get("connection"), dict) else data.get("asn")),
        "is_proxy": bool(data.get("security", {}).get("proxy") if isinstance(data.get("security"), dict) else False),
        "is_hosting": bool(data.get("security", {}).get("hosting") if isinstance(data.get("security"), dict) else False),
        "is_mobile": bool(data.get("connection", {}).get("is_mobile") if isinstance(data.get("connection"), dict) else False),
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "confidence": 0.75,
        "source": "ipwho.is",
    }


def _lookup_ipapi(ip: str, timeout: int = 5) -> dict:
    import requests

    resp = requests.get(f"https://ipapi.co/{ip}/json/", timeout=timeout)
    data = resp.json() if resp is not None else {}
    if data.get("error") is True:
        return {}
    return {
        "country": _clean_text(data.get("country_name")),
        "city": _clean_text(data.get("city")),
        "region": _clean_text(data.get("region")),
        "timezone": _clean_text(data.get("timezone")),
        "isp": _clean_text(data.get("org")),
        "org": _clean_text(data.get("org")),
        "asn": _clean_text(data.get("asn")),
        "is_proxy": False,
        "is_hosting": False,
        "is_mobile": False,
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "confidence": 0.65,
        "source": "ipapi.co",
    }


def _build_location_hint(data: dict) -> str:
    parts = [
        data.get("city"),
        data.get("region"),
        data.get("country"),
    ]
    text_parts = [p for p in parts if p]
    base = ", ".join(text_parts) if text_parts else "Unknown"
    isp = data.get("isp") or data.get("org")
    if isp:
        return f"{base} ({isp})"
    return base


def get_geo_context(ip: Optional[str] = None) -> dict:
    """
    Return approximate geolocation for *ip* (or current public IP).

    Returns
    -------
    dict
        Keys: ip, country, city, lat, lon  (all str/float or None)
    """
    ip = _clean_text(ip) or get_ip_address()
    if not _is_public_ip(ip):
        return {
            "ip": ip or "unknown",
            "country": None,
            "city": None,
            "region": None,
            "timezone": None,
            "isp": None,
            "org": None,
            "asn": None,
            "is_proxy": None,
            "is_hosting": None,
            "is_mobile": None,
            "lat": None,
            "lon": None,
            "confidence": 0.0,
            "location_hint": "Unknown",
            "source": None,
        }

    result = {
        "ip": ip,
        "country": None,
        "city": None,
        "region": None,
        "timezone": None,
        "isp": None,
        "org": None,
        "asn": None,
        "is_proxy": None,
        "is_hosting": None,
        "is_mobile": None,
        "lat": None,
        "lon": None,
        "confidence": 0.0,
        "location_hint": "Unknown",
        "source": None,
    }

    try:
        for provider in (_lookup_ipwhois, _lookup_ipapi):
            try:
                data = provider(ip)
            except Exception as exc:
                logger.debug("Geo provider failed (%s): %s", provider.__name__, exc)
                continue

            if not data:
                continue

            result.update(data)
            if result.get("city") or result.get("country"):
                break
    except Exception as exc:
        logger.debug("Geolocation lookup failed: %s", exc)

    if result.get("city") or result.get("country"):
        conf = float(result.get("confidence") or 0.0)
        if result.get("is_proxy"):
            conf *= 0.6
        if result.get("is_hosting"):
            conf *= 0.6
        result["confidence"] = round(max(0.0, min(conf, 0.95)), 2)
        result["location_hint"] = _build_location_hint(result)

    return result


def haversine_km(lat1, lon1, lat2, lon2) -> Optional[float]:
    """Return great-circle distance in KM between two coordinates."""
    a_lat = _to_float(lat1)
    a_lon = _to_float(lon1)
    b_lat = _to_float(lat2)
    b_lon = _to_float(lon2)
    if None in (a_lat, a_lon, b_lat, b_lon):
        return None

    r = 6371.0088
    d_lat = math.radians(b_lat - a_lat)
    d_lon = math.radians(b_lon - a_lon)
    x = (
        math.sin(d_lat / 2.0) ** 2
        + math.cos(math.radians(a_lat))
        * math.cos(math.radians(b_lat))
        * math.sin(d_lon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(x), math.sqrt(1.0 - x))
    return round(r * c, 3)
