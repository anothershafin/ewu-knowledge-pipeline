from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .common import ROOT, config, now, read_csv, record, sha, sources, write_csv


class Collector:
    def __init__(self):
        self.settings = config()["collection"]
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.settings["user_agent"]
        self.last_request = 0
        self.robots = {}

    def request(self, url):
        wait = self.settings["delay_seconds"] - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        self.last_request = time.monotonic()
        return self.session.get(url, timeout=self.settings["timeout"], allow_redirects=False)

    def allowed(self, url):
        parts = urlsplit(url)
        if parts.scheme != "https" or not (parts.hostname == "ewubd.edu" or parts.hostname.endswith(".ewubd.edu")):
            raise ValueError(f"Source outside EWU HTTPS allowlist: {url}")
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            path = ROOT / f"data/raw/robots_{parts.hostname}.txt"
            rp = RobotFileParser()
            if path.exists():
                content = path.read_text(encoding="utf-8")
            else:
                response = self.request(origin + "/robots.txt")
                if response.status_code == 404:
                    content = "User-agent: *\nDisallow:\n"
                elif response.status_code in (401, 403):
                    content = "User-agent: *\nDisallow: /\n"
                else:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise RuntimeError(f"Unresolved robots.txt response: {response.status_code}")
                    content = response.text
                    if "<html" in content.lower():
                        raise RuntimeError("robots.txt returned HTML; collection stopped for review.")
                path.write_text(content, encoding="utf-8")
            rp.parse(content.splitlines())
            self.robots[origin] = rp
        rp = self.robots[origin]
        delay = rp.crawl_delay(self.settings["user_agent"]) or rp.crawl_delay("*") or 0
        self.settings["delay_seconds"] = max(self.settings["delay_seconds"], delay)
        return rp.can_fetch(self.settings["user_agent"], url)

    def get(self, url):
        for _ in range(6):
            if not self.allowed(url):
                raise PermissionError(f"robots.txt disallows {url}")
            response = self.request(url)
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
            else:
                response.raise_for_status()
                return response
        raise RuntimeError("Too many redirects")


def run():
    previous = {r["id"]: r for r in read_csv("data/processed/manifest.csv")}
    client = Collector()
    rows = []
    for source in sources():
        sid = source["id"]
        path = ROOT / f"data/raw/{sid}.{source['type']}"
        old = previous.get(sid)
        if old and path.exists() and old["sha256"] == sha(path) and old["url"] == source["url"]:
            rows.append(old)
            print(f"{sid}: cache verified", flush=True)
            continue
        row = {"id": sid, "url": source["url"], "retrieved_at": now(), "status": "error",
               "bytes": 0, "sha256": "", "content_type": "", "final_url": "", "error": ""}
        try:
            response = client.get(source["url"])
            payload = response.content
            if not payload or (source["type"] == "pdf" and not payload.startswith(b"%PDF")):
                raise ValueError("Empty or unexpected document format")
            if source["type"] == "html" and b"<html" not in payload[:10000].lower():
                raise ValueError("Expected HTML")
            path.write_bytes(payload)
            row.update(status=response.status_code, bytes=len(payload), sha256=sha(payload),
                       content_type=response.headers.get("Content-Type", ""), final_url=response.url)
        except (requests.RequestException, ValueError, PermissionError, RuntimeError) as error:
            row["error"] = str(error)
        rows.append(row)
        print(f"{sid}: {row['status']} ({row['bytes']} bytes) {row['error']}", flush=True)
        # Preserve earlier snapshots for sources not yet visited if collection is interrupted.
        updated = {**previous, **{r["id"]: r for r in rows}}
        checkpoint = [updated[s["id"]] for s in sources() if s["id"] in updated]
        write_csv("data/processed/manifest.csv", checkpoint, row.keys())
    write_csv("data/processed/manifest.csv", rows, rows[0].keys())
    # Public manifest has no content or personal values.
    write_csv("reports/manifest.csv", rows, rows[0].keys())
    record("collect", {"sources": len(rows), "successful": sum(str(r["status"]) == "200" for r in rows),
                       "failed": [r["id"] for r in rows if str(r["status"]) != "200"]})
    if any(str(row["status"]) != "200" for row in rows):
        raise RuntimeError("Collection incomplete; inspect manifest. Successful sources remain cached.")
