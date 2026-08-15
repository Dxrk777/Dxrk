from __future__ import annotations

from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from dxrk.strconst import StrTitle


@dataclass
class Result:
    url: str
    title: str = ""
    content: str = ""
    links: list[str] = field(default_factory=list)


def scrape(url: str, timeout: float) -> Result:
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "Dxrk/1.0"},
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise RuntimeError(f"scrape {url}: {e}") from e

    soup = BeautifulSoup(resp.text, "html.parser")

    res = Result(url=url)

    title = soup.select_one(StrTitle)
    if title is not None:
        res.title = title.get_text()

    body = soup.select_one("body")
    if body is not None:
        res.content = body.get_text()

    for link in soup.select("a[href]"):
        href = link.get("href")
        if href:
            res.links.append(str(href))

    return res


def extract_domain(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url)
        if not parsed.scheme or not parsed.hostname:
            return ""
        return parsed.hostname
    except Exception:
        return ""
