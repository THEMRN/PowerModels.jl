"""
A batch of runs: the settings of the Run form, with lists of values in place of single values.
Every combination of the values is one run, as in runners/batch_islanding.jl, and each run gets
a tag of its own, so it writes to a results folder of its own. Nothing here draws.

Two things go beyond every combination. Paired penalties: the lists of the penalty rows and of
all other loads go together by position, the first values in one run, the second in the next,
so each run has one whole set of penalties (an entry of `load_shedding_penalties` in the
script). And a penalty row may follow the target: in each run it is for that run's target zone
or area (or for all but it), so the penalties move with the island.

What may take a list is what batch_islanding.jl sweeps, and the load scaling factors:
the objective, the flow penalty, the OPF model, λ, the target zone or area, every load shedding
penalty (× λ), and the factor of every load scaling among the network modifications.

A batch is described by its `spec`, one list of values per field (`find_base_spec` gives the
spec of settings as they are, every list with one value):
    objective, flow_model, opf_model, lambda     lists of values
    target                                       zone or area names; left out for bus pairs
    uniform                                      penalties of every load; with uniform shedding only
    penalty_rows                                 one list per penalty row; without uniform shedding
    others                                       penalties of all other loads (None is the default)
    penalty_paired                               True when penalty_rows and others go together by position
    penalty_follows                              per penalty row, True when it is for each run's target
    load_scaling                                 one list of factors per load scaling
"""

import copy
import itertools
import math
import re

from advanced import where
from results_index import calc_folder_name
from settings import FORBIDDEN_TAG_CHARACTERS, GROUP_KINDS, clean_number, describe_penalty_row, validate

# ==================== Settings ====================
MAX_RUNS = 200                  # a batch larger than this is most likely a typing mistake (a range with a tiny step)
DEFAULT_TAG = "batch"           # tag prefix of a batch whose form has no output tag
RUNS_NAMED = 6                  # a problem names up to this many runs by number, and counts them beyond it
NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
RANGE = re.compile(rf"({NUMBER}):({NUMBER}):({NUMBER})")      # first:step:last, as a Julia range
VARIED_SEPARATOR = "  ·  "
PENALTY_PAIR = "penalties"      # the pair of the penalty lists, when they go together by position


# ==================== Lists of numbers ====================
def parse_values(text, unique=True):
    """
    The numbers of a text like "100, 250, 500" (commas, semicolons or spaces between them), each
    once, in their order. An item "0.5:0.5:2" is a range first:step:last, here 0.5, 1, 1.5, 2.
    With `unique` off a number written twice stays twice: in a paired list the place of a value
    says which run it is for. Raises ValueError with a readable message.
    """
    values = []
    for item in re.split(r"[\s,;]+", (text or "").strip()):
        if not item:
            continue
        match = RANGE.fullmatch(item)
        if match is not None:
            first, step, last = (float(part) for part in match.groups())
            if step <= 0 or last < first:
                raise ValueError(f'"{item}": a range is first:step:last, with a step above zero and a last value not below the first')
            count = int(math.floor((last - first) / step + 1e-9)) + 1
            if count > MAX_RUNS:
                raise ValueError(f'"{item}" is {count} values, more than a batch may have ({MAX_RUNS})')
            numbers = [first + step * place for place in range(count)]
        elif re.fullmatch(NUMBER, item):
            numbers = [float(item)]
        else:
            raise ValueError(f'"{item}" is not a number, nor a range like 0.5:0.5:2')
        for number in numbers:
            value = clean_number(round(number, 10))         # 0.1 + 0.2 as 0.3
            if value not in values or not unique:
                values.append(value)
    return values


def format_values(values):
    """Numbers as the text parse_values reads: "100, 250, 500"; a value that is not there (None) is left out."""
    return ", ".join(str(value) for value in values if value is not None)


def format_tag_number(value):
    """A number in a tag: "2.5", "500", "0.01"; "default" for none."""
    return "default" if value is None else f"{value:g}"


def clean_tag(text):
    """A tag without the characters a folder name cannot have, and without spaces."""
    forbidden = set(FORBIDDEN_TAG_CHARACTERS)
    return "".join("-" if character in forbidden or character.isspace() else character for character in text)


# ==================== The spec ====================
def find_base_spec(settings):
    """The spec of settings as they are: every field with its one value. The batch dialog starts from it."""
    penalties = settings["penalties"]
    spec = {
        "objective": [settings["objective"]],
        "flow_model": [settings["flow_model"]],
        "opf_model": [settings["opf_model"]],
        "lambda": [settings["lambda"]],
        "load_scaling": [[entry.get("factor")] for entry in find_scalings(settings)],
    }
    if settings["boundary"]["kind"] in GROUP_KINDS:
        spec["target"] = [settings["boundary"]["name"]]
    if penalties.get("uniform") is not None:
        spec["uniform"] = [penalties["uniform"]]
    else:
        spec["penalty_rows"] = [[row["times_lambda"]] for row in penalties.get("rows", [])]
        spec["others"] = [penalties.get("others")]
    return spec


def find_scalings(settings):
    """The load scalings among the settings' network modifications, in the order they apply."""
    return (settings.get("modifications") or {}).get("load_scaling") or []


# ==================== Dimensions: one per field that may take a list ====================
def build_dimension(values, apply, describe, tag_group=None, tag_prefix="", tag_text=str, pair=None):
    """
    One field of a batch: its `values`; `apply(settings, value)`, which writes one of them into a
    run's settings; `describe(value)`, what the run list says of it; and its part of the tag,
    `tag_prefix` then `tag_text(value)`. Fields of the same `tag_group` share a part, their
    values joined by "-". A field without a group is not in the tag (the objective, which the
    folder's name already has). Fields of the same `pair` go together by position instead of in
    every combination (find_combinations).
    """
    return {
        "values": list(values),
        "apply": apply,
        "describe": describe,
        "tag_group": tag_group,
        "tag_prefix": tag_prefix,
        "tag_text": tag_text,
        "pair": pair,
    }


def find_dimensions(settings, spec):
    """
    The fields of a batch in the order batch_islanding.jl sweeps them (the first varies slowest):
    objective, flow penalty, OPF model, λ, target, penalties, then the load scalings.
    """
    penalty_pair = PENALTY_PAIR if spec.get("penalty_paired") else None
    follows = spec.get("penalty_follows", [])
    following = [position for position, follow in enumerate(follows) if follow]    # the penalty rows for each run's target

    def set_field(key):
        return lambda run_settings, value: run_settings.update({key: value})

    def set_target(run_settings, value):
        run_settings["boundary"]["name"] = value
        for position in following:
            run_settings["penalties"]["rows"][position]["name"] = value

    def describe_row(row, position):
        if position not in following:
            return describe_penalty_row(row)
        return f"{'all but ' if row.get('except') else ''}target {row['kind']}"      # its name differs from run to run

    def set_uniform(run_settings, value):
        run_settings["penalties"]["uniform"] = value

    def set_others(run_settings, value):
        run_settings["penalties"]["others"] = value

    def set_penalty_row(position):
        return lambda run_settings, value: run_settings["penalties"]["rows"][position].update(times_lambda=value)

    def set_scaling(position):
        return lambda run_settings, value: run_settings["modifications"]["load_scaling"][position].update(factor=value)

    dimensions = [
        build_dimension(spec["objective"], set_field("objective"), str),
        build_dimension(spec["flow_model"], set_field("flow_model"), str, "flow_model"),
        build_dimension(spec["opf_model"], set_field("opf_model"), str, "opf_model", tag_text=str.lower),
        build_dimension(spec["lambda"], set_field("lambda"), lambda value: f"λ {value:g}", "lambda", "lam", format_tag_number),
    ]
    if "target" in spec:
        dimensions.append(
            # "target", not "zone": a penalty row beside it may name the same zone
            build_dimension(spec["target"], set_target, lambda value: f"target {value}", "target", tag_text=str.lower)
        )
    if "uniform" in spec:
        dimensions.append(
            build_dimension(spec["uniform"], set_uniform, lambda value: f"uniform {value:g} λ", "uniform", "uni", format_tag_number)
        )
    for position, values in enumerate(spec.get("penalty_rows", [])):
        row = settings["penalties"]["rows"][position]
        dimensions.append(
            build_dimension(
                values, set_penalty_row(position),
                lambda value, row=row, position=position: f"{describe_row(row, position)} {value:g} λ",
                "penalty", "pen", format_tag_number, pair=penalty_pair,
            )
        )
    if "others" in spec:
        dimensions.append(
            build_dimension(
                spec["others"], set_others,
                lambda value: "others default" if value is None else f"others {value:g} λ",
                "others", "oth", format_tag_number, pair=penalty_pair,
            )
        )
    for position, values in enumerate(spec.get("load_scaling", [])):
        entry = find_scalings(settings)[position]
        dimensions.append(
            build_dimension(
                values, set_scaling(position),
                lambda value, entry=entry: f"loads {where.describe_of(entry)} × {value:g}",
                "load_scaling", "load", format_tag_number,
            )
        )
    return dimensions


def find_axes(dimensions):
    """
    The fields as the axes of the batch, in their order: a field on its own, or the fields of one
    `pair` together. An axis is the list of its fields' positions in `dimensions`.
    """
    axes = []
    paired = {}                         # pair -> its axis
    for position, dimension in enumerate(dimensions):
        pair = dimension["pair"]
        if pair is None:
            axes.append([position])
        elif pair in paired:
            paired[pair].append(position)
        else:
            paired[pair] = [position]
            axes.append(paired[pair])
    return axes


def calc_axis_length(dimensions, axis):
    """
    How many values an axis has: those of its field, or of paired fields the number they share
    (a field with one value has it in every run). Raises ValueError for paired lists of
    different lengths.
    """
    counts = {len(dimensions[position]["values"]) for position in axis}
    if 0 in counts:
        return 0
    counts.discard(1)
    if len(counts) > 1:
        raise ValueError("paired lists need the same number of values, or one value")
    return counts.pop() if counts else 1


def count_runs(dimensions):
    """How many runs the batch has: the product of the axes' numbers of values."""
    return math.prod(calc_axis_length(dimensions, axis) for axis in find_axes(dimensions))


def find_combinations(dimensions):
    """
    The values of every run, one per field in the order of `dimensions`: every combination of
    the axes' values, the first axis varying slowest.
    """
    axes = find_axes(dimensions)
    lengths = [calc_axis_length(dimensions, axis) for axis in axes]
    combinations = []
    for places in itertools.product(*(range(length) for length in lengths)):
        combination = [None] * len(dimensions)
        for axis, place in zip(axes, places):
            for position in axis:
                values = dimensions[position]["values"]
                combination[position] = values[place] if len(values) > 1 else values[0]
        combinations.append(combination)
    return combinations


def build_tag(tag_prefix, dimensions, combination):
    """
    The output tag of one run: the batch's prefix, then one part per field that has more than
    one value, such as "spartanb_lam500_pen2.5-1.6" (two penalty rows vary).
    """
    parts = {}                          # tag group -> [prefix, texts], in the order of the fields
    for dimension, value in zip(dimensions, combination):
        if dimension["tag_group"] is None or len(dimension["values"]) < 2:
            continue
        part = parts.setdefault(dimension["tag_group"], [dimension["tag_prefix"], []])
        part[1].append(dimension["tag_text"](value))
    texts = [tag_prefix] if tag_prefix else []
    texts.extend(prefix + "-".join(values) for prefix, values in parts.values())
    return clean_tag("_".join(texts))


# ==================== The runs ====================
def expand_batch(settings, spec, tag_prefix):
    """
    The runs of a batch, one per combination of the spec's values (paired lists by position): a list of
    {"settings", "varied", "folder"}. `settings` are the run's own, with its output tag;
    `varied` says what this run has of the fields that vary ("λ 500  ·  zone SPARTANB 2.5 λ");
    `folder` is the results folder it writes to. Raises ValueError for a batch of more than
    MAX_RUNS runs, of none (a field without a value), or of paired lists of different lengths.
    """
    dimensions = find_dimensions(settings, spec)
    count = count_runs(dimensions)
    if count == 0:
        raise ValueError("every field needs at least one value")
    if count > MAX_RUNS:
        raise ValueError(f"{count} runs are more than a batch may have ({MAX_RUNS})")

    runs = []
    for combination in find_combinations(dimensions):
        run_settings = copy.deepcopy(settings)
        varied = []
        for dimension, value in zip(dimensions, combination):
            dimension["apply"](run_settings, value)
            if len(dimension["values"]) > 1:
                varied.append(dimension["describe"](value))
        run_settings["output_tag"] = build_tag(tag_prefix, dimensions, combination)
        runs.append({
            "settings": run_settings,
            "varied": VARIED_SEPARATOR.join(varied),
            "folder": calc_folder_name(run_settings),
        })
    return runs


def describe_run_numbers(numbers, count):
    """Which runs of a batch of `count` a problem is in: "every run", "run 3", "runs 2, 4", "24 of 48 runs"."""
    if len(numbers) == count:
        return "every run"
    if len(numbers) > RUNS_NAMED:
        return f"{len(numbers)} of {count} runs"
    return ("run " if len(numbers) == 1 else "runs ") + ", ".join(str(number) for number in numbers)


def find_problems(runs, check=None):
    """
    What keeps a batch from running: the problems `validate` finds in each run's settings, those
    of `check(settings)` (the network modifications, which the advanced dialog's tabs check
    against the case), and runs that would write to the same folder. A problem several runs
    share is listed once, with the runs it is in.
    """
    found = {}                          # problem -> the runs it is in
    folders = {}                        # folder -> the runs that write to it
    for number, run in enumerate(runs, start=1):
        problems = validate(run["settings"])
        if check is not None:
            problems.extend(check(run["settings"]))
        for problem in problems:
            found.setdefault(problem, []).append(number)
        folders.setdefault(run["folder"].lower(), []).append(number)    # Windows folder names ignore case

    texts = [f"{problem} ({describe_run_numbers(numbers, len(runs))})" for problem, numbers in found.items()]
    for numbers in folders.values():
        if len(numbers) > 1:
            texts.append(f"{describe_run_numbers(numbers, len(runs))} would write to the same folder, {runs[numbers[0] - 1]['folder']}")
    return texts
