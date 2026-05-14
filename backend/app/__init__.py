"""Package init — runs proxy-env sanitization before any sub-module loads."""

import os


def _sanitize_no_proxy() -> None:
    # OrbStack/Docker Desktop injects IPv6 CIDRs (e.g. ``fd07:b51a:cc66:f0::/64``)
    # into NO_PROXY. httpx's env-proxy parser turns each NO_PROXY entry into an
    # ``all://<entry>`` URL pattern; a raw IPv6 host without brackets makes its
    # URL parser interpret the tail as a port, raising ``InvalidURL: Invalid
    # port: 'b51a:cc66:f0::'`` the moment any httpx client is constructed
    # (which breaks bilibili_api, OpenAI, Anthropic SDKs, etc.). Strip IPv6
    # entries from NO_PROXY so trust_env clients keep working.
    for key in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(key)
        if not raw:
            continue
        kept = [
            part
            for part in (p.strip() for p in raw.split(","))
            if part and "::" not in part
        ]
        cleaned = ",".join(kept)
        if cleaned != raw:
            os.environ[key] = cleaned


_sanitize_no_proxy()
