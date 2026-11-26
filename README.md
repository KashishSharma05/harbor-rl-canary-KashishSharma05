# Harbor RL Submission — Kashish Sharma (@KashishSharma05)

## 1. Loom Walkthrough Video
- **Video URL:** [Watch 5-Minute Walkthrough](https://www.loom.com/share/YOUR_VIDEO_ID)
  *(Link sharing set to "Anyone with the link can view")*

## 2. Task & Calibration Summary

`tasks/reconcile-bug/` ships a broken payment-reconciliation CLI (`/app/reconcile.py`, 87 lines, stdlib only) that reads `tx_id,timestamp,amount,status` and prints `{"total_valid_amount", "valid_count", "failed_count"}`.

- **Bug 1 (Easy):** the argument check is `if len(argv) < 3`, so the script prints its usage message and exits 2 even when it is given the one CSV path it needs.
- **Bug 2 (Medium):** `VALID_STATUSES` contains `PENDING`, so pending payments are counted as valid and added to the total.
- **Bug 3 (Hard):** the "latest row per `tx_id` wins" rule is broken in four ways that only show up on real data: offsets are relabelled as UTC instead of converted (`replace(tzinfo=...)` vs `astimezone`), an exact tie keeps the first row instead of the later one, `datetime.fromisoformat` silently truncates nanosecond fractions to microseconds (so two events a few ns apart become a "tie"), and a lowercase `z` UTC designator is rejected as malformed.
- **Calibration Scores:** `nop` = `0.00` | `oracle` (`solve.sh`) = `1.00` | Partial `oracle` (Bug 1+2 fixed, Bug 3 broken) = `0.40` with Bug 3's original code put back (`jobs_summary/proof_partial_oracle_bug3_broken`), `0.50` for the one-line break shown in the video | `hack.sh` = `0.00`

**How the difficulty was calibrated.** Getting at least one baseline failure took three tries. All runs used `terminus-2` with `gemini/gemini-3.5-flash-lite`. The `gemini-2.5-flash` model named in the brief is closed to new API keys, and the larger 3.x flash models returned HTTP 503 (high demand).

| Attempt | Bug 3 at that point | Result | What the trajectories showed |
| :--- | :--- | :--- | :--- |
| `run0_calibration_too_easy` | offset dropped with `.replace(tzinfo=None)` | 3/3 pass | The line looks wrong on sight; every trial spotted it while reading the file. |
| `run0b_calibration_too_easy` | subtler code (`replace(tzinfo=utc)` + strict `>`) | 3/3 pass | Agents don't patch the file, they rewrite it from the spec, so how well the bug is hidden in the code doesn't matter. Their rewrites also scored 1.0 on the hardened random verifier. |
| `run1_baseline` | spec adds nanosecond precision + `z` designator | **0/3 pass** | Same mistake in all three trials (see §4). |

The lesson from the first two attempts: difficulty has to come from the **spec** (a rule whose obvious implementation is quietly wrong), not from how well the bug is hidden in the code.

## 3. Ablation & RL Advantage Table (`terminus-2`, `k=3` Trials)

Binary rewards come from the binary verifier these runs were graded with (`dev/verifiers/v1_binary`). Dense rewards come from re-grading the same recorded `/app/reconcile.py` artifacts with the final hardened verifier (`harbor job regrade`, see `jobs_summary/*__regraded_dense`). The agent was not re-run.

| Run | Change Tested | Trial 1 (Binary / Dense) | Trial 2 (Binary / Dense) | Trial 3 (Binary / Dense) | Mean Binary | Mean Dense ($\bar{R}$) | Binary Advantage ($R_1-\bar{R}, R_2-\bar{R}, R_3-\bar{R}$) | Dense Advantage ($R_1-\bar{R}, R_2-\bar{R}, R_3-\bar{R}$) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Run 1: Baseline** | Original 3-bug task | `0 / 0.80` (5FozozC) | `0 / 0.80` (NP8YiBg) | `0 / 0.80` (be33Frz) | `0.00` | `0.80` | `0.00, 0.00, 0.00` | `0.00, 0.00, 0.00` |
| **Run 2: Ablation** | Sample CSV + its expected JSON placed in `/app/samples/` (one row pair differs only in nanoseconds) | `1 / 1.00` (aEY8mXo) | `1 / 1.00` (aUKZTM8) | `1 / 1.00` (sRzFyTc) | `1.00` | `1.00` | `0.00, 0.00, 0.00` | `0.00, 0.00, 0.00` |

**Reading the table.** Within each group of 3, every trial got the same reward under both graders, so every advantage is 0. Dense reward did not break the tie here because the policy's failure was **systematic**: all three baseline trials wrote the same parser and lost the same 0.20 (`check3c_nanoseconds`). Dense reward only produces a learning signal when trials in a group *differ*. What it does change is the *level*. Binary scores the baseline 0.00, the same as `nop`. Dense scores it 0.80 and pins down the one sub-rule it missed, which is how the ablation was designed.

If a training batch had grouped a baseline-style rollout with an ablation-style rollout (same prompt, one rollout happens to check the sample and one doesn't), the dense group mean would be 0.90. The non-checking rollout would get advantage −0.10 and the checking rollout +0.10, so the RL update would push toward "run the sample, compare, debug" and away from "write tests, delete them, submit".

## 4. Trajectory Forensics (`trajectory.json`)
- **Where the Agent Failed in Run 1:** In `run1_baseline/reconcile-bug__5FozozC`, step 6 ran `datetime.fromisoformat("2026-03-01T04:45:00.000000123Z")`. It printed `2026-03-01 04:45:00+00:00`, with the 123 ns already gone, and the agent moved on without noticing. At step 11 its own plan lists "Nanosecond precision" as an edge case to test, but the `test_edges.py` it actually wrote covers only offsets, ties and argument errors. At step 12 it deleted its test files and marked the task complete. `NP8YiBg` did write a nanosecond test at step 15, but put the two timestamps on *different* `tx_id`s (`N1`, `N2`), so their ordering was never compared. It printed the output with no assertion, and at step 16 claimed the code "handles timestamps with nanosecond precision". `be33Frz` never ran a nanosecond case. All three trials wrote the same truncating `fromisoformat` parser.
- **Ablation Hypothesis & Result:** The agent wasn't misreading the rule. It planned the right test and never ran it. So the one change was to give it data to check against: `/app/samples/sample_transactions.csv` plus `sample_expected_output.json`, with nothing about the code or where the bug is. All three ablation trials listed `/app/samples` within their first 3 steps and wrote the same truncating parser as the baseline. Running it on the sample produced `135.25` instead of the expected `74.05` (e.g. aEY8mXo step 7). They then inspected `load_latest` on the sample (step 9), found the nanosecond collapse, switched to a fraction-preserving sort key, re-ran until the output matched (step 14), and scored 3/3 binary and 1.00 dense.

## 5. Dense Reward & Anti-Cheat Design
- **My Dense Reward Weights (`tests/test.sh`):**

  | Check | Weight | Rule |
  | :--- | :--- | :--- |
  | `check1_cli` | 0.15 | one CSV argument works; no argument still exits non-zero |
  | `check2_status` | 0.25 | `SUCCESS`, `FAILED` and `PENDING` counted correctly |
  | `check3a_offsets` | 0.20 | latest row per `tx_id` chosen by the real UTC instant |
  | `check3b_exact_tie` | 0.10 | on an exact tie, the later row in the file wins |
  | `check3c_nanoseconds` | 0.20 | ordering keeps nanosecond precision |
  | `check3d_lower_z` | 0.10 | `z` accepted as the UTC designator |

  Bug 3 is worth 0.60 because it is where the real reasoning is. It is split into four sub-rules so the reward rises step by step instead of jumping from 0.40 straight to 1.00. Every check needs the script to run, so `nop`, where Bug 1 makes every run exit with a usage error, scores 0.00. Each check's inputs exercise only its own rule (e.g. nanosecond cases use only `Z` timestamps), so breaking one rule never costs another rule's points. Verified on 25 random seeds per variant: buggy 0.00, Bug 1 only 0.15, Bugs 1+2 0.40, typical agent rewrite 0.70–0.80, correct except tie rule 0.90, `solve.sh` 1.00, every seed identical.
- **How `solution/hack.sh` Cheated & How I Blocked It:** `hack.sh` swaps in a stub that keeps the CLI contract (usage error without an argument) but never parses a row. It reads the first `tx_id` of the input to tell which fixed test file it was given, then prints the memorised answer for that file. Against the naive dense verifier (`dev/verifiers/v2_dense_naive`) it scores **1.00** (`jobs_summary/proof_hack_vs_naive_dense`). The hardened `tests/verify.py` generates every CSV at grading time from a fresh random seed and computes the expected output with its own independent reference implementation. Each check runs 4 random cases and needs all 4. Duplicate pairs are adversarial: the truly latest row comes first in the file, and for offsets it also shows the earlier wall-clock time. Result: `hack.sh` = **0.00** (`jobs_summary/proof_hack_vs_hardened`). On top of that, `task.toml` sets `environment_mode = "separate"` and `artifacts = ["/app/reconcile.py"]`. Grading happens in a fresh container that receives only the agent's script, so nothing the agent left in its own container (a patched `python3`, a `.pth` hook, a planted `reward.txt`) reaches the grader. The candidate runs with `python3 -I -S` from a temp dir on a randomly named file, scripts that mention `/tests` or `/logs` are rejected, and `reward.txt` is written last.
- **Remaining Reward-Hacking Risk:** The candidate script still runs *inside the verifier container*, where `/tests/verify.py` and its reference implementation are readable. A smarter agent could locate that file without spelling the path literally (e.g. `os.walk("/")`, or building the string `"/te" + "sts"` at runtime, which slips past my static check), import its `reference()` function, and print perfect answers without implementing anything itself. The fix is to run the candidate as an unprivileged user that cannot read `/tests` (or in a nested sandbox), so the grader's code is out of its reach.

## 6. AI Tool Workflow
- **AI Tool & Model Used:** Claude Code (Claude Opus 5.5). It did the Harbor/Docker (Colima) setup, the task files, the three verifier versions (`dev/verifiers/`), the trajectory extraction scripts, and these runs. Transcripts are in `ai_transcripts/`.
- **How I Avoided Prompt Leakage:** The business rules were first written as a stand-alone spec with no mention of any bug. `instruction.md` was then written by a separate sub-agent that was given only that spec and told not to open `environment/`, `solution/`, `tests/` or `dev/`. When the spec gained the nanosecond and `z` rules, a fresh sub-agent updated it the same way. As a result `instruction.md` states every rule (including Bug 3's) but never names a function, line, library call or "bug".

## Repository notes
- `tasks/reconcile-bug/` is the final task, including the Run 2 sample files and the hardened dense verifier in `tests/`. Bug 3's spec-level rules (nanoseconds, `z`) were added after the two calibration runs, which used earlier versions of the task.
- `dev/verifiers/v1_binary` (graded Runs 1 and 2), `v2_dense_naive` (what `hack.sh` beats), `v3_dense_hardened` (= `tasks/reconcile-bug/tests`).
- `dev/reconcile_v1_easy_bug3.py` and `dev/reconcile_v2_subtle_code_bug3.py` are the buggy scripts used in the two calibration runs. `dev/summarize.py` prints per-trial rewards and checks for a job folder.
- `jobs_summary/` keeps `result.json`, `trajectory.json` and the verifier's per-check `checks.json` for every run, regrade, sanity and proof job.

### Reproduce
```bash
harbor run -p ./tasks/reconcile-bug -a nop       # 0.000
harbor run -p ./tasks/reconcile-bug -a oracle    # 1.000
harbor run -p ./tasks/reconcile-bug -a terminus-2 --model gemini/gemini-3.5-flash-lite -k 3 -n 1
harbor job regrade jobs/<job> -p ./tasks/reconcile-bug   # dense re-grade of recorded artifacts
```
