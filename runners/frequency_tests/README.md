# Frequency-security tests

Tests of the frequency-security constraint (`runners/frequency.jl`, used by `build_custom_pf` when
`run_islanding(...; frequency_security=true)`), on savnw and ACTIVSg500, with ANDES for the dynamics.
Nothing here changes the pipeline: the scripts call the same functions `run_islanding` uses.

Run from the repository root, in order:

```bash
julia --project=. runners/frequency_tests/1_offline.jl     # ~1.5 min
julia --project=. runners/frequency_tests/2_model.jl       # ~1 min
julia --project=. runners/frequency_tests/3_dynamic.jl     # ~20 min of ANDES runs ("sweeps" or "passfail" for one part)
python runners/frequency_tests/build_report.py             # HTML report
python runners/frequency_tests/build_summary.py            # one-page summary (PDF) and its three figures
```

| File | What it does |
|---|---|
| `common.jl` | packages, runner includes, the test scenarios (boundaries and network changes in the style of `islanding.jl`), solve / export / ANDES helpers, a trajectory version of the SFR model |
| `1_offline.jl` | machine data from the .dyr (cross-checked by `andes_dyr_check.py`), islands and H/K/D/limits recomputed by hand, nadir-limit checks (bisection, linearity, Euler vs exact), sensitivity of the limits to H, K, D |
| `2_model.jl` | 23 off/on solves with an expected outcome each: `binds`, `within`, `unchanged`, `infeasible` |
| `3_dynamic.jl` | A: calibration sweeps (import of the first island fixed by a test-only equality, relays removed from the .dyr); B: off/on runs through `run_islanding` with the relays |
| `analyze_andes.py` | per ANDES run: centre-of-inertia frequency of each island, RoCoF / nadir / zenith / settling against the SFR model, power, load and voltage steps at the split, UFLS and generator trips |
| `build_report.py`, `report_template.html` | the report, `results/frequency_tests/frequency_security_tests.html` |
| `build_summary.py`, `summary.html`, `summary_short.html` | one-page black-and-white summary for meetings (and a half-length version) with its three figures (matplotlib, PNG and PDF), in `results/frequency_tests/summary/`; the page is printed with Edge or Chrome headless |

Results go to `results/frequency_tests/` (`offline/`, `model/`, `dynamic/sweep_*/`, `dynamic/passfail/`).
Each ANDES run folder keeps the exported case, `line_outage.json`, `islands.json`, the channels
(`output_andes_*.csv.gz`), `console.txt` and `metrics.json`. The HTML report of `dynamic.py` is kept
for the off/on runs only (`KEEP_SWEEP_REPORTS` in `3_dynamic.jl`), since it is 60 MB per ACTIVSg500 run.

ANDES runs with `BROWSER` pointing at Git's `true.exe`, so `dynamic.py` does not open a browser tab per run.
