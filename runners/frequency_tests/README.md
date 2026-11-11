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

## Open items

These were recorded on 2026-11-10, when the frequency bounds were closed and the work moved on to voltage.
The numbers come from scratch runs on ANDES that are not part of the scripts here.

- **The stored results were made with load damping 1.0.** `LOAD_DAMPING` in `frequency.jl` is now 0, because
  the simulated loads do not change with frequency (the change proposed in section 6.4 of the HTML report).
  Everything in `results/frequency_tests/` predates this, so the suite has to be run again. A scratch run of
  `2_model.jl` with zero damping passed 22 of 23 tests. The one failure is an outdated expectation.
  `activsg_spartanb` with `flow_shed` expects `unchanged`, but its 33.3 MW import is now above the 32.0 MW limit,
  so the constraint binds and the expectation should become `binds`. Some `purpose` texts in `2_model.jl` also
  quote old values. SPARTANB's limit is no longer 49.4 MW. The QSS limit of savnw left (D x 0.3/60) is now zero,
  so that island must import exactly nothing.
- **SPARTANB is still insecure with zero damping.** Its limit drops from 39.1 to 32.0 MW and the preemptive
  shedding rises from 399.3 to 406.3 MW. The simulated nadir improves from 59.43 to 59.48 Hz, but the first UFLS
  stage still sheds about 29 MW. MIDLANDS and YORK stay secure (nadir 59.52 Hz, zenith 60.42 Hz). YORK sheds
  5.5 MW more and MIDLANDS is unchanged, because its RoCoF limit binds.
- **The load also steps at the split.** The simulated P load is constant current, so the island load follows the
  voltage step at the split, which the SFR model does not see. The step is largest at the split and about halves
  within 1 to 1.5 s as the exciters act. In SPARTANB with halved load and a 25 MW import it is +13.0 MW after
  20 ms and +7.8 MW once settled. In savnw north with a 75 MW import it is -76.6 MW and then -32.7 MW. A steady
  power flow of the island with voltage-dependent loads predicts the settled part within about 2 MW, but not the
  peak. With constant-power P loads the SFR model matches the simulation within about 0.02 Hz (SPARTANB with
  halved load and 25 MW: 59.63 Hz simulated, 59.61 Hz from the model with zero damping). The rest of SPARTANB's
  miss is mostly this transient.
- **The outer check needs more than one step.** The proposal (2027 Q3) tightens the nadir limit after the
  simulation. One proportional step on SPARTANB, scaling the limit by (60 - 59.5)/(60 - simulated nadir), gives
  30.7 MW and a nadir of 59.495 Hz, and UFLS still sheds 29.2 MW. The load-step offset is roughly fixed rather
  than proportional to the import, so proportional tightening falls short. Near the limit the nadir moves about
  0.013 Hz per MW, so about 30.3 MW would clear. The loop needs two or three proportional steps, or an additive
  step.
- **savnw north heavy is a voltage problem.** Its import sits at the 56.5 MW limit, but the load-bus voltage
  falls 0.27 pu at the split. The island load drops 273 MW and the power step becomes -212 MW, giving a zenith of
  60.89 Hz. The outcome depends entirely on the load model. With constant-power P there is no solution at the
  split. With constant impedance two units trip, the zenith reaches 61.37 Hz and the simulation stops at 15.3 s.
  With constant current it runs through. This case belongs to the voltage work.
- **savnw top does not start from a steady state.** Unit 3011 is dispatched below its governor minimum, which the
  optimization does not know about. One unit trips and the simulation stops at 1.3 s, before the split.
- **savnw left is not a viable island.** It has two buses and its only unit (3018) has no governor, so K = 0.
  With damping 1.0 its limit was 1 MW, and even then the frequency drifted until UFLS shed 5.7 MW and the unit
  tripped. With zero damping its limit is zero. It stays as a test of that edge case.
- **SPARTANB at 200 and 300 MW in the calibration sweep was not looked into.** With the relays removed, the
  frequency falls to about 51 Hz and ANDES stops 5.5 and 3.8 s after the split. The island load ends at half its
  value, so the voltage collapses as well. Both imports are far above the limit.
- **Some limits have no source.** The proposal leaves the RoCoF and settling limits as symbols without values,
  and the code gives none.
  - `MAX_ROCOF = 0.5` Hz/s has no North American source. The closest found is Ireland's former grid code
    limit; EirGrid has since moved to 1 Hz/s.
  - `MAX_QSS_DEVIATION = 0.3` Hz has no source at all.
  - `MIN_NADIR_FREQUENCY = 59.5` Hz is the first UFLS stage in the case's own .dyr. It appears to agree with the
    first stage of NPCC's program (PRC-006-NPCC-2, NPCC Directory 12), but that was seen in search summaries
    only, not in the documents.
  - `REHEAT_FRACTION = 0.3` and `REHEAT_TIME = 7.0` s are typical values with no source cited.
  - `LOAD_DAMPING = 0` matches the simulated loads. Textbooks give real loads 1 to 2, so the limits are
    conservative for a real system.
- **ANDES is the only simulator now.** PSS®E is no longer available, so the ANDES results are not cross-checked.
  The HYGOV correction in `runners/andes_scripts/dynamic.py` was checked only against the block diagram in the PSS®E
  manual. `run_islanding` still defaults to `simulator = "psse"`.
