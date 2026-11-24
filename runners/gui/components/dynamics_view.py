"""
The Dynamics tab of the results panel (gui_plan.md, phase 13): the dynamic simulation's curves of
one run, read from its channel file, with their statistics beside them. What it shows is
dynamics.py's business; this module draws it.

The panel builds every tab of a run at once, so this tab reads nothing until it is shown
(`start`). The file is read off the event loop under a cover, and read again when the quantity
changes; Where, Buses and "all buses" work on what was read. The choices are the panel's
(`choice`), so they stay from run to run.

What the chart does under the mouse runs in the browser (`CHART_JS`), because ECharts has none
of it: zooming as Plotly does, naming the curve nearest the cursor, and bringing forward the
curve of a bus whose row of the statistics is under the mouse.
"""

from nicegui import background_tasks, run, ui

import dynamics
import theme
from advanced.where import parse_buses

# ==================== Settings ====================
QUANTITY_LABELS = {quantity: spec["label"] for quantity, spec in dynamics.QUANTITIES.items()}
DEFAULT_CHOICE = {"quantity": "frequency", "where": "all", "buses_text": "", "all_buses": False}
ALL_BUSES_QUANTITIES = ("frequency", "voltage")     # quantities with the "all buses" box
ZOOM_NOTE = "Drag across to zoom the time, up or down to zoom the values, a box to zoom both; a double-click shows the whole chart."
NEAREST_CURVE_PX = 8            # px, how near the cursor a curve has to be to be named
MIN_DRAG_PX = 8                 # px, a drag shorter than this along an axis does not zoom that axis (as Plotly)
# In the browser, for the chart CHART, the name label LABEL and the statistics STATS (NiceGUI ids;
# the chart's last series holds the lines, not a curve):
# - the curve nearest the cursor at its time (within NEAREST_PX) comes forward, the others pale,
#   and its name goes into the label; ECharts names a curve only under an exact hover;
# - a row of the statistics brings its bus's curve forward the same way;
# - a drag zooms as Plotly does: across the time, up or down the values, a box both (a side
#   shorter than MIN_DRAG does not zoom its axis), through the chart's dataZoom 0 (time) and 1
#   (values); a double-click shows the whole chart again.
CHART_JS = """
(async () => {
  let chart = null;
  for (let attempt = 0; attempt < 100 && !chart; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 50));
    chart = getElement(CHART)?.chart;
  }
  const label = document.getElementById('ng-LABEL');      // plain elements: no Vue component to ask
  const stats = document.getElementById('ng-STATS');
  if (!chart || !label) return;
  label.textContent = '';
  const zr = chart.getZr();
  const curves = chart.getOption().series.slice(0, -1);

  // one curve forward (-1: none), the others pale, and its name in the label
  let shown = -1;
  const show = index => {
    if (chart.isDisposed() || index === shown) return;
    if (shown >= 0) chart.dispatchAction({type: 'downplay', seriesIndex: shown});
    if (index >= 0) chart.dispatchAction({type: 'highlight', seriesIndex: index});
    shown = index;
    label.textContent = index >= 0 ? curves[index].name : '';
  };
  const findNearest = (x, y) => {
    const time = chart.convertFromPixel({gridIndex: 0}, [x, y])[0];
    let nearest = -1, nearestDistance = NEAREST_PX;
    curves.forEach((curve, index) => {
      const points = curve.data;
      let low = 0, high = points.length - 1;
      if (high < 1 || time < points[0][0] || time > points[high][0]) return;
      while (high - low > 1) { const middle = (low + high) >> 1; if (points[middle][0] <= time) low = middle; else high = middle; }
      const [t0, v0] = points[low], [t1, v1] = points[high];
      const value = t1 > t0 ? v0 + (v1 - v0) * (time - t0) / (t1 - t0) : v0;
      const distance = Math.abs(chart.convertToPixel({gridIndex: 0}, [time, value])[1] - y);
      if (distance < nearestDistance) { nearestDistance = distance; nearest = index; }
    });
    return nearest;
  };

  // a row of the statistics: its bus's curve forward (the first cell starts with the bus number)
  if (stats) {
    stats.onmouseover = event => {
      const row = event.target.closest('tbody tr');
      const bus = row ? parseInt(row.cells[0].textContent, 10) : NaN;
      show(curves.findIndex(curve => curve.name === 'bus ' + bus || curve.name.startsWith('bus ' + bus + ' ')));
    };
    stats.onmouseleave = () => show(-1);
  }

  // zoom as Plotly: the box being dragged, in the chart's own element
  const dom = chart.getDom();
  const band = document.createElement('div');
  band.className = 'dyn-zoom-box';
  dom.appendChild(band);
  let start = null;
  const findGrid = () => chart.getModel().getComponent('grid', 0).coordinateSystem.getRect();
  const findPoint = event => {
    const rect = dom.getBoundingClientRect(), grid = findGrid();
    const x = Math.min(Math.max(event.clientX - rect.left, grid.x), grid.x + grid.width);
    const y = Math.min(Math.max(event.clientY - rect.top, grid.y), grid.y + grid.height);
    return [x, y];
  };
  const findBox = end => {
    const grid = findGrid();
    const across = Math.abs(end[0] - start[0]) >= MIN_DRAG, upDown = Math.abs(end[1] - start[1]) >= MIN_DRAG;
    const left = across ? Math.min(start[0], end[0]) : grid.x, right = across ? Math.max(start[0], end[0]) : grid.x + grid.width;
    const top = upDown ? Math.min(start[1], end[1]) : grid.y, bottom = upDown ? Math.max(start[1], end[1]) : grid.y + grid.height;
    return {across, upDown, left, right, top, bottom};
  };
  const onMove = event => {
    const box = findBox(findPoint(event));
    band.style.display = box.across || box.upDown ? 'block' : 'none';
    Object.assign(band.style, {left: box.left + 'px', top: box.top + 'px', width: (box.right - box.left) + 'px', height: (box.bottom - box.top) + 'px'});
  };
  const onUp = event => {
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    band.style.display = 'none';
    const box = findBox(findPoint(event));
    start = null;
    if (chart.isDisposed()) return;
    const [t0, v0] = chart.convertFromPixel({gridIndex: 0}, [box.left, box.bottom]);
    const [t1, v1] = chart.convertFromPixel({gridIndex: 0}, [box.right, box.top]);
    if (box.across) chart.dispatchAction({type: 'dataZoom', dataZoomIndex: 0, startValue: t0, endValue: t1});
    if (box.upDown) chart.dispatchAction({type: 'dataZoom', dataZoomIndex: 1, startValue: v0, endValue: v1});
  };
  zr.on('mousedown', event => {
    if (event.event.button !== 0 || !chart.containPixel({gridIndex: 0}, [event.offsetX, event.offsetY])) return;
    // no text selected on the page while dragging; ECharts listens to pointer events, and a
    // prevented pointerdown fires no mouse events after it, so the drag follows pointer events
    event.event.preventDefault();
    start = [event.offsetX, event.offsetY];
    show(-1);
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  });
  zr.on('dblclick', () => {
    chart.dispatchAction({type: 'dataZoom', dataZoomIndex: 0, start: 0, end: 100});
    chart.dispatchAction({type: 'dataZoom', dataZoomIndex: 1, start: 0, end: 100});
  });
  zr.on('mousemove', event => { if (!start) show(findNearest(event.offsetX, event.offsetY)); });
  zr.on('globalout', () => show(-1));
})();
"""
# In the browser, when a drawing has no chart: no name left in the label, no row bound to an old chart
CLEAR_JS = """
(() => {
  const label = document.getElementById('ng-LABEL');
  if (label) label.textContent = '';
  const stats = document.getElementById('ng-STATS');
  if (stats) { stats.onmouseover = null; stats.onmouseleave = null; }
})();
"""


def build_script(script, chart, label, stats):
    """A script above with the NiceGUI ids of the chart, the name label and the statistics, and its settings, filled in."""
    replacements = {
        "CHART": str(chart.id) if chart is not None else "",
        "LABEL": str(label.id),
        "STATS": str(stats.id),
        "NEAREST_PX": str(NEAREST_CURVE_PX),
        "MIN_DRAG": str(MIN_DRAG_PX),
    }
    for name, value in replacements.items():
        script = script.replace(name, value)
    return script


def find_default_choice():
    """A fresh copy of the choices the tab starts with."""
    return dict(DEFAULT_CHOICE)


class DynamicsView:
    """
    The Dynamics tab of one run. `start()` reads its channel file the first time the tab is
    shown; it does nothing for a run without curves, which shows a sentence instead.
    """

    def __init__(self, record, choice, running, open_report):
        self.summary = record["summary"]
        self.files = self.summary["files"]
        self.target = self.summary.get("target")
        self.sides = dynamics.find_sides(self.target)
        self.choice = choice
        self.path = None
        self.data = None            # what was read for the quantity on show
        self.started = False
        self.reads = 0              # reads asked for; an older read that ends late is dropped
        self.draws = 0              # drawings asked for, the same way
        self.chart = None           # the chart on show

        with ui.element("div").classes("tab-body"):
            missing, waiting = dynamics.describe_missing(self.summary, record["settings"], running)
            if missing is None:
                self.path, missing = dynamics.find_channel_file(self.files)
            if self.path is None:
                theme.show_hint(theme.hint(), missing, waiting=waiting)
                if self.files.get("report"):
                    with theme.line():
                        theme.button("Open report", on_click=open_report)
                return

            with theme.line().classes("dyn-controls"):
                theme.label("Quantity")
                self.quantity = ui.select(QUANTITY_LABELS, value=choice["quantity"], on_change=self._quantity_changed)
                self.where_label = theme.label("Where")
                where = choice["where"] if choice["where"] in self.sides else "all"
                self.where = ui.toggle(self.sides, value=where, on_change=self._where_changed)
                for element in (self.where_label, self.where):
                    element.set_visibility(len(self.sides) > 1)
                theme.label("Buses")
                self.buses = ui.input(value=choice["buses_text"], placeholder="all, or bus numbers", on_change=self._buses_changed)
                self.buses.props("debounce=500 clearable").classes("dyn-buses")
                self.all_buses = ui.checkbox("all buses", value=choice["all_buses"], on_change=self._all_buses_changed)
            self.notes = theme.hint()
            with ui.element("div").classes("dyn-body"):
                with ui.element("div").classes("dyn-chart"):
                    with theme.line().classes("dyn-key-line"):
                        self.key = ui.html("", sanitize=False).classes("dyn-key grow")     # names escaped by build_key_html
                        self.hovered = ui.label().classes("dyn-hovered")                 # the curve under the cursor
                    self.chart_box = ui.element("div").classes("dyn-plot-box")
                    self.lines_note = theme.hint()
                    self.cover = theme.Cover()
                self.stats_box = ui.element("div").classes("dyn-stats")
        self._show_all_buses_box()

    # -------------------- reading --------------------
    def start(self):
        """Read the channel file, the first time the tab is shown."""
        if self.started or self.path is None:
            return
        self.started = True
        self._read()

    def _read(self):
        self.reads += 1
        self.data = None
        self.cover.show("Reading the simulation's channels …")
        background_tasks.create(self._load(self.reads), name="read the simulation's channels")

    async def _load(self, read):
        quantity = self.choice["quantity"]
        try:
            data = await run.io_bound(dynamics.load_dynamics, self.path, quantity, self.files, self.summary)
        except Exception as error:      # a file cut short or not a channel file: say so in place of the chart
            if read == self.reads and not self.chart_box.is_deleted:
                self.cover.hide()
                theme.show_hint(self.notes, f"The channel file could not be read: {error}", bad=True)
            return
        if read != self.reads or self.chart_box.is_deleted:
            return
        self.data = data
        await self._draw()

    # -------------------- drawing --------------------
    async def _draw(self):
        """Draw the chart and the statistics of the choices on what was read."""
        if self.data is None:
            return
        try:
            picked_buses = parse_buses(self.buses.value)
        except ValueError as error:
            self.cover.hide()
            theme.show_hint(self.notes, f"Buses: {error}", bad=True)
            return
        self.draws += 1
        draw = self.draws
        self.cover.show("Drawing the curves …")
        view = await run.io_bound(
            dynamics.build_view, self.data, self.target, self.where.value, picked_buses, self.choice["all_buses"]
        )
        if draw != self.draws or self.chart_box.is_deleted:
            return
        self.cover.hide()
        theme.show_hint(self.notes, " ".join(view["notes"]))
        self.key.content = dynamics.build_key_html(view["key"])
        self.chart_box.clear()      # a new chart each time: ECharts would merge the old curves into new options of the same count
        self.chart = None
        self.hovered.text = ""
        with self.chart_box:
            if view["chart"] is None:
                theme.hint("No curve to draw for this choice.")
                ui.run_javascript(build_script(CLEAR_JS, None, self.hovered, self.stats_box))
            else:
                self.chart = ui.echart(view["chart"]).classes("dyn-plot")
                ui.run_javascript(build_script(CHART_JS, self.chart, self.hovered, self.stats_box))
        notes = [dynamics.describe_lines(self.data), ZOOM_NOTE if view["chart"] else ""]
        self.lines_note.text = " ".join(note for note in notes if note)
        self._draw_stats(view)

    def _draw_stats(self, view):
        """The statistics of the chosen side beside the chart: frequency and voltage only."""
        self.stats_box.clear()
        stats = view["stats"]
        quantity = self.data["quantity"]
        self.stats_box.set_visibility(quantity in ("frequency", "voltage"))
        if quantity not in ("frequency", "voltage"):
            return
        with self.stats_box:
            theme.eyebrow(f"Statistics · {view['side']}")
            if stats is None:
                theme.hint("No bus on this side has a curve after the trip.")
                return
            if quantity == "frequency":
                with theme.facts():
                    for name, text in dynamics.find_frequency_facts(stats):
                        theme.fact(name, text)
                theme.eyebrow("Furthest from 60 Hz")
                theme.data_table(*dynamics.find_frequency_table(stats))
                theme.hint("From the trip on, as the Frequency tab's simulated nadir. A row under the mouse brings its bus's curve forward.")
                return
            with theme.facts():
                for name, text in dynamics.find_voltage_facts(stats):
                    theme.fact(name, text)
            if stats["top"]:
                theme.eyebrow("Furthest outside 0.9–1.1 pu")
                theme.data_table(*dynamics.find_voltage_table(stats))
            if stats["wtvsi_top"]:
                theme.eyebrow("Largest parts of WTVSI")
                theme.data_table(*dynamics.find_wtvsi_table(stats))
            theme.hint(
                "Over the whole simulation, as voltage_stats.json and the report have them. "
                "A row under the mouse brings its bus's curve forward."
            )

    # -------------------- the choices --------------------
    def _show_all_buses_box(self):
        self.all_buses.set_visibility(self.choice["quantity"] in ALL_BUSES_QUANTITIES and not self.buses.value)

    def _quantity_changed(self, event):
        if event.value is None or event.value == self.choice["quantity"]:
            return
        self.choice["quantity"] = event.value
        self._show_all_buses_box()
        if self.started:
            self._read()

    def _where_changed(self, event):
        if event.value is None:
            return
        self.choice["where"] = event.value
        background_tasks.create(self._draw(), name="draw the curves")

    def _buses_changed(self, event):
        self.choice["buses_text"] = event.value or ""
        self._show_all_buses_box()
        background_tasks.create(self._draw(), name="draw the curves")

    def _all_buses_changed(self, event):
        self.choice["all_buses"] = bool(event.value)
        background_tasks.create(self._draw(), name="draw the curves")
