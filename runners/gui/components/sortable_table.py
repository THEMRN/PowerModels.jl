"""
A table of rows to choose from, sorted by a click on a column title, with one row selected and
opened by a double-click or Enter: the History page's runs. The table is sortable_table.js; this is its Python side.

It is one element for the whole table, so a few hundred rows stay quick, and it has the look of
`theme.data_table`.
"""

from nicegui import ui


class SortableTable(ui.element, component="sortable_table.js"):
    """
    `columns`: [{"key", "label", "numeric", "wide"}]; `order`: {"key", "descending"}, the first
    sorting; `on_select(id)` is called when a row is chosen by a click or the arrow keys, and
    `on_open(id)` when a row is double-clicked or Enter is pressed on the selected row.
    Rows are given to `show`.
    """

    def __init__(self, columns, *, order=None, empty="Nothing to show.", on_select=None, on_open=None):
        super().__init__()
        self._props["columns"] = columns
        self._props["rows"] = []
        self._props["selected"] = None
        self._props["order"] = order or {}
        self._props["empty"] = empty
        if on_select is not None:
            self.on("select", lambda event: on_select(event.args))
        if on_open is not None:
            self.on("open", lambda event: on_open(event.args))

    def show(self, rows, selected=None):
        """
        Show rows: [{"id", "tone", "tones": {<column key>: class}, <column key>: text, "sort":
        {<column key>: value}}], with the row `selected` (an id, or None) marked. `tone` is a class
        for the whole row, `tones` (optional) one for single cells. The sorting the user chose stays.
        """
        self._props["rows"] = rows
        self._props["selected"] = selected
        self.update()
