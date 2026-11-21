"""
A list of rows to edit: column titles, one line of fields per row with a remove button, and
"Add row". The rows are plain dicts in a list, which is edited in place, so whoever gave the
list reads the result from it.
"""

from nicegui import ui

import theme


class RowList:
    """
    `rows` is the list being edited. `build_row(row)` draws the fields of one row, in the columns
    of the grid class `row_class` (theme.css); the remove button is added here. `new_row()` gives
    the dict of an added row. `on_change()` is called after a row is added or removed.
    """

    def __init__(self, rows, *, titles, row_class, new_row, build_row, on_change=None):
        self.rows = rows
        self.row_class = row_class
        self.new_row = new_row
        self.build_row = build_row
        self.on_change = on_change
        with theme.stack():
            with ui.element("div").classes(f"edit-row {row_class}"):
                for title in titles:
                    theme.eyebrow(title)
            self.box = theme.stack()
            with theme.line():
                theme.button("Add row", icon="plus", kind="ghost", small=True, on_click=self._add)
        self.refresh()

    def refresh(self):
        """Draw the rows again: one was added or removed, or the fields of one depend on what was chosen in it."""
        self.box.clear()
        with self.box:
            for row in self.rows:
                with ui.element("div").classes(f"edit-row {self.row_class}"):
                    self.build_row(row)
                    theme.button(icon="close", kind="ghost", small=True, on_click=lambda row=row: self._remove(row)).tooltip(
                        "Remove this row"
                    )

    def _add(self):
        self.rows.append(self.new_row())
        self._changed()

    def _remove(self, row):
        # by identity: two rows may hold the same values
        self.rows[:] = [other for other in self.rows if other is not row]
        self._changed()

    def _changed(self):
        self.refresh()
        if self.on_change is not None:
            self.on_change()
