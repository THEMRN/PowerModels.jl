"""
Compare page: runs side by side, and the trade-off between the preemptive shed and the margins.

Runs come here from the Run page (Compare in the runs table) and from History (Add to
compare), and a batch adds its runs as they finish. The list is the app's (`ctx.compare`,
comparison.py), so every browser tab shows the same runs.

- Side by side: one column per run. First the settings in which the runs differ, then what each
  run found: solution, load shedding, boundary flows, frequency per island, voltage, and the
  shed by zone or area.
- Trade-off: each run is a point, its preemptive shed against its frequency margin (per
  island) and against its voltage margin, the figure of the proposal's "How much preparation
  is enough". The two margins have different units, so they are two charts. Under them, the
  dynamic response: one curve per run on one chart, a bus's frequency or voltage or the lowest
  of a side's buses, read from the runs' channel files once the tab is shown.

What the page says is comparison.py's business (`find_*`, `calc_*`), which draws nothing; this
module draws it. The charts' colours are the group colours of the Network page. The chart of the
dynamic response is built and zoomed as the Dynamics tab's (dynamics.py, dynamics_view.py).
"""

from html import escape

from nicegui import background_tasks, run, ui

import comparison
import dynamics
import theme
from components.dynamics_view import CHART_JS, CLEAR_JS, ZOOM_NOTE, build_script
from network_view import GROUP_COLORS, OTHER_GROUP_COLOR

# ==================== Settings ====================
TITLE = "Compare"
TAB_LABELS = {"table": "Side by side", "tradeoff": "Trade-off"}
SOURCE_LABELS = {"simulated": "dynamic simulation", "predicted": "SFR model"}
SERIES_COLORS = GROUP_COLORS[:3]    # a scatter chart keeps three colours apart; a fourth island and later ones share one grey
LABELLED_POINTS = 8                 # a chart with more points than this names them in the tooltip only
POINT_SIZE = 12                     # px
AXIS_CLEARANCE = 0.06               # share of the widest shed within which a point counts as standing on the vertical axis
BELOW_LIMIT_FILL = "rgba(209, 52, 63, 0.06)"    # theme.BAD, faint: the part of a chart where the margin is negative
CHART_FONT = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif'
HOW_TO = [  # what the page says while it has no run
    "Add runs with Compare in the runs table of the Run page, or with Add to compare in History. A batch adds its runs as they finish.",
    "Only a run with its final results can be compared: a GUI run that finished, since the GUI keeps results.",
]
STOPPED_EARLY_NOTE = "A hollow point is a run whose simulation stopped early, so its frequency is the last one simulated, not a settled one."
NOT_VERIFIED_NOTE = (
    "A hollow point is a run whose voltage was not verified. Above the limit line, that is a run with an island "
    "that could not be checked, so its margin is that of the other islands only."
)
CURVE_WIDTH = 1.6                   # px, a run's curve on the chart of the dynamic response


# ==================== The side by side table ====================
def build_rows_html(sections, count):
    """
    The rows of the comparison as the cells of one grid, in HTML: a title per section across the
    grid, then per row its name and one value per run. Every text is escaped: names come from
    case files and tags.
    """
    cells = []
    for title, rows in sections:
        cells.append(f'<div class="eyebrow compare-section">{escape(title)}</div>')
        for row in rows:
            cells.append(f'<div class="compare-name" title="{escape(row["name"])}">{escape(row["name"])}</div>')
            tones = row.get("tones") or [""] * count
            for value, tone in zip(row["values"], tones):
                cells.append(f'<div class="compare-value num {tone}" title="{escape(str(value))}">{escape(str(value))}</div>')
    return "".join(cells)


# ==================== The trade-off charts ====================
def find_series_color(position):
    """The colour of the island at `position` among a chart's islands: three colours in a fixed order, then one grey."""
    return SERIES_COLORS[position] if position < len(SERIES_COLORS) else OTHER_GROUP_COLOR


def build_tip(lines):
    """A tooltip as HTML: the first line stands out, every text is escaped."""
    first, rest = lines[0], lines[1:]
    return "<br>".join([f"<b>{escape(first)}</b>"] + [escape(line) for line in rest])


def describe_frequency_point(island, point, source):
    """What the tooltip of a point of the frequency chart says."""
    lines = [
        f"{point['run']} · {point['tag']}",
        f"{island}: {point['extreme']} {point['value_hz']:.3f} Hz ({SOURCE_LABELS[source]}), limit {point['limit_hz']:.3f} Hz",
        f"Frequency margin {point['margin']:.3f} Hz",
        f"Preemptive shed {point['shed_mw']:.2f} MW",
    ]
    if point["stopped_early"]:
        lines.append("The simulation stopped early")
    return build_tip(lines)


def describe_voltage_point(point):
    """What the tooltip of a point of the voltage chart says."""
    lines = [
        f"{point['run']} · {point['tag']}",
        f"Worst indicator {point['worst_indicator']:.3f}, threshold {point['threshold']:.3f}",
        f"Voltage margin {point['margin']:.3f}",
        f"Preemptive shed {point['shed_mw']:.2f} MW",
    ]
    if not point["verified"]:
        lines.append("Voltage not verified")
    return build_tip(lines)


def build_chart_series(name, color, points, labelled):
    """One series of a chart: `points` are {"x", "y", "name", "tip", "hollow"}; a hollow point is drawn as a ring."""
    data = []
    for point in points:
        item = {"value": [point["x"], point["y"]], "name": point["name"], "tip": point["tip"]}
        if point["hollow"]:
            item["itemStyle"] = {"color": theme.SURFACE, "borderColor": color, "borderWidth": 2}
        data.append(item)
    return {
        "type": "scatter",
        "name": name,
        "data": data,
        "symbolSize": POINT_SIZE,
        "itemStyle": {"color": color, "borderColor": theme.SURFACE, "borderWidth": 2},     # a ring of the surface between points that touch
        "emphasis": {"scale": 1.5},
        "label": {"show": labelled, "position": "top", "formatter": "{b}", "color": theme.INK_2, "fontSize": 11},
        "labelLayout": {"hideOverlap": True},
    }


def build_chart_options(series, y_name):
    """
    The ECharts options of one trade-off chart: the preemptive shed on the horizontal axis, a
    margin on the vertical one, and a line at zero (the limit), since a point is acceptable only
    above it. The part below the line is tinted when a point is in it. A legend shows with two
    series or more.
    """
    axis = {
        "type": "value",
        "nameLocation": "middle",
        "nameTextStyle": {"color": theme.INK_2, "fontSize": 12},
        "axisLine": {"show": True, "lineStyle": {"color": theme.LINE_STRONG}},
        "axisTick": {"show": False},
        "axisLabel": {"color": theme.INK_3, "fontSize": 11},
        "splitLine": {"lineStyle": {"color": theme.LINE}},
    }
    if series:
        series[0]["markLine"] = {
            "silent": True,
            "symbol": "none",
            "lineStyle": {"color": theme.INK_3, "type": "solid", "width": 1},
            "label": {"formatter": "limit", "position": "insideEndTop", "color": theme.INK_2, "fontSize": 11},
            "data": [{"yAxis": 0}],
        }
    # a point at or near zero shed stands on the vertical axis: its name goes to its right, clear of the axis numbers
    items = [item for entry in series for item in entry["data"]]
    widest = max((item["value"][0] for item in items), default=0)
    for item in items:
        if item["value"][0] <= AXIS_CLEARANCE * widest:
            item["label"] = {"position": "right"}
    if any(item["value"][1] < 0 for item in items):
        series[0]["markArea"] = {
            "silent": True,
            "itemStyle": {"color": BELOW_LIMIT_FILL},
            "label": {"show": True, "position": "insideBottomLeft", "color": theme.INK_2, "fontSize": 11, "formatter": "below the limit"},
            "data": [[{"yAxis": 0}, {"yAxis": -1e6}]],
        }
    return {
        "animation": False,
        "textStyle": {"fontFamily": CHART_FONT},
        "grid": {"left": 62, "right": 28, "top": 34 if len(series) > 1 else 16, "bottom": 44},
        "legend": {
            "show": len(series) > 1,
            "top": 0,
            "left": 0,
            "icon": "circle",
            "itemWidth": 9,
            "itemHeight": 9,
            "textStyle": {"color": theme.INK_2, "fontSize": 12},
        },
        "tooltip": {
            "trigger": "item",
            ":formatter": "params => params.data.tip",
            "backgroundColor": theme.SURFACE,
            "borderColor": theme.LINE_STRONG,
            "borderWidth": 1,
            "padding": [7, 10],
            "textStyle": {"color": theme.INK, "fontSize": 12},
            "extraCssText": "box-shadow: 0 6px 20px rgba(16, 24, 40, 0.14); border-radius: 6px; line-height: 1.5;",
        },
        "xAxis": dict(axis, name="Preemptive shed (MW)", nameGap=28, min=0),
        "yAxis": dict(axis, name=y_name, nameGap=44),
        "series": series,
    }


def build_frequency_chart(tradeoff, source):
    """The options of the frequency chart: one series per island."""
    count = sum(len(entry["points"]) for entry in tradeoff["frequency"])
    series = []
    for position, entry in enumerate(tradeoff["frequency"]):
        points = [
            {
                "x": point["shed_mw"],
                "y": point["margin"],
                "name": point["run"],
                "tip": describe_frequency_point(entry["island"], point, source),
                "hollow": point["stopped_early"],
            }
            for point in entry["points"]
        ]
        series.append(build_chart_series(entry["island"], find_series_color(position), points, count <= LABELLED_POINTS))
    return build_chart_options(series, "Frequency margin (Hz)")


def build_voltage_chart(tradeoff):
    """The options of the voltage chart: one series, the runs with voltage security."""
    points = [
        {
            "x": point["shed_mw"],
            "y": point["margin"],
            "name": point["run"],
            "tip": describe_voltage_point(point),
            "hollow": not point["verified"],
        }
        for point in tradeoff["voltage"]
    ]
    series = [build_chart_series("Voltage margin", SERIES_COLORS[0], points, len(points) <= LABELLED_POINTS)]
    return build_chart_options(series, "Voltage margin")


def describe_missing(names, what):
    """A sentence on the runs a chart does not show, or ""."""
    if not names:
        return ""
    return f"Not on this chart, {what}: {', '.join(names)}."


# ==================== The dynamic response ====================
def find_guide(curves, quantity):
    """What the chart's lines come from: the trip and the relays' thresholds of the first run (the runs are of one case), and the latest end of a simulation."""
    first = curves[0]
    return {
        "quantity": quantity,
        "event_time": first["event_time"],
        "end_time": max(curve["end_time"] for curve in curves),
        "relay_thresholds": first["relay_thresholds"],
    }


def build_curves_chart(curves, guide):
    """The options of the chart of the dynamic response: one curve per run in its colour, named in a legend, with the lines of the trip and the relays."""
    digits = dynamics.QUANTITIES[guide["quantity"]]["digits"]
    series = []
    for curve in curves:
        series.append(dynamics.build_curve_series(
            curve["name"], curve["color"], curve["times"], curve["values"], digits, dynamics.MAX_POINTS, width=CURVE_WIDTH
        ))
    return dynamics.build_chart_options(series, guide, show_legend=True)


# ==================== The page ====================
class ComparePage:
    """The Compare page of one browser tab. It is drawn again whenever the list of runs changes."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.compare = ctx.compare
        self.tab = "table"              # the tab on show
        self.source = "simulated"       # where the frequency margin comes from
        self.curve_choice = {"quantity": "frequency", "where": "inside", "bus_text": ""}   # the dynamic response's choices, kept while the runs change
        self.curve_runs = []            # the runs on its chart (comparison.find_curve_runs)
        self.curve_refused = []         # the others, as (name, reason)
        self.curves_started = False     # whether the curves of the runs on show were read
        self.curve_reads = 0            # reads asked for; an older read that ends late is dropped

    def build(self):
        with theme.panel():
            with theme.toolbar():
                theme.eyebrow("Compare")
                self.count = theme.toolbar_text()
                self.clear_button = theme.button("Clear", kind="ghost", on_click=self.compare.clear)

            @ui.refreshable
            def body():
                self._build_body()

            self.body = body
            body()

    def refresh(self):
        self.body.refresh()

    def _build_body(self):
        records = self.compare.records
        count = len(records)
        self.count.text = f"{count} run" + ("" if count == 1 else "s") if count else ""
        self.clear_button.set_enabled(bool(records))
        if not records:
            with ui.element("div").classes("tab-body compare-empty"):
                ui.label("No run to compare yet.")
                for line in HOW_TO:
                    theme.hint(line)
            return
        with ui.tabs(value=self.tab, on_change=self._tab_changed).classes("results-tabs w-full") as tabs:
            for name, label in TAB_LABELS.items():
                ui.tab(name, label=label)
        with ui.tab_panels(tabs, value=self.tab, animated=False).classes("w-full"):
            with ui.tab_panel("table"):
                self._build_table(records)
            with ui.tab_panel("tradeoff"):
                self._build_tradeoff(records)
        if self.tab == "tradeoff":
            self._start_curves()

    def _tab_changed(self, event):
        if event.value:
            self.tab = event.value
        if self.tab == "tradeoff":
            self._start_curves()

    # -------------------- side by side --------------------
    def _build_table(self, records):
        setting_rows, same = comparison.find_setting_rows(records)
        sections = comparison.find_sections(records)
        if setting_rows:
            sections.insert(0, ("Settings" if len(records) == 1 else "Settings that differ", setting_rows))
        columns = f"grid-template-columns: minmax(220px, 320px) repeat({len(records)}, minmax(150px, 280px))"
        with ui.element("div").classes("tab-body"):
            if same:
                theme.hint(f"The same in every run:  {same}")
            elif len(records) > 1 and not setting_rows:
                theme.hint("The runs have the same settings.")
            with ui.element("div").classes("compare-grid").style(columns):
                ui.element("div").classes("compare-corner")
                for record in records:
                    key = comparison.calc_run_key(record)
                    subtitle = comparison.describe_subtitle(record)
                    with ui.element("div").classes("compare-run"):
                        with theme.line():
                            ui.label(comparison.describe_title(record)).classes("compare-run-name grow")
                            theme.button(
                                icon="close", kind="ghost", small=True, on_click=lambda key=key: self.compare.remove(key)
                            )
                        ui.label(subtitle).classes("compare-run-tag").tooltip(subtitle)  # all of a tag that is cut
                ui.html(build_rows_html(sections, len(records)), sanitize=False).classes("compare-rows")

    # -------------------- trade-off --------------------
    def _build_tradeoff(self, records):
        with ui.element("div").classes("tab-body"):
            theme.hint(
                "Each run is one point: what it shed before the event against the margin it kept. A point is "
                "acceptable only above the limit line, in both charts."
            )

            @ui.refreshable
            def charts():
                self._build_charts(records)

            with theme.line():
                theme.label("Frequency from the")
                ui.toggle(SOURCE_LABELS, value=self.source, on_change=lambda event: self._source_changed(event, charts))
            charts()
            self._build_curves(records)

    def _source_changed(self, event, charts):
        if event.value and event.value != self.source:
            self.source = event.value
            charts.refresh()

    def _build_charts(self, records):
        tradeoff = comparison.find_tradeoff(records, self.source)
        with ui.element("div").classes("tradeoff-charts"):
            with ui.element("div").classes("tradeoff-chart"):
                theme.eyebrow("Frequency margin, per island")
                if tradeoff["frequency"]:
                    ui.echart(build_frequency_chart(tradeoff, self.source)).classes("tradeoff-plot")
                else:
                    ui.label(f"No run here has a frequency from the {SOURCE_LABELS[self.source]}.").classes("tradeoff-none")
                if self.source == "simulated":
                    what = "without frequency security or without a simulated frequency (ANDES)"
                else:
                    what = "without frequency security, or kept before the GUI predicted the nadir"
                theme.hint(describe_missing(tradeoff["no_frequency"], what))
                if any(point["stopped_early"] for entry in tradeoff["frequency"] for point in entry["points"]):
                    theme.hint(STOPPED_EARLY_NOTE)
                theme.hint(
                    "How far an island's nadir stays above its limit (the first UFLS stage), or its peak below it."
                )
            with ui.element("div").classes("tradeoff-chart"):
                theme.eyebrow("Voltage margin, predicted")
                if tradeoff["voltage"]:
                    ui.echart(build_voltage_chart(tradeoff)).classes("tradeoff-plot")
                else:
                    ui.label("No run here has voltage security.").classes("tradeoff-none")
                theme.hint(describe_missing(tradeoff["no_voltage"], "without voltage security"))
                if any(not point["verified"] for point in tradeoff["voltage"]):
                    theme.hint(NOT_VERIFIED_NOTE)
                theme.hint(
                    "The indicator threshold minus the worst indicator of the predicted island state. "
                    "It is the optimization's own check, not a result of the simulation."
                )

    # -------------------- the dynamic response --------------------
    def _build_curves(self, records):
        """The section Dynamic response: its choices, then one curve per run on one chart, read once the tab is shown (`_start_curves`)."""
        drawn, not_drawn = comparison.find_curve_runs(records)
        self.curve_runs, self.curve_refused = drawn, not_drawn
        self.curves_started = False
        self.curve_reads += 1           # a read of the runs before is dropped
        self.places = comparison.find_curve_places(comparison.find_shared_target([entry["record"] for entry in drawn]))
        where = self.curve_choice["where"] if self.curve_choice["where"] in self.places else next(iter(self.places))    # the choice stays for later runs
        with ui.element("div").classes("curves-section"):
            theme.eyebrow("Dynamic response")
            if not drawn:
                ui.label("No run here has curves to draw.").classes("tradeoff-none")
                for name, reason in not_drawn:
                    theme.hint(f"Not drawn, {name}: {reason}.")
                return
            with theme.line().classes("dyn-controls"):
                theme.label("Quantity")
                ui.toggle(comparison.CURVE_QUANTITIES, value=self.curve_choice["quantity"], on_change=self._curve_quantity_changed)
                theme.label("Where" if len(self.places) > 1 else "Bus")
                self.curve_where = ui.toggle(self.places, value=where, on_change=self._curve_where_changed)
                self.curve_where.set_visibility(len(self.places) > 1)
                self.curve_bus = ui.input(value=self.curve_choice["bus_text"], placeholder="bus number", on_change=self._curve_bus_changed)
                self.curve_bus.props("debounce=500 clearable").classes("compare-bus")
                self.curve_bus.set_visibility(where == "bus")
            self.curve_note = theme.hint()
            with ui.element("div").classes("curves-chart"):
                self.curve_hovered = ui.label().classes("dyn-hovered dyn-key-line")     # the curve under the cursor
                self.curve_box = ui.element("div").classes("dyn-plot-box")
                self.curve_lines = theme.hint()
                self.curve_cover = theme.Cover()
            self.curve_missing = ui.element("div").classes("curves-missing")

    def _start_curves(self):
        """Read the runs' curves, the first time the Trade-off tab shows them."""
        if self.curves_started or not self.curve_runs:
            return
        self.curves_started = True
        self._read_curves()

    def _read_curves(self):
        self.curve_reads += 1
        background_tasks.create(self._load_curves(self.curve_reads), name="read the runs' curves")

    async def _load_curves(self, read):
        """Read each run's curve off the event loop, one run after another, then draw them on one chart."""
        quantity = self.curve_choice["quantity"]
        where = self.curve_where.value
        bus = None
        if where == "bus":
            text = (self.curve_bus.value or "").strip()
            if not text:
                self._draw_curves([], quantity, "Type a bus number to see its curve in every run.", self.curve_refused)
                return
            try:
                bus = int(text)
            except ValueError:
                self._draw_curves([], quantity, "Bus: type one bus number.", self.curve_refused, bad=True)
                return

        curves, not_drawn, highest_runs, dead = [], list(self.curve_refused), [], False
        for place, entry in enumerate(self.curve_runs):
            self.curve_cover.show(f"Reading the channels of {entry['name']} ({place + 1} of {len(self.curve_runs)}) …")
            summary = entry["record"]["summary"]
            extreme = comparison.find_side_extreme(summary, where, quantity)
            try:
                curve = await run.io_bound(dynamics.load_run_curve, entry["path"], summary["files"], summary, quantity, where, bus, extreme)
                reason = f"no channel at bus {bus}" if where == "bus" else "no bus on that side kept its power"
            except Exception as error:      # a file cut short or not a channel file
                curve, reason = None, f"its channel file could not be read ({error})"
            if read != self.curve_reads or self.curve_box.is_deleted:
                return
            if curve is None:
                not_drawn.append((entry["name"], reason))
                continue
            curves.append(dict(curve, name=entry["name"], color=entry["color"]))
            if extreme == "highest":
                highest_runs.append(entry["name"])
            dead = dead or curve["dead_count"] > 0

        note = ""
        if curves:
            bus_text = f"{bus} {curves[0]['bus_name']}".strip() if where == "bus" else ""
            note = comparison.describe_curves(quantity, where, self.places, bus_text, len(curves), highest_runs, dead)
        self._draw_curves(curves, quantity, note or "No run has a curve for this choice.", not_drawn)

    def _draw_curves(self, curves, quantity, note, not_drawn, bad=False):
        """The chart of `curves` (a new one each time) with `note` above it, or `note` alone without curves, and the runs not drawn under it."""
        self.curve_cover.hide()
        theme.show_hint(self.curve_note, note, bad=bad)
        self.curve_box.clear()
        self.curve_hovered.text = ""
        self.curve_lines.text = ""
        with self.curve_box:
            if curves:
                guide = find_guide(curves, quantity)
                chart = ui.echart(build_curves_chart(curves, guide)).classes("dyn-plot")
                ui.run_javascript(build_script(CHART_JS, chart, self.curve_hovered))
                self.curve_lines.text = " ".join(text for text in (dynamics.describe_lines(guide), ZOOM_NOTE) if text)
            else:
                ui.run_javascript(build_script(CLEAR_JS, None, self.curve_hovered))
        self.curve_missing.clear()
        with self.curve_missing:
            for name, reason in not_drawn:
                theme.hint(f"Not drawn, {name}: {reason}.")

    def _curve_quantity_changed(self, event):
        if event.value is None or event.value == self.curve_choice["quantity"]:
            return
        self.curve_choice["quantity"] = event.value
        self._read_curves()

    def _curve_where_changed(self, event):
        if event.value is None:
            return
        self.curve_choice["where"] = event.value
        self.curve_bus.set_visibility(event.value == "bus")
        self._read_curves()

    def _curve_bus_changed(self, event):
        self.curve_choice["bus_text"] = event.value or ""
        if self.curve_where.value == "bus":
            self._read_curves()


def build(ctx):
    """The Compare page of one browser tab."""
    page = ComparePage(ctx)
    page.build()
    remove = ctx.compare.on_change(page.refresh)
    ui.context.client.on_delete(remove)
