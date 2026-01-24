#!/usr/bin/env python3
"""Upload fiscal information per-SKU to MercadoLibre.

Reads JSON files from a directory (default: items_by_sku/) produced by
`scripts/export_livros_info.py`. For each payload it checks existence via
GET /items/fiscal_information/{SKU} and POSTs missing payloads to
POST /items/fiscal_information.

Supports: --dry-run, --verbose, --dir, --concurrency, --max-retries
"""
import argparse
import glob
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from auth import TokenManager
from ml_api import MLAPI
from error_collector import ErrorCollector


logger = logging.getLogger(__name__)


def load_files(directory):
    files = sorted(glob.glob(os.path.join(directory, "*.json")))
    return files


def load_payloads_from_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return [data]


def process_payload(api, payload, dry_run=False, max_retries=3, backoff_base=1, verbose=False):
    sku = payload.get("sku")
    if not sku:
        return False, "missing sku"

    if dry_run:
        if verbose:
            print(f"[DRY-RUN] Would check SKU: {sku}")
            print(json.dumps(payload, ensure_ascii=False))
        return True, "dry-run"

    # 1) Check existence
    try:
        api.request("GET", f"/items/fiscal_information/{sku}")
        # exists
        if verbose:
            print(f"[SKIP] Fiscal information already exists for {sku}")
        return True, "exists"
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        code = resp.status_code if resp is not None else None
        if code != 404:
            return False, f"GET failed: {code} {getattr(resp, 'text', '')[:200]}"
        # 404 -> proceed to POST
    except Exception as e:
        return False, f"GET error: {e}"

    # 2) POST payload with retries/backoff
    attempt = 0
    while attempt <= max_retries:
        try:
            res = api.request("POST", "/items/fiscal_information", json=payload)
            if verbose:
                print(f"[OK] Posted fiscal info for {sku}")
            return True, res
        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            code = resp.status_code if resp is not None else None
            # Retry on rate limit and server errors
            if code in (429, 500, 502, 503, 504) and attempt < max_retries:
                delay = min(60, backoff_base * (2 ** attempt))
                if verbose:
                    print(f"[RETRY] {sku} -> {code}, sleeping {delay}s (attempt {attempt+1})")
                time.sleep(delay)
                attempt += 1
                continue
            # Non-retriable
            return False, f"POST failed: {code} {getattr(resp, 'text', '')[:400]}"
        except Exception as e:
            if attempt < max_retries:
                delay = min(60, backoff_base * (2 ** attempt))
                if verbose:
                    print(f"[RETRY] {sku} -> exception {e}, sleeping {delay}s (attempt {attempt+1})")
                time.sleep(delay)
                attempt += 1
                continue
            return False, f"POST error: {e}"


def main():
    p = argparse.ArgumentParser(description="Upload fiscal information for SKUs")
    p.add_argument("--dir", default="items_by_sku", help="Directory with per-SKU JSON files")
    p.add_argument("--dry-run", action="store_true", help="Simulate actions without network calls")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--concurrency", type=int, default=1, help="Number of concurrent uploads (default: 1)")
    p.add_argument("--max-retries", type=int, default=3, help="Retries for POST on 429/5xx (default: 3)")
    args = p.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    files = load_files(args.dir)
    if not files:
        print(f"No JSON files found in {args.dir}")
        return

    # Prepare API (but avoid instantiating network calls when dry-run)
    token_manager = TokenManager()
    api = MLAPI(token_manager)

    # Collector for errors
    collector = ErrorCollector()

    payloads = []
    for path in files:
        try:
            items = load_payloads_from_file(path)
        except Exception as e:
            print(f"Failed to read {path}: {e}")
            collector.add_error({"file": path}, str(e))
            continue
        for item in items:
            payloads.append((path, item))

    total = len(payloads)
    print(f"Found {total} payload(s) across {len(files)} file(s)")

    results = []

    def _worker(tup):
        path, payload = tup
        ok, info = process_payload(api, payload, dry_run=args.dry_run, max_retries=args.max_retries, verbose=args.verbose)
        if not ok:
            collector.add_error(payload, str(info))
        return path, payload.get("sku"), ok, info

    if args.concurrency and args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futures = {ex.submit(_worker, p): p for p in payloads}
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    print(f"Worker exception: {e}")
    else:
        for p in payloads:
            results.append(_worker(p))

    success = sum(1 for r in results if r[2])
    failed = sum(1 for r in results if not r[2])

    print(f"Done: {success} succeeded, {failed} failed")

    if collector.has_errors:
        err_file = collector.save()
        if err_file:
            print(f"Errors saved to: {err_file}")


if __name__ == "__main__":
    main()
