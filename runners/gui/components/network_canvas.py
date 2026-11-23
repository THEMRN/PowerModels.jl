"""
The network drawing of the Network page: buses, lines and group circles on a canvas, with zoom,
pan, a tooltip, clicks and a selection box. The drawing itself is network_canvas.js; this is its
Python side.

It draws what it is given and decides nothing: `network_view.build_graph` makes the `graph` (what
is where) and `network_view.build_look` the `look` (colours, sizes, marks, tooltips).
"""

from nicegui import ui


class NetworkCanvas(ui.element, component="network_canvas.js"):
    """
    The canvas. `on_pick(kind, index, shift, ctrl)` is called for a click on a bus ("node"), a line
    ("link"), a circle ("circle") or nothing ("none"); `on_context(kind, index)` for a right click
    on a bus or a line; `on_box(nodes, links, ctrl)` for a selection box drawn with shift, with the
    indices of the buses and the lines inside it.
    """

    def __init__(self, *, on_pick=None, on_context=None, on_box=None, on_ready=None):
        """`on_ready()` is called once, when the canvas is first shown in the browser."""
        super().__init__()
        if on_ready is not None:
            self.on("ready", lambda _event: on_ready())
        self._props["graph"] = {"key": "", "nodes": [], "links": [], "circles": []}
        self._props["look"] = {}
        if on_pick is not None:
            self.on("pick", lambda event: on_pick(event.args["kind"], event.args["index"], event.args["shift"], event.args["ctrl"]))
        if on_context is not None:
            self.on("context", lambda event: on_context(event.args["kind"], event.args["index"]))
        if on_box is not None:
            self.on("box", lambda event: on_box(event.args["nodes"], event.args["links"], event.args["ctrl"]))

    def show(self, graph, look):
        """Draw a graph with a look. A graph with a new `key` is fitted to the canvas; the same key keeps the view."""
        self._props["graph"] = graph
        self._props["look"] = look
        self.update()

    def show_look(self, look):
        """Change how the graph is drawn, keeping the view."""
        self._props["look"] = look
        self.update()

    def fit(self):
        """Show the whole network."""
        self.run_method("fit")

    def zoom_to(self, node_indices):
        """Show the buses with these indices, with room around them."""
        self.run_method("show", list(node_indices))
