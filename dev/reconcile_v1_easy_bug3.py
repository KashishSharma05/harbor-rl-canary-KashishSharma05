#!/usr/bin/env python3
"""Reconcile a CSV of payment transactions into a JSON summary."""
import csv
import json
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

FIELDS = ["tx_id", "timestamp", "amount", "status"]
KNOWN_STATUSES = {"SUCCESS", "FAILED", "PENDING"}
VALID_STATUSES = {"SUCCESS", "PENDING"}
FAILED_STATUSES = {"FAILED"}


def usage():
    print("usage: reconcile.py <transactions.csv>", file=sys.stderr)
    sys.exit(2)


def parse_timestamp(raw):
    """Parse an ISO-8601 timestamp into a comparable datetime."""
    raw = raw.strip()
    if raw.endswith("Z"):
        raw = raw[:-1]
    return datetime.fromisoformat(raw).replace(tzinfo=None)


def parse_row(row):
    """Return a normalized record dict, or None if the row is malformed."""
    if len(row) != len(FIELDS):
        return None
    tx_id, raw_ts, raw_amount, raw_status = (cell.strip() for cell in row)
    status = raw_status.upper()
    if not tx_id or status not in KNOWN_STATUSES:
        return None
    try:
        ts = parse_timestamp(raw_ts)
        amount = Decimal(raw_amount)
    except (ValueError, InvalidOperation):
        return None
    if not amount.is_finite():
        return None
    return {"tx_id": tx_id, "ts": ts, "amount": amount, "status": status}


def load_latest(path):
    """Keep only the most recent row per tx_id (later row wins on a tie)."""
    latest = {}
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None or [h.strip().lower() for h in header] != FIELDS:
            sys.exit("error: unexpected CSV header")
        for row in reader:
            record = parse_row(row)
            if record is None:
                continue
            previous = latest.get(record["tx_id"])
            if previous is None or record["ts"] >= previous["ts"]:
                latest[record["tx_id"]] = record
    return list(latest.values())


def summarize(records):
    valid = [r for r in records if r["status"] in VALID_STATUSES]
    failed = [r for r in records if r["status"] in FAILED_STATUSES]
    total = sum((r["amount"] for r in valid), Decimal("0"))
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "total_valid_amount": float(total),
        "valid_count": len(valid),
        "failed_count": len(failed),
    }


def main(argv):
    if len(argv) < 3:
        usage()
    print(json.dumps(summarize(load_latest(argv[1]))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
