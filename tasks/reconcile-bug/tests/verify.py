"""Verifier for reconcile-bug (v3: DENSE reward, hardened).

Independent checks, each worth a fixed share of the reward:

    check1_cli          0.15  runs with one CSV argument; usage error without one   (bug 1)
    check2_status       0.25  SUCCESS / FAILED / PENDING counted correctly          (bug 2)
    check3a_offsets     0.20  latest row per tx_id compared across UTC offsets      (bug 3)
    check3b_exact_tie   0.10  same moment -> the row later in the file wins         (bug 3)
    check3c_nanoseconds 0.20  ordering keeps sub-microsecond (ns) precision         (bug 3)
    check3d_lower_z     0.10  'z' accepted as the UTC designator                    (bug 3)

Each check feeds the script inputs that exercise only its own rule, so one
broken rule does not cost the points of another.

Hardening against reward hacking:
  * Every CSV is generated at verification time from a fresh random seed
    (random tx_ids, amounts, timestamps, offsets, row order). The expected
    answer comes from an independent reference implementation below, so
    memorised outputs are worthless.
  * Each check runs several random cases and passes only if all of them pass.
  * Duplicate-row cases are adversarial: the truly latest row is placed first
    in the file and, for offsets, has the earlier wall-clock time.
  * The candidate runs as `python3 -I -S`, from a fresh temp dir, on a randomly
    named file, and is rejected outright if it references /tests or /logs.
  * The reward file is written last, overwriting anything the candidate wrote.
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else "/app/reconcile.py"
LOGS = sys.argv[2] if len(sys.argv) > 2 else "/logs/verifier"
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else int.from_bytes(os.urandom(8), "big")
PYTHON = sys.executable
CASES_PER_CHECK = 4
rng = random.Random(SEED)

UTC = timedelta(0)
EAST = [timedelta(hours=9), timedelta(hours=5, minutes=30), timedelta(hours=3)]
WEST = [timedelta(hours=-5), timedelta(hours=-8), timedelta(hours=-3, minutes=-30)]


# ------------------------------------------------------------------ generators

def ts_text(instant, offset=UTC, designator="Z", nanos=None):
    """ISO-8601 text for a UTC instant shown in `offset`.
    For offset 0, `designator` is "Z" or "z"; any other offset is written +HH:MM."""
    local = instant.astimezone(timezone(offset)).replace(tzinfo=None)
    text = local.strftime("%Y-%m-%dT%H:%M:%S")
    if nanos is not None:
        text += f".{nanos:09d}"
    if offset == UTC:
        return text + designator
    sign = "-" if offset < UTC else "+"
    mins = abs(int(offset.total_seconds())) // 60
    return f"{text}{sign}{mins // 60:02d}:{mins % 60:02d}"


def rand_instant():
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=rng.randrange(0, 300 * 86400))


def rand_amount():
    cents = rng.randrange(1, 500000)
    text = f"{cents / 100:.2f}"
    return text + rng.choice("05") if rng.random() < 0.25 else text


def rand_status(name):
    return rng.choice([name, name.lower(), name.title(), f" {name} "])


_ids = set()


def rand_tx_id():
    while True:
        tx = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(2)) + str(rng.randrange(10**5, 10**6))
        if tx not in _ids:
            _ids.add(tx)
            return tx


def plain_rows(n, statuses=("SUCCESS", "FAILED")):
    """Unique tx_ids, uppercase Z or +HH:MM offsets, no fractions: no traps."""
    return [[rand_tx_id(), ts_text(rand_instant(), rng.choice([UTC] + EAST + WEST)),
             rand_amount(), rand_status(rng.choice(statuses))] for _ in range(n)]


def dup_pair(first_ts, first_status, second_ts, second_status):
    """Two rows for one new tx_id with the same amount, in file order."""
    tx, amount = rand_tx_id(), rand_amount()
    return [[tx, first_ts, amount, rand_status(first_status)],
            [tx, second_ts, amount, rand_status(second_status)]]


def mix(groups):
    """Shuffle groups; rows inside a group keep their order."""
    rng.shuffle(groups)
    return [row for group in groups for row in group]


def case_cli():
    return mix([[r] for r in plain_rows(rng.randrange(3, 7))])


def case_status():
    rows = plain_rows(rng.randrange(3, 7), ("SUCCESS", "FAILED", "PENDING"))
    rows += plain_rows(1, ("PENDING",)) + plain_rows(1, ("SUCCESS",))
    return mix([[r] for r in rows])


def case_offsets():
    """Truly later row (western offset) comes FIRST in the file and shows the
    earlier wall-clock time; the older row is written in an eastern offset."""
    groups = []
    for _ in range(2):
        older = rand_instant()
        newer = older + timedelta(minutes=rng.randrange(30, 240))
        win, lose = rng.sample(["SUCCESS", "FAILED"], 2)
        groups.append(dup_pair(ts_text(newer, rng.choice(WEST)), win,
                               ts_text(older, rng.choice(EAST)), lose))
    return mix(groups + [[r] for r in plain_rows(rng.randrange(1, 4))])


def case_exact_tie():
    """Identical timestamp text twice: the later row in the file must win."""
    groups = []
    for _ in range(2):
        stamp = ts_text(rand_instant(), rng.choice([UTC] + EAST))
        first, last = rng.sample(["SUCCESS", "FAILED"], 2)
        groups.append(dup_pair(stamp, first, stamp, last))
    return mix(groups + [[r] for r in plain_rows(rng.randrange(1, 4))])


def case_nanoseconds():
    """Pairs of rows in the same microsecond, both in Z, differing by a few
    nanoseconds. One pair has the later row first in the file, the other has it
    last, so truncating to microseconds fails whichever way ties are broken."""
    groups = []
    for later_first in (True, False):
        instant, micro = rand_instant(), rng.randrange(0, 10**6)
        lo, hi = sorted(rng.sample(range(1, 1000), 2))
        win, lose = rng.sample(["SUCCESS", "FAILED"], 2)
        late = (ts_text(instant, nanos=micro * 1000 + hi), win)
        early = (ts_text(instant, nanos=micro * 1000 + lo), lose)
        first, second = (late, early) if later_first else (early, late)
        groups.append(dup_pair(*first, *second))
    return mix(groups + [[r] for r in plain_rows(rng.randrange(1, 4))])


def case_lower_z():
    rows = [[rand_tx_id(), ts_text(rand_instant(), designator="z"), rand_amount(), rand_status(s)]
            for s in ["SUCCESS"] * rng.randrange(1, 3) + ["FAILED"]]
    return mix([[r] for r in rows + plain_rows(rng.randrange(1, 4))])


CHECKS = [  # (name, weight, case generator)
    ("check1_cli", 0.15, case_cli),
    ("check2_status", 0.25, case_status),
    ("check3a_offsets", 0.20, case_offsets),
    ("check3b_exact_tie", 0.10, case_exact_tie),
    ("check3c_nanoseconds", 0.20, case_nanoseconds),
    ("check3d_lower_z", 0.10, case_lower_z),
]


# ----------------------------------------------------- reference implementation

TS_PARTS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|z|[+-]\d{2}:\d{2})?")


def ref_moment(ts):
    """(UTC datetime to the second, nanoseconds), keeping full precision."""
    m = TS_PARTS.fullmatch(ts.strip())
    if not m:
        raise ValueError(ts)
    base, frac, off = m.groups()
    whole = datetime.fromisoformat(base).replace(tzinfo=timezone.utc)
    if off and off not in ("Z", "z"):
        sign = -1 if off[0] == "-" else 1
        whole -= sign * timedelta(hours=int(off[1:3]), minutes=int(off[4:6]))
    return whole, int((frac or "").ljust(9, "0"))


def reference(rows):
    latest = {}
    for idx, (tx, ts, amount, status) in enumerate(rows):
        tx, status = tx.strip(), status.strip().upper()
        try:
            moment, value = ref_moment(ts), Decimal(amount.strip())
        except Exception:
            continue
        if not tx or status not in ("SUCCESS", "FAILED", "PENDING") or not value.is_finite():
            continue
        key = (moment, idx)                        # later row wins an exact tie
        if tx not in latest or key > latest[tx][0]:
            latest[tx] = (key, value, status)
    valid = [v for _, v, s in latest.values() if s == "SUCCESS"]
    total = sum(valid, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"total_valid_amount": float(total), "valid_count": len(valid),
            "failed_count": sum(1 for _, _, s in latest.values() if s == "FAILED")}


# ---------------------------------------------------------------------- runner

def run_candidate(workdir, *args):
    return subprocess.run([PYTHON, "-I", "-S", SCRIPT, *args], cwd=workdir, capture_output=True,
                          text=True, timeout=10, env={"PATH": "/usr/bin:/bin"})


def run_case(rows):
    expected = reference(rows)
    with tempfile.TemporaryDirectory() as workdir:
        path = os.path.join(workdir, f"{rng.getrandbits(48):012x}.csv")
        with open(path, "w", newline="") as fh:
            fh.write("tx_id,timestamp,amount,status\n")
            fh.writelines(",".join(r) + "\n" for r in rows)
        proc = run_candidate(workdir, path)
    if proc.returncode != 0:
        return False, f"exit code {proc.returncode}: {proc.stderr.strip()[-300:]}"
    try:
        got = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        return False, f"stdout is not JSON: {proc.stdout[:200]!r}"
    total = got.get("total_valid_amount") if isinstance(got, dict) else None
    ok = (isinstance(got, dict) and set(got) == set(expected)
          and got["valid_count"] == expected["valid_count"]
          and got["failed_count"] == expected["failed_count"]
          and isinstance(total, (int, float)) and not isinstance(total, bool)
          and abs(float(total) - expected["total_valid_amount"]) < 0.005)
    return ok, f"got {got}, expected {expected}"


def run_check(name, make_case):
    try:
        if name == "check1_cli":
            with tempfile.TemporaryDirectory() as workdir:
                if run_candidate(workdir).returncode == 0:
                    return False, "running with no argument exited 0"
        for i in range(CASES_PER_CHECK):
            ok, detail = run_case(make_case())
            if not ok:
                return False, f"case {i + 1}: {detail}"
        return True, f"{CASES_PER_CHECK} random cases passed"
    except subprocess.TimeoutExpired:
        return False, "timed out"


def main():
    os.makedirs(LOGS, exist_ok=True)
    extra, checks = {}, {}
    try:
        source = open(SCRIPT, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        source, extra["error"] = None, f"cannot read script: {exc}"
    if source is not None and re.search(r"/(tests|logs)\b", source):
        source, extra["anti_cheat"] = None, "script references grader paths (/tests or /logs)"
    if source is not None:
        for name, weight, make_case in CHECKS:
            ok, detail = run_check(name, make_case)
            checks[name] = {"passed": ok, "weight": weight, "detail": detail}
            print(f"{'PASS' if ok else 'FAIL'} {name} (w={weight}): {detail}")
    else:
        print(f"REJECTED: {extra}")
    reward = round(sum(c["weight"] for c in checks.values() if c["passed"]), 2)
    with open(os.path.join(LOGS, "checks.json"), "w") as fh:
        json.dump({"seed": SEED, "reward": reward, "checks": checks, **extra}, fh, indent=2)
    with open(os.path.join(LOGS, "reward.txt"), "w") as fh:
        fh.write(f"{reward}\n")
    print(f"seed = {SEED}  reward = {reward}")


if __name__ == "__main__":
    main()
