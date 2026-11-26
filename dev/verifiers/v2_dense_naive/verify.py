"""Verifier for reconcile-bug (v2: DENSE reward, naive).

Same three fixed fixtures as v1, but each check earns its own weight, so a
partial fix gets partial credit. Naive on purpose: the inputs never change,
so a script that memorises the answers can game it (see solution/hack.sh).
"""
import json
import os
import subprocess
import sys

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/app/reconcile.py"
FIXTURES = sys.argv[2] if len(sys.argv) > 2 else "/tests/fixtures"
LOGS = sys.argv[3] if len(sys.argv) > 3 else "/logs/verifier"
PYTHON = sys.executable

# Weight per check: the harder the bug, the more it is worth.
WEIGHTS = {"check1_cli": 0.15, "check2_status": 0.25, "check3_dedup_tz": 0.6}

# (check name, fixture file, expected output). Each fixture isolates one bug.
CHECKS = [
    ("check1_cli", "check1_basic.csv",
     {"total_valid_amount": 36.25, "valid_count": 3, "failed_count": 1}),
    ("check2_status", "check2_status.csv",
     {"total_valid_amount": 102.41, "valid_count": 3, "failed_count": 1}),
    ("check3_dedup_tz", "check3_dedup.csv",
     {"total_valid_amount": 115.55, "valid_count": 4, "failed_count": 3}),
]


def run(*args):
    return subprocess.run([PYTHON, SCRIPT, *args], capture_output=True,
                          text=True, timeout=10)


def output_matches(proc, expected):
    if proc.returncode != 0:
        return False, f"exit code {proc.returncode}: {proc.stderr.strip()[-300:]}"
    try:
        got = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return False, f"stdout is not JSON: {proc.stdout[:200]!r}"
    if not isinstance(got, dict) or set(got) != set(expected):
        return False, f"wrong keys: {got!r}"
    ok = (got["valid_count"] == expected["valid_count"]
          and got["failed_count"] == expected["failed_count"]
          and isinstance(got["total_valid_amount"], (int, float))
          and round(float(got["total_valid_amount"]), 2) == expected["total_valid_amount"])
    return ok, f"got {got}, expected {expected}"


def main():
    os.makedirs(LOGS, exist_ok=True)
    results = {}
    for name, fixture, expected in CHECKS:
        try:
            ok, detail = output_matches(run(os.path.join(FIXTURES, fixture)), expected)
            if ok and name == "check1_cli":
                # The usage contract must still hold: no argument -> non-zero exit.
                no_arg = run()
                if no_arg.returncode == 0:
                    ok, detail = False, "running with no argument exited 0"
        except subprocess.TimeoutExpired:
            ok, detail = False, "timed out"
        results[name] = {"passed": ok, "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    reward = round(sum(WEIGHTS[n] for n, r in results.items() if r["passed"]), 2)
    with open(os.path.join(LOGS, "checks.json"), "w") as fh:
        json.dump({"reward": reward, "checks": results}, fh, indent=2)
    with open(os.path.join(LOGS, "reward.txt"), "w") as fh:
        fh.write(f"{reward}\n")
    print(f"reward = {reward}")


if __name__ == "__main__":
    main()
