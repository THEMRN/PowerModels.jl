"""
A table of rows to choose from, sorted by a click on a column title and with one row selected:
the History page's runs. The table is sortable_table.js; this is its Python side.

It is one element for the whole table, so a few hundred rows stay quick, and it has the look of
`theme.data_table`.
"""

from nicegui import ui


class SortableTable(ui.element, component="sortable_table.js"):
    """
    `columns`: [{"key", "label", "numeric", "wide"}]; `order`: {"key", "descending"}, the first
    sorting; `on_select(id)` is called when a row is chosen by a click or the arrow keys.
    Rows are given to `show`.
    """

    def __init__(self, columns, *, order=None, empty="Nothing to show.", on_select=None):
        super().__init__()
        self._props["columns"] = columns
        self._props["rows"] = []
        self._props["selected"] = None
        self._props["order"] = order or {}
        self._props["empty"] = empty
        if on_select is not None:
            self.on("select", lambda event: on_select(event.args))

    def show(self, rows, selected=None):
        """
        Show rows: [{"id", "tone", <column key>: text, "sort": {<column key>: value}}], with the
        row `selected` (an id, or None) marked. The sorting the user chose stays.
        """
        self._props["rows"] = rows
        self._props["selected"] = selected
        self.update()
