"""
Network page: the network of a case as a graph. The buses of a zone or an area stand together in
a circle; buses, lines and circles can be coloured by what the case holds or by what a run of the
session found; and a zone or an area, a set of buses or a set of lines can be selected, to see
its boundary and to send it to the Run form as the target or with a penalty.

The network comes from Julia (the `network` job) with its layout, when the page is first shown, and is kept for the session in
`ctx.state["networks"]`. While it comes, a cover over the drawing says what the page waits for. What is shown is worked out in
`network_view.py`, which draws nothing; `components/network_canvas` draws it.
"""

from pathlib import Path

from nicegui import background_tasks, ui

import network_view
import theme
from advanced.where import format_buses, parse_buses
from components.network_canvas import NetworkCanvas
from julia_worker import JobError, WorkerError
from settings import GROUP_KINDS, format_bus_pairs, parse_bus_pairs

# ==================== Settings ====================
TITLE = "Network"
KIND_LABELS = {"zone": "Zone", "area": "Area"}
MODE_LABELS = {"group": "Group", "buses": "Buses", "lines": "Lines"}
CASE_SOURCE = "case"            # the value of "Values of" for the case as it was read
HOW_TO = (
    "Wheel to zoom, drag to move, double click for the whole network.",
    "Click to select: a circle or a bus for its zone or area, single buses, or lines.",
    "Shift and drag selects the buses or the lines in a box (with Ctrl it removes them).",
    "A square is a bus with a generator. Zoom in for the bus numbers.",
)


class NetworkPage:
    """The Network page of one browser tab: what it shows (case, kind of group, colours, values) and what is selected."""

    def __init__(self, ctx, client_state):
        self.ctx = ctx
        self.client_state = client_state    # of this browser tab: the Run form, the function that shows a page
        self.network = None                 # network_view.Network of the case shown
        self.loading = None                 # case being read
        self.unanswered = None              # case whose network Julia did not give (it stopped first): read again once it is back
        self.kind = None                    # kind of group shown: "zone", "area", or None for a case without groups
        self.mode = "group"                 # what a click selects: "group", "buses" or "lines"
        self.group = None                   # index of the selected zone or area
        self.buses = []                     # selected bus numbers, in the order chosen
        self.lines = []                     # indices of the selected lines
        self.updating = False               # the page is setting its own controls: their handlers stay quiet

    # -------------------- layout --------------------
    def build(self):
        with theme.panel().classes("network-panel"):
            with theme.toolbar().classes("network-bar"):
                theme.label("Case")
                self.case = ui.select({}, on_change=self._case_changed).classes("field-case")
                self.kind_label = theme.label("Group by")
                self.kind_toggle = ui.toggle(dict(KIND_LABELS), on_change=self._kind_changed)
                theme.label("Buses")
                self.color_buses = ui.select({}, on_change=self._look_changed).classes("field-color")
                theme.label("Lines")
                self.color_lines = ui.select({}, on_change=self._look_changed).classes("field-color")
                theme.label("Circles")
                self.color_circles = ui.select({}, on_change=self._look_changed).classes("field-color")
                self.source_label = theme.label("Values of")
                self.source = ui.select({}, on_change=self._source_changed).classes("field-source")
                self.message = theme.toolbar_text()
                self.fit_button = theme.button("Fit", kind="ghost", on_click=lambda: self.canvas.fit()).tooltip("Show the whole network")
                theme.button(icon="refresh", kind="ghost", on_click=self.reload, busy=True).tooltip("Read this case's network from Julia again")
                theme.help_mark(HOW_TO)
            with ui.element("div").classes("network-body"):
                self.canvas = NetworkCanvas(on_pick=self._picked, on_box=self._boxed, on_ready=self._first_shown)
                self.cover = theme.Cover()
                with ui.element("div").classes("network-side"):
                    with ui.element("div").classes("network-selection") as self.selection_box:
                        self._build_selection()
                    theme.eyebrow("Legend")
                    self.legend = ui.element("div").classes("network-legend")
        with theme.offstage():
            self.timer = ui.timer(0.5, self._load_cases, active=False)
        # what greys out while the page waits: the choices of what to show, and the selection ("How to use" stays readable)
        self.waiting_parts = [self.kind_toggle, self.color_buses, self.color_lines, self.color_circles, self.source, self.fit_button, self.selection_box]
        self.kind_label.set_visibility(False)       # until a case says whether it has zones or areas
        self.kind_toggle.set_visibility(False)
        self._show_selection()
        self._show_wait()

    def _build_selection(self):
        theme.eyebrow("Selection")
        self.mode_toggle = ui.toggle(dict(MODE_LABELS), value=self.mode, on_change=self._mode_changed)
        self.group_select = ui.select({}, with_input=True, clearable=True, on_change=self._group_chosen).classes("w-full")
        self.buses_text = ui.input(placeholder="3005, 3007, 3008").classes("w-full")
        self.buses_text.on("change", self._buses_typed)
        self.lines_text = ui.input(placeholder="154-3008, 152-153").classes("w-full")
        self.lines_text.on("change", self._lines_typed)
        self.selection_problem = theme.hint()
        self.facts = theme.facts()
        self.target_hint = theme.hint()
        with theme.line():
            self.target_button = theme.button("Use as target", kind="primary", on_click=self._use_as_target, busy=True)
            with self.target_button:
                self.target_tooltip = ui.tooltip()      # what the button does with this selection
            self.zoom_button = theme.button("Zoom to it", kind="ghost", on_click=self._zoom_to_selection)
            self.clear_button = theme.button("Clear", kind="ghost", on_click=self._clear_selection)
        with theme.line():
            self.penalty_value = ui.number(placeholder="× λ", min=0).classes("field-penalty")
            self.penalty_button = theme.button("Set penalty", on_click=self._set_penalty, busy=True)
            with self.penalty_button:
                self.penalty_tooltip = ui.tooltip()

    # -------------------- reading from Julia --------------------
    def _first_shown(self):
        """
        The page is shown for the first time in this browser tab: only now is its network asked
        for, so that an app whose Network page is never opened does not keep Julia busy with it.
        """
        if self.network is None and self.loading is None:
            self.timer.activate()
            self._load_cases()              # at once when the case list is there; else the timer looks again

    def _load_cases(self):
        """Take the case list the Run page read; it is there once Julia answered."""
        cases = self.ctx.state.get("cases")
        if not cases:
            self._show_wait()
            return
        self.timer.deactivate()
        form = self.client_state.get("run_form")
        first = form.loaded_case if form is not None and form.loaded_case in cases else cases[0]
        self.updating = True
        self.case.set_options({case: Path(case).name for case in cases}, value=first)
        self.updating = False
        background_tasks.create(self._show_case(first), name="network")

    async def _find_network(self, case):
        """(reply, error message) of the `network` job for a case, from the session's cache or from Julia."""
        cache = self.ctx.state.setdefault("networks", {})
        if case in cache:
            return cache[case]
        try:
            cache[case] = (await self.ctx.worker.request({"type": "network", "case": case}), "")
        except JobError as error:           # Julia could not read the case: that stays true until the file changes
            cache[case] = (None, str(error))
        except WorkerError as error:        # Julia is not running: ask again next time
            return None, f"Julia did not answer: {error}"
        return cache[case]

    async def _show_case(self, case):
        """Read a case's network and show it, with nothing selected."""
        self.loading = case
        self.unanswered = None
        self._show_message("")
        self._show_wait()
        reply, error = await self._find_network(case)
        if case != self.loading:            # another case was chosen meanwhile
            return
        self.loading = None
        if case not in self.ctx.state.get("networks", {}) and self.ctx.worker.state in ("stopped", "crashed", "starting"):
            self.unanswered = case          # Julia stopped first (Stop, Restart Julia): read it again once Julia is back
        self._show_wait()
        self.group, self.buses, self.lines = None, [], []
        if reply is None:
            self.network = None
            if self.unanswered is None:
                self._show_message(f"the case could not be read: {error}", bad=True)
            self.canvas.show({"key": f"{case}|empty", "nodes": [], "links": [], "circles": []}, {})
            self._show_controls()
            self._show_selection()
            return
        self.network = network_view.Network(reply)
        if self.kind not in self.network.kinds:
            self.kind = self.network.kinds[0] if self.network.kinds else None
        if self.kind is None and self.mode == "group":
            self.mode = "buses"
        self._show_message(f"{len(self.network.buses)} buses, {len(self.network.lines)} lines")
        self._show_controls()
        self._show(new_graph=True)

    async def reload(self):
        """Forget what Julia said about this case and ask again."""
        case = self.case.value
        if case is None:
            return
        self.ctx.state.get("networks", {}).pop(case, None)
        await self._show_case(case)

    # -------------------- the controls --------------------
    def _find_record(self):
        """The run whose values are shown, or None for the case as read."""
        if self.source.value in (None, CASE_SOURCE):
            return None
        for record in self.ctx.runs.records:
            if record["number"] == self.source.value:
                return record
        return None

    def _find_sources(self):
        """What "Values of" offers: the case as read, and the session's runs of this case that have results."""
        sources = {CASE_SOURCE: "the case as read"}
        for record in reversed(self.ctx.runs.records):
            run_settings = record["settings"]
            if self.network is None or run_settings["case"] != self.network.case or network_view.find_run_network(record) is None:
                continue
            tag = f" · {run_settings['output_tag']}" if run_settings["output_tag"] else ""
            sources[record["number"]] = f"run {record['number']} · {run_settings['objective']}{tag} · {record['started']}"
        return sources

    def _show_controls(self):
        """Offer what this case, this kind of group and these values allow, keeping the choices that still fit."""
        self.updating = True
        try:
            kinds = {kind: KIND_LABELS[kind] for kind in (self.network.kinds if self.network else [])}
            self.kind_toggle.set_options(kinds, value=self.kind if self.kind in kinds else None)
            self.kind_toggle.set_visibility(len(kinds) > 0)
            self.kind_label.set_visibility(len(kinds) > 0)

            sources = self._find_sources()
            self.source.set_options(sources, value=self.source.value if self.source.value in sources else CASE_SOURCE)
            record = self._find_record()
            with_shed = record is not None and record["summary"].get("load_shed") is not None

            def offer(select, first, values):
                options = dict(first)
                options.update({key: label for key, (label, _, _) in values.items() if key not in network_view.RUN_ONLY or with_shed})
                select.set_options(options, value=select.value if select.value in options else next(iter(options)))

            group_label = f"{KIND_LABELS[self.kind]}" if self.kind else "One colour"
            offer(self.color_buses, {"group": group_label}, network_view.BUS_VALUES)
            offer(self.color_lines, {"none": "Plain"}, network_view.LINE_VALUES)
            offer(self.color_circles, {"group": group_label}, network_view.GROUP_VALUES if self.kind else {})
            self.color_circles.set_enabled(self.kind is not None)

            modes = {mode: (KIND_LABELS[self.kind] if mode == "group" else label) for mode, label in MODE_LABELS.items() if mode != "group" or self.kind}
            self.mode_toggle.set_options(modes, value=self.mode if self.mode in modes else next(iter(modes)))
            self.mode = self.mode_toggle.value
            groups = self.network.find_groups(self.kind) if self.network and self.kind else []
            self.group_select.set_options({index: f"{name}  ({count} buses)" for index, name, count in groups},
                                          value=self.group if self.group in [index for index, _, _ in groups] else None)
        finally:
            self.updating = False

    def _case_changed(self, event):
        if self.updating or event.value is None:
            return
        background_tasks.create(self._show_case(event.value), name="network")

    def _kind_changed(self, event):
        if self.updating or event.value is None or event.value == self.kind:
            return
        self.kind = event.value
        self.group = None
        self._show_controls()
        self._show(new_graph=True)

    def _source_changed(self, event):
        if self.updating:
            return
        record = self._find_record()
        if record is not None and self.network is not None:        # a run is reported by its own kind of group (decision 11)
            run_kind = (record["summary"].get("generation") or {}).get("group_kind")
            if run_kind in self.network.kinds and run_kind != self.kind:
                self.kind = run_kind
                self.group = None
                self._show_controls()
                self._show(new_graph=True)
                return
        self._show_controls()
        self._show()

    def _look_changed(self, _event=None):
        if not self.updating:
            self._show()

    def runs_changed(self):
        """A run started or ended: it may be one more to take values from, and a network that waits for it says so."""
        if self.network is not None:
            self._show_controls()
        self._show_wait()

    def julia_changed(self, state, _message=""):
        """Julia's state changed: say what the page waits for now, and ask again for a network Julia did not give."""
        if state == "ready" and self.unanswered is not None and self.loading is None and self.unanswered == self.case.value:
            background_tasks.create(self._show_case(self.unanswered), name="network")
        self._show_wait()

    # -------------------- waiting for Julia --------------------
    def _describe_wait(self):
        """What the page waits for, as the cover says it; "" when it waits for nothing that will come."""
        worker = self.ctx.worker
        if worker.state in ("stopped", "crashed"):
            return ""                       # nothing comes until Julia is restarted: the message says so
        case = self.loading or self.unanswered
        if case is None:
            return "Waiting for Julia's case list..." if self.network is None and not self.ctx.state.get("cases") else ""
        name = Path(case).name
        if worker.state == "starting":
            return f"Waiting for Julia to start, then reading the network of {name}..."
        running = self.ctx.runs.find_running()
        if running is not None:
            return f"Julia is busy with run {running['number']}. The network of {name} is read when the run ends."
        if "network" not in worker.answered_types:
            return f"Reading the network of {name} and placing its buses. The first network after Julia starts takes about 20 s."
        return f"Reading the network of {name} and placing its buses..."

    def _show_wait(self):
        """The cover over the drawing says what the page waits for, and the controls grey out meanwhile."""
        text = self._describe_wait()
        if text:
            self.cover.show(text)
        else:
            self.cover.hide()
        theme.grey_out(self.waiting_parts, bool(text))
        if self.unanswered is not None and not text:        # Julia stopped and is not coming back by itself
            self._show_message(f"Julia is not running: Restart Julia to read the network of {Path(self.unanswered).name}", bad=True)
        elif self.unanswered is not None:
            self._show_message("")

    def _show_message(self, text, bad=False):
        """The text at the end of the toolbar: the size of the network, or why there is none (in red)."""
        self.message.text = text
        self.message.classes(replace="toolbar-text bad" if bad else "toolbar-text")

    # -------------------- what is shown --------------------
    def _find_selected_buses(self):
        """Bus numbers the selection stands for: the group's buses, or the buses chosen; empty for lines."""
        if self.network is None:
            return set()
        if self.mode == "group" and self.group is not None:
            return self.network.find_group_buses(self.kind, self.group)
        if self.mode == "buses":
            return set(self.buses)
        return set()

    def _find_boundary(self):
        """Indices of the lines the selection would open: the boundary of its buses, or the lines chosen."""
        if self.network is None:
            return []
        if self.mode == "lines":
            return list(self.lines)
        buses = self._find_selected_buses()
        return network_view.find_boundary(self.network, buses) if buses else []

    def _find_marked_buses(self):
        """Buses that get a ring: those chosen, or the buses of the selected group that stand outside its circles."""
        if self.network is None or self.mode == "lines":
            return set()
        if self.mode == "buses":
            return set(self.buses)
        if self.group is None:
            return set()
        layout = self.network.find_layout(self.kind)
        marked = set()
        for place, bus in enumerate(self.network.buses):
            if bus[self.kind] == self.group and layout["circles"][layout["circle_of_bus"][place] - 1]["group"] != self.group:
                marked.add(bus["bus"])
        return marked

    def _show(self, new_graph=False):
        """Draw the network with the colours and the selection of now, and say what is selected."""
        if self.network is None:
            return
        record = self._find_record()
        self.bus_values = network_view.find_bus_values(self.network, record)
        self.line_values = network_view.find_line_values(self.network, record)
        look, legend = network_view.build_look(
            self.network, self.kind, self.bus_values, self.line_values,
            color_buses=self.color_buses.value or "group", color_lines=self.color_lines.value or "none",
            color_circles=self.color_circles.value or "group",
            selected_buses=self._find_marked_buses(), selected_lines=self._find_boundary(),
            selected_group=self.group if self.mode == "group" else None,
        )
        if new_graph:
            self.canvas.show(network_view.build_graph(self.network, self.kind), look)
        else:
            self.canvas.show_look(look)
        self._show_legend(legend)
        self._show_selection()

    def _show_legend(self, legend):
        self.legend.clear()
        with self.legend:
            for entry in legend:
                if "title" in entry:
                    ui.label(entry["title"]).classes("legend-title")
                elif "ramp" in entry:
                    with ui.element("div").classes("legend-scale"):
                        ui.element("div").classes("legend-ramp").style(f"background: linear-gradient(to right, {', '.join(entry['ramp'])})")
                        with ui.element("div").classes("legend-ends"):
                            ui.label(entry["low"])
                            ui.label(entry.get("middle", ""))
                            ui.label(entry["high"])
                elif "color" in entry:
                    row = ui.element("div").classes("legend-row")
                    with row:
                        ui.element("span").classes("legend-chip").style(f"background: {entry['color']}")
                        ui.label(entry["text"])
                    if "group" in entry:
                        row.classes("clickable")
                        row.on("click", lambda _, index=entry["group"]: self._select_group(index))
                else:
                    theme.hint(entry["note"])

    def _show_selection(self):
        """The side panel: the field of the mode, the facts of the selection, and what the buttons would do."""
        self.updating = True
        try:
            self.group_select.set_visibility(self.mode == "group")
            self.buses_text.set_visibility(self.mode == "buses")
            self.lines_text.set_visibility(self.mode == "lines")
            if self.mode == "group":
                self.group_select.set_value(self.group)
            elif self.mode == "buses":
                self.buses_text.set_value(format_buses(self.buses))
            elif self.network is not None:
                self.lines_text.set_value(format_bus_pairs([[self.network.lines[index]["from"], self.network.lines[index]["to"]] for index in self.lines]))
        finally:
            self.updating = False

        buses = self._find_selected_buses()
        boundary = self._find_boundary()
        self.facts.clear()
        with self.facts:
            if self.network is not None:
                for name, text in network_view.calc_selection_facts(self.network, self.bus_values, self.line_values, buses, boundary):
                    theme.fact(name, text)

        has_selection = bool(buses or boundary)
        self.target_button.set_enabled(bool(boundary))
        self.zoom_button.set_enabled(has_selection)
        self.clear_button.set_enabled(has_selection)
        can_penalize = self.mode != "lines" and bool(buses)
        self.penalty_value.set_enabled(can_penalize)
        self.penalty_button.set_enabled(can_penalize)
        # what the two buttons would do goes in their tooltips; only the empty selection gets a line of its own
        hint, target_tip, penalty_tip = "", "", ""
        if self.network is None:
            pass
        elif not has_selection:
            what = {"group": f"a circle or a bus for its {self.kind}", "buses": "buses", "lines": "lines"}[self.mode]
            hint = f"Nothing is selected. Click {what}, or type them above." if self.mode != "group" else f"Nothing is selected. Click {what}, or choose it above."
            target_tip = "Select a zone or an area, buses or lines first"
            penalty_tip = "Select a zone or an area, or buses, first"
        elif self.mode == "group":
            name = self.network.find_group_name(self.kind, self.group)
            target_tip = f"The Run form gets {self.kind} {name} as its boundary, the lines drawn in red"
            penalty_tip = f"A load shedding penalty for {self.kind} {name}, in multiples of λ"
        elif self.mode == "buses":
            target_tip = f"The Run form gets the {len(boundary)} bus pairs around these buses as its boundary"
            penalty_tip = "A load shedding penalty for each of these buses that has a load, in multiples of λ"
        else:
            target_tip = f"The Run form gets these {len(boundary)} bus pairs as its boundary"
            penalty_tip = "A penalty is for loads: select a zone or an area, or buses"
        self.target_hint.text = hint
        for tooltip, text in ((self.target_tooltip, target_tip), (self.penalty_tooltip, penalty_tip)):
            tooltip.text = text
            tooltip.set_visibility(bool(text))

    # -------------------- selecting --------------------
    def _set_problem(self, text=""):
        theme.show_hint(self.selection_problem, text, bad=True)

    def _mode_changed(self, event):
        if self.updating or event.value is None:
            return
        self.mode = event.value
        self._set_problem()
        self._show()

    def _select_group(self, index):
        if self.kind is None:
            return
        self.mode = "group"
        self.group = index
        self._set_problem()
        self._show_controls()
        self._show()

    def _group_chosen(self, event):
        if self.updating:
            return
        self.group = event.value
        self._show()

    def _buses_typed(self, _event=None):
        if self.updating or self.network is None:
            return
        try:
            buses = parse_buses(self.buses_text.value)
        except ValueError as error:
            self._set_problem(str(error))
            return
        unknown = [bus for bus in buses if bus not in self.network.index_of_bus]
        self._set_problem(f"not in the case: {format_buses(unknown)}" if unknown else "")
        self.buses = [bus for bus in buses if bus in self.network.index_of_bus]
        self._show()

    def _lines_typed(self, _event=None):
        if self.updating or self.network is None:
            return
        try:
            pairs = parse_bus_pairs(self.lines_text.value)
        except ValueError as error:
            self._set_problem(str(error))
            return
        lines, unknown = [], []
        for first, second in pairs:
            index = self.network.index_of_pair.get((min(first, second), max(first, second)))
            if index is None:
                unknown.append([first, second])
            elif index not in lines:
                lines.append(index)
        self._set_problem(f"no line between: {format_bus_pairs(unknown)}" if unknown else "")
        self.lines = lines
        self._show()

    def _toggle(self, chosen, items, remove=False):
        """Add the items to a list of chosen ones, or take them out; one item that is there goes out."""
        if remove or (len(items) == 1 and items[0] in chosen):
            return [item for item in chosen if item not in items]
        return chosen + [item for item in items if item not in chosen]

    def _picked(self, kind, index, _shift, _ctrl):
        """A click on the canvas: on a bus ("node"), a line ("link"), a circle or nothing."""
        if self.network is None:
            return
        self._set_problem()
        if self.mode == "group":
            if kind == "node":
                self.group = self.network.buses[index][self.kind]
            elif kind == "circle":
                self.group = self.network.find_layout(self.kind)["circles"][index]["group"]
            elif kind == "none":
                self.group = None
            else:
                return
        elif self.mode == "buses":
            if kind == "node":
                self.buses = self._toggle(self.buses, [self.network.buses[index]["bus"]])
            else:
                return
        elif kind == "link":
            self.lines = self._toggle(self.lines, [index])
        else:
            return
        self._show()

    def _boxed(self, nodes, links, ctrl):
        """A selection box: its buses or its lines join the selection, or leave it with Ctrl."""
        if self.network is None or self.mode == "group":
            return
        if self.mode == "buses":
            self.buses = self._toggle(self.buses, [self.network.buses[index]["bus"] for index in nodes], remove=ctrl)
        else:
            self.lines = self._toggle(self.lines, list(links), remove=ctrl)
        self._show()

    def _clear_selection(self):
        self.group, self.buses, self.lines = None, [], []
        self._set_problem()
        self._show()

    def _zoom_to_selection(self):
        buses = self._find_selected_buses()
        for index in self._find_boundary():
            buses |= {self.network.lines[index]["from"], self.network.lines[index]["to"]}
        self.canvas.zoom_to([self.network.index_of_bus[bus] for bus in buses])

    # -------------------- to the Run form --------------------
    async def _send_to_run(self, boundary=None, penalty_rows=()):
        """Give the Run form of this browser tab a boundary or penalty rows for this case, and show the Run page."""
        form = self.client_state.get("run_form")
        if form is None or not form.cases_loaded:
            ui.notify("The Run form is not ready yet.", position="top")
            return
        running = self.ctx.runs.find_running()
        if running is not None and self.network.case not in self.ctx.state.get("case_infos", {}):
            ui.notify(f"Julia is busy with run {running['number']}: the Run form gets this when it has read the case, after the run.", position="top")
        refused, notes = await form.take(self.network.case, boundary=boundary, penalty_rows=penalty_rows)
        if refused:
            ui.notify(refused, position="top", type="warning")
            return
        self.client_state["show_page"]("Run")
        what = "The boundary is" if boundary is not None else "The penalty is"
        ui.notify(" ".join([f"{what} in the Run form."] + notes), position="top")

    async def _use_as_target(self):
        boundary_lines = self._find_boundary()
        if not boundary_lines:
            return
        if self.mode == "group":
            boundary = {"kind": self.kind, "name": self.network.find_group_name(self.kind, self.group), "bus_pairs": []}
        else:
            pairs = [[self.network.lines[index]["from"], self.network.lines[index]["to"]] for index in boundary_lines]
            boundary = {"kind": "bus_pairs", "name": "", "bus_pairs": pairs}
        await self._send_to_run(boundary=boundary)

    async def _set_penalty(self):
        times_lambda = self.penalty_value.value
        if times_lambda is None:
            ui.notify("Type the penalty first, in multiples of λ.", position="top")
            return
        if self.mode == "group":
            rows = [{"kind": self.kind, "name": self.network.find_group_name(self.kind, self.group), "times_lambda": times_lambda}]
        else:
            with_load = [bus["bus"] for bus in self.network.buses if bus["bus"] in set(self.buses) and bus["pd_mw"]]
            if not with_load:
                ui.notify("None of these buses has a load.", position="top")
                return
            rows = [{"kind": "bus", "name": bus, "times_lambda": times_lambda} for bus in with_load]
        await self._send_to_run(penalty_rows=rows)


def build(ctx):
    """The Network page of one browser tab."""
    page = NetworkPage(ctx, ctx.client_state())
    page.build()
    removers = [ctx.runs.on_change(page.runs_changed), ctx.worker.on_state(page.julia_changed)]
    ui.context.client.on_delete(lambda: [remove() for remove in removers])
