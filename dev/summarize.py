"""Print per-trial reward and per-check results for one or more Harbor job dirs."""
import json
import sys
from pathlib import Path


def trials(job_dir):
    for trial in sorted(p for p in Path(job_dir).iterdir() if p.is_dir()):
        result = trial / "result.json"
        if not result.is_file():
            continue
        data = json.loads(result.read_text())
        vr = data.get("verifier_result") or {}
        rewards = vr.get("rewards") or {}
        checks_file = trial / "verifier" / "checks.json"
        checks = {}
        if checks_file.is_file():
            checks = {k: v["passed"] for k, v in json.loads(checks_file.read_text()).get("checks", {}).items()}
        exc = (data.get("exception_info") or {}).get("exception_type")
        yield trial.name, rewards.get("reward"), checks, exc


for job in sys.argv[1:]:
    print(f"== {job}")
    rows = list(trials(job))
    for name, reward, checks, exc in rows:
        marks = " ".join(f"{k.split('_')[0]}={'Y' if v else 'n'}" for k, v in checks.items())
        print(f"  {name:32s} reward={reward}  {marks}  {('EXC ' + exc) if exc else ''}")
    vals = [r for _, r, _, _ in rows if r is not None]
    if vals:
        mean = sum(vals) / len(vals)
        print(f"  mean={mean:.3f}  advantages={[round(v - mean, 3) for v in vals]}")
