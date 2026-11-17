#!/usr/bin/env python3
"""DonSeTch runner adapter for WRB.
Supports both DonSeTch v5 (--json envelopes + stderr diagnostics) and v4."""

import json
import os
import re
import subprocess
import time
from base import Runner as BaseRunner

DONSETCH_PATH = os.environ.get("DONSETCH_PATH", "donsetch")
ENV = {**os.environ, "PATH": os.path.expanduser("~/.npm-global/bin:") + os.environ.get("PATH", "")}


def count_tokens(text):
    if not text:
        return 0
    return max(1, len(text) // 4)


def run_cmd(args, timeout=60):
    start = time.time()
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, env=ENV
        )
        latency = int((time.time() - start) * 1000)
        return result.stdout, result.stderr, latency, result.returncode
    except subprocess.TimeoutExpired:
        latency = int((time.time() - start) * 1000)
        return "", "timeout", latency, -1
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return "", str(e), latency, -1


def parse_fetch_output(stdout, stderr, latency, rc):
    """Parse DonSeTch fetch output across v5 (--json + stderr [fetch]) and v4."""
    stripped = (stdout or "").strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            meta = data.get("meta") or {}
            ok = bool(data.get("ok", False)) and rc == 0 and bool(meta.get("content_ok", True))
            content = data.get("content", "") if ok else ""
            escalation = meta.get("escalation") or []
            tier = (
                meta.get("tier")
                or (escalation[-1].get("stage") if escalation and isinstance(escalation[-1], dict) else None)
                or ("local" if ok else meta.get("verdict", "unknown"))
            )
            return {
                "success": ok,
                "content": content,
                "latency_ms": meta.get("ms", latency),
                "tokens": meta.get("tokens_est", count_tokens(content)),
                "tier": str(tier),
            }
        except json.JSONDecodeError:
            pass

    # Fallback for non-JSON / v4 output: check both stdout and stderr for [fetch] footer
    fetch_meta = {}
    content_lines = []
    for line in (stdout or "").split("\n"):
        if line.strip().startswith("[fetch]"):
            _parse_fetch_footer(line.strip(), fetch_meta)
        else:
            content_lines.append(line)
    for line in (stderr or "").split("\n"):
        if line.strip().startswith("[fetch]"):
            _parse_fetch_footer(line.strip(), fetch_meta)

    content = "\n".join(content_lines).strip()
    if rc != 0:
        success = False
    else:
        success = fetch_meta.get("success", len(content) > 0)
    tokens = fetch_meta.get("tokens", count_tokens(content)) if success else 0

    return {
        "success": success,
        "content": content if success else "",
        "latency_ms": latency,
        "tokens": tokens,
        "tier": fetch_meta.get("tier", "unknown"),
    }


def _parse_fetch_footer(meta_line, fetch_meta):
    if re.search(r"\bok\b", meta_line):
        fetch_meta["success"] = True
    elif "error" in meta_line.lower() or "wall" in meta_line.lower():
        fetch_meta["success"] = False
    tier_match = re.search(r"(?:tier\s+|fetch:\s*)([^\s\u00b7]+)", meta_line)
    if tier_match:
        fetch_meta["tier"] = tier_match.group(1)
    tok_match = re.search(r"~(\d+)\s*tokens", meta_line)
    if tok_match:
        fetch_meta["tokens"] = int(tok_match.group(1))


class Runner(BaseRunner):
    name = "DonSeTch"

    def fetch(self, url, max_chars=5000):
        stdout, stderr, latency, rc = run_cmd([
            DONSETCH_PATH, "fetch", url, "--max-chars", str(max_chars), "--json"
        ], timeout=45)
        return parse_fetch_output(stdout, stderr, latency, rc)

    def search(self, query, max_results=10):
        stdout, stderr, latency, rc = run_cmd([
            DONSETCH_PATH, "search", query, "--max-results", str(max_results), "--json"
        ], timeout=30)

        try:
            data = json.loads(stdout)
            meta = data.get("meta") or {}
            results = meta.get("results") or []
            elapsed = meta.get("elapsed_ms", latency)
            ok = bool(data.get("ok", True)) and rc == 0
            content = data.get("content", "")

            parsed_results = []
            for r in results[:max_results]:
                parsed_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("snippet", ""),
                })

            tokens = count_tokens(content)

            return {
                "success": ok,
                "results": parsed_results,
                "latency_ms": elapsed,
                "tokens": tokens,
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "results": [],
                "latency_ms": latency,
                "tokens": 0,
            }

    def crawl(self, seed_url, focus, max_pages=30):
        stdout, stderr, latency, rc = run_cmd([
            DONSETCH_PATH, "crawl", seed_url,
            "--topic", focus,
            "--max-pages", str(max_pages),
            "--max-chars", "100000",
            "--json"
        ], timeout=120)

        try:
            data = json.loads(stdout)
            ok = bool(data.get("ok", True)) and rc == 0
            meta = data.get("meta") or {}
            pages_meta = meta.get("pages") or []
            run_meta = meta.get("run") or {}
            if "elapsed_ms" in run_meta:
                elapsed_ms = int(run_meta["elapsed_ms"])
            elif "elapsed_s" in meta:
                elapsed_ms = int(float(meta["elapsed_s"]) * 1000)
            else:
                elapsed_ms = latency
            content = data.get("content", "")

            pages = []
            for p in pages_meta:
                pages.append({
                    "url": p.get("url", ""),
                    "title": p.get("title", ""),
                    "content": "",
                })

            tokens = count_tokens(content)

            return {
                "success": ok,
                "pages": pages,
                "latency_ms": elapsed_ms,
                "tokens": tokens,
            }
        except json.JSONDecodeError:
            return {
                "success": False,
                "pages": [],
                "latency_ms": latency,
                "tokens": 0,
            }
