"""
Check what the results panel shows against the printed reports of the same runs.

    python runners/gui/dev/send_jobs.py --full runners/gui/dev/jobs_results_check.json > runs.log
    python runners/gui/dev/check_results_tables.py runs.log

The log has, for each run, the console reports and the whole @@result line (send_jobs.py prints
both; --full keeps the control lines whole). jobs_results_check.json has five runs without the
dynamic simulation: savnw, ACTIVSg500 with frequency security, savnw and ACTIVSg500 with voltage
security, and case9, which has no zone records.
For each run this builds the tables with the panel's own find_* functions (results_view.py and
voltage_details.py) and compares their cells, formatted as the panel formats them, with the
numbers the console printed.

The console prints generation in pu to 4 decimals (0.01 MW) and the flow sums in pu to 3 decimals
(0.1 MW), so those are compared at the console's precision after x100. What the console does not
print (each line's flow, each bus's shed, the generation total) is checked against the totals.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))       # runners/gui
import theme                                                    # noqa: E402
from components import results_view, voltage_details           # noqa: E402

if len(sys.argv) != 2:
    sys.exit(__doc__)
LOG = Path(sys.argv[1])
NUMBER = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
checks = 0
failures = []


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        failures.append(message)


def shown(table, row, title):
    """The cell of `row` under the column `title`, as the panel shows it."""
    columns = table[0]
    for column_title, key, digits in columns:
        if column_title == title:
            value = row.get(key)
            return ("" if value is None else str(value)) if digits is None else theme.format_number(value, digits)
    raise KeyError(title)


def close(text, value, tolerance):
    return abs(float(text) - value) <= tolerance


lines = LOG.read_text(encoding="utf-8", errors="replace").split("\n")
starts = [i for i, line in enumerate(lines) if "@@start" in line] + [len(lines)]
for job, (first, last) in enumerate(zip(starts, starts[1:]), start=1):
    segment = lines[first:last]
    result_line = next((line for line in reversed(segment) if "@@result" in line), None)     # the final one: a run with the simulation sends one before it too
    if result_line is None:
        continue
    summary = json.loads(result_line[result_line.index("{"):])["summary"]
    text = "\n".join(segment)
    tag = f"job {job}"

    # objective, as printed
    printed = re.search(r"^objective:(\S+)", text, re.M)
    check(printed and printed.group(1) == str(summary["objective"]), f"{tag}: objective {printed and printed.group(1)} vs {summary['objective']}")

    # generation by group: name, Pg, Pmax, used %, Qg, Qmax, used % (pu, 4 decimals)
    table = results_view.find_generation_table(summary)
    rows = {str(row["name"]): row for row in table[1]}
    block = re.search(r"Generation status by \w+:\n.*\n((?:.+%\s*\n)*)", text)
    printed_rows = [line.split() for line in block.group(1).strip().split("\n")] if block and block.group(1).strip() else []
    check(len(printed_rows) == len(rows), f"{tag}: {len(printed_rows)} generation lines printed, {len(rows)} rows")
    for name, pg, pmax, p_used, qg, qmax, q_used in printed_rows:
        row = rows[name]
        for title, pu in (("Pg (MW)", pg), ("Pmax (MW)", pmax), ("Qg (Mvar)", qg), ("Qmax (Mvar)", qmax)):
            check(close(shown(table, row, title), float(pu) * 100, 0.0051), f"{tag}: generation {name} {title}: {shown(table, row, title)} vs {pu} pu")
        check(shown(table, row, "P used (%)") == p_used.rstrip("%"), f"{tag}: generation {name} P used {shown(table, row, 'P used (%)')} vs {p_used}")
        check(shown(table, row, "Q used (%)") == q_used.rstrip("%"), f"{tag}: generation {name} Q used {shown(table, row, 'Q used (%)')} vs {q_used}")
    total = table[2][0]
    network = re.search(rf"Network: Pg=({NUMBER}), Pmax=({NUMBER}), Used=({NUMBER})%, Qg=({NUMBER}), Qmax=({NUMBER}), Used=({NUMBER})%", text)
    if network:     # a case without group records prints the whole network on one line
        for title, pu in zip(("Pg (MW)", "Pmax (MW)", "Qg (Mvar)", "Qmax (Mvar)"), (network.group(1), network.group(2), network.group(4), network.group(5))):
            check(close(shown(table, total, title), float(pu) * 100, 0.0051), f"{tag}: network {title}: {shown(table, total, title)} vs {pu} pu")
        check(float(shown(table, total, "P used (%)")) == float(network.group(3)) and float(shown(table, total, "Q used (%)")) == float(network.group(6)), f"{tag}: network used %")
    if rows:        # the total is not printed: it has to be the sum of the groups
        check(abs(sum(row["pg_mw"] for row in rows.values()) - total["pg_mw"]) < 0.01 * len(rows), f"{tag}: generation total Pg")
        check(abs(sum(row["pmax_mw"] for row in rows.values()) - total["pmax_mw"]) < 0.01 * len(rows), f"{tag}: generation total Pmax")

    # load shed by group: name : shed MW, load MW, shed %
    if summary["load_shed"] is not None:
        table = results_view.find_shed_group_table(summary)
        rows = {str(row["name"]): row for row in table[1]}
        # a group without a record is printed as "Zone 1" and named "1" in the summary
        printed_rows = re.findall(rf"^(?:Zone |Area )?(\S+)\s*:\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})%", text, re.M)
        check(len(printed_rows) == len(rows), f"{tag}: {len(printed_rows)} shed lines printed, {len(rows)} rows")
        for name, shed, load, percent in printed_rows:
            row = rows[name]
            check(float(shown(table, row, "Shed (MW)")) == float(shed), f"{tag}: shed {name} {shown(table, row, 'Shed (MW)')} vs {shed}")
            check(float(shown(table, row, "Load (MW)")) == float(load), f"{tag}: load {name} {shown(table, row, 'Load (MW)')} vs {load}")
            check(shown(table, row, "Shed (%)") == percent, f"{tag}: shed % {name} {shown(table, row, 'Shed (%)')} vs {percent}")
        printed = re.search(rf"Total load shed: ({NUMBER}) MW from ({NUMBER}) MW", text)
        total = table[2][0]
        check(float(shown(table, total, "Shed (MW)")) == float(printed.group(1)), f"{tag}: total shed {total['shed_mw']} vs {printed.group(1)}")
        check(float(shown(table, total, "Load (MW)")) == float(printed.group(2)), f"{tag}: total load {total['load_mw']} vs {printed.group(2)}")

        # the buses are not printed: their sums have to be the totals, and the filter keeps the buses that shed
        all_buses = results_view.find_shed_bus_table(summary, only_shed=False)[1]
        shed_buses = results_view.find_shed_bus_table(summary, only_shed=True)[1]
        check(abs(sum(row["shed_mw"] for row in all_buses) - total["shed_mw"]) < 0.005 * len(all_buses) + 0.011, f"{tag}: bus sheds add up to {sum(row['shed_mw'] for row in all_buses)}, total {total['shed_mw']}")
        check(abs(sum(row["pd_mw"] for row in all_buses) - total["load_mw"]) < 0.005 * len(all_buses) + 0.011, f"{tag}: bus loads add up to {sum(row['pd_mw'] for row in all_buses)}, total {total['load_mw']}")
        check(all(row["shed_mw"] > 0 for row in shed_buses) and len(shed_buses) == sum(1 for row in all_buses if row["shed_mw"] > 0), f"{tag}: the filter of buses with shed")

    # boundary flows: the two sums are printed in pu to 3 decimals; the lines are not printed
    table = results_view.find_flow_table(summary)
    for footer, label in zip(table[2], ("Total net flow through target lines", "Sum of absolute flows through target lines")):
        printed = re.search(rf"{label}:\s+P = ({NUMBER}), Q = ({NUMBER}), Total = ({NUMBER})", text)
        for title, pu in zip(("P (MW)", "Q (Mvar)", "P + Q"), printed.groups()):
            check(close(shown(table, footer, title), float(pu) * 100, 0.0501), f"{tag}: {label} {title}: {shown(table, footer, title)} vs {pu} pu")
    net = table[2][0]
    check(abs(sum(row["p_mw"] for row in table[1]) - net["p_mw"]) < 0.005 * len(table[1]) + 0.011, f"{tag}: line P add up to the net flow")
    check(abs(sum(row["q_mvar"] for row in table[1]) - net["q_mvar"]) < 0.005 * len(table[1]) + 0.011, f"{tag}: line Q add up to the net flow")

    # frequency: one block of four lines per island
    if summary["frequency"] is not None:
        table = results_view.find_frequency_table(summary)
        printed_islands = re.findall(
            rf"Island at bus (\d+): (\d+) buses, (\d+) gens \((\d+) with governor\)\n"
            rf"\s+H = ({NUMBER}) s, K = ({NUMBER}) pu, D = ({NUMBER}) pu \(system base\)\n"
            rf"\s+limits: RoCoF ({NUMBER}) MW, QSS ({NUMBER}) MW, nadir ({NUMBER}) MW \((\w+) binds\)\n"
            rf"\s+scheduled import: ({NUMBER}) MW", text)
        check(len(printed_islands) == len(table[1]), f"{tag}: {len(printed_islands)} frequency islands printed, {len(table[1])} rows")
        for printed, row in zip(printed_islands, table[1]):
            check(row["island_bus"] == int(printed[0]), f"{tag}: frequency island at bus {row['island_bus']} vs {printed[0]}")     # the panel names it, by the target
            titles = ("Buses", "Generators", "With governor", "H (s)", "K (pu)", "D (pu)", "RoCoF limit (MW)", "QSS limit (MW)", "Nadir limit (MW)")
            for title, value in zip(titles, printed[1:10]):
                check(float(shown(table, row, title)) == float(value), f"{tag}: frequency {title}: {shown(table, row, title)} vs {value}")
            check(shown(table, row, "Binding").lower() == printed[10].lower(), f"{tag}: binding {shown(table, row, 'Binding')} vs {printed[10]}")
            check(float(shown(table, row, "Scheduled import (MW)")) == float(printed[11]), f"{tag}: import {shown(table, row, 'Scheduled import (MW)')} vs {printed[11]}")

    # voltage: the rounds, their islands, indicators, limits and sheds
    if summary["voltage"] is not None:
        voltage = summary["voltage"]
        round_starts = [m.start() for m in re.finditer(r"Voltage viability, round \d+:", text)]
        check(len(round_starts) == len(voltage["details"]) == voltage["rounds"], f"{tag}: {len(round_starts)} rounds printed, {len(voltage['details'])} in the details, rounds {voltage['rounds']}")
        verdict = re.search(r"Voltage (verified|not verified)\D*(\d+)", text)
        check(verdict and (verdict.group(1) == "verified") == voltage["verified"], f"{tag}: voltage verdict")
        round_ends = round_starts[1:] + [verdict.start() if verdict else len(text)]
        for voltage_round, begin, end in zip(voltage["details"], round_starts, round_ends):
            block = text[begin:end]
            where = f"{tag} round {voltage_round['round']}"
            head = re.match(rf"Voltage viability, round (\d+): (.*)", block)
            check(int(head.group(1)) == voltage_round["round"] and head.group(2).strip() == voltage_details.describe_round(voltage_round), f"{where}: title '{head.group(2)}' vs '{voltage_details.describe_round(voltage_round)}'")

            islands = voltage_details.find_island_table(voltage_round)
            by_bus = {str(row["bus"]): row for row in islands[1]}
            for bus in re.findall(r"Island at bus (\d+) has no generator", block):
                check(by_bus[bus]["status"] == "no_generator" and "no generator" in shown(islands, by_bus[bus], "State"), f"{where}: island {bus} without generator")
            checked = re.findall(
                rf"Island at bus (\d+): (\d+) buses, (\d+) with generation, (\d+) holding their voltage\n"
                rf"\s+generators at a reactive limit: upper (.*); lower (.*)\n"
                rf"\s+slack bus (\d+): P = ({NUMBER}) MW, Q = ({NUMBER}) Mvar", block)
            limits = {str(row["island"]): row for row in voltage_details.find_limit_table(voltage_round)[1]}
            check(len(checked) == len(limits), f"{where}: {len(checked)} checked islands printed, {len(limits)} rows")
            for bus, n_buses, with_generation, holding, upper, lower, slack_bus, slack_p, slack_q in checked:
                row = by_bus[bus]
                for title, value in (("Buses", n_buses), ("With generation", with_generation), ("Holding voltage", holding), ("Slack bus", slack_bus), ("Slack P (MW)", slack_p), ("Slack Q (Mvar)", slack_q)):
                    check(float(shown(islands, row, title)) == float(value), f"{where}: island {bus} {title}: {shown(islands, row, title)} vs {value}")
                check(limits[bus]["upper"] == upper.strip() and limits[bus]["lower"] == lower.strip(), f"{where}: island {bus} limits '{limits[bus]['upper']}' / '{limits[bus]['lower']}' vs '{upper}' / '{lower}'")

            indicators = voltage_details.find_indicator_table(voltage_round)
            printed_indicators = re.findall(rf"indicator ({NUMBER}) at bus (\d+) \(V = ({NUMBER}) pu, load ({NUMBER}) MW\)", block)
            check(len(printed_indicators) == len(indicators[1]), f"{where}: {len(printed_indicators)} indicators printed, {len(indicators[1])} rows")
            for printed, row in zip(printed_indicators, indicators[1]):
                for title, value in zip(("Indicator", "Bus", "V (pu)", "Load (MW)"), printed):
                    check(float(shown(indicators, row, title)) == float(value), f"{where}: indicator {title}: {shown(indicators, row, title)} vs {value}")
            # each island's worst indicator is its first printed one
            for row in islands[1]:
                if row["status"] == "checked":
                    first = next(r for r in indicators[1] if r["island"] == row["bus"])
                    check(row["worst_indicator"] == first["value"], f"{where}: island {row['bus']} worst indicator")

            sheds = voltage_details.find_shed_table(voltage_round)
            printed_sheds = re.findall(rf"shed sized at bus (\d+): ({NUMBER}) MW of ({NUMBER}) MW", block)
            printed_after = re.findall(rf"indicator after that shed: ({NUMBER}) at bus (\d+)", block)
            check(len(printed_sheds) == len(sheds[1]), f"{where}: {len(printed_sheds)} sheds printed, {len(sheds[1])} rows")
            for printed, row in zip(printed_sheds, sheds[1]):
                for title, value in zip(("Shed at bus", "Shed (MW)", "Of load (MW)"), printed):
                    check(float(shown(sheds, row, title)) == float(value), f"{where}: shed {title}: {shown(sheds, row, title)} vs {value}")
            shown_after = sorted({(shown(sheds, row, "Indicator after"), shown(sheds, row, "At bus")) for row in sheds[1]})
            check(sorted((f"{float(value):.3f}", bus) for value, bus in printed_after) == shown_after, f"{where}: indicators after the sheds {printed_after} vs {shown_after}")
        last = voltage["details"][-1]
        worst = max(row["worst_indicator"] for row in voltage_details.find_checked_islands(last))
        check(worst == voltage["worst_indicator"], f"{tag}: worst indicator {voltage['worst_indicator']} vs the last round's {worst}")

    print(f"{tag}: tabs {results_view.find_tabs(summary)}")

print(f"{checks} checks, {len(failures)} failed")
for failure in failures:
    print("  FAILED", failure)
