"""
Look of the GUI: the stylesheet (theme.css), the defaults of the NiceGUI elements, the icons and
a few building blocks, so every page looks the same. The rules are in gui_plan.md ("Look").

app.py calls `setup()` once and `apply_colors()` in each page. A page builds with plain NiceGUI
elements (they get the look from the defaults) and with the blocks below.
"""

import asyncio
import inspect
from html import escape
from pathlib import Path

from nicegui import ui

# ==================== Settings ====================
STYLESHEET = Path(__file__).with_name("theme.css")
# Quasar's own colour names, for the parts it colours itself (the same values as in theme.css)
ACCENT = "#2563eb"
OK = "#1f9d5b"
WARN = "#d48a06"
BAD = "#d1343f"

# the app's mark, also its browser tab icon: a ring left open, with the island beside it
MARK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22">'
    f'<rect width="24" height="24" rx="6.5" fill="{ACCENT}"/>'
    '<path d="M12 6.2a5.8 5.8 0 1 0 5.8 5.8" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>'
    '<circle cx="16.7" cy="7.3" r="1.8" fill="#fff"/>'
    "</svg>"
)

# icons as Quasar "svg path" strings (24 x 24), drawn with lines; `play` and `stop` are filled
LINES = "fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round"
ICONS = {
    "play": "M8 5.6v12.8a.6.6 0 0 0 .92.5l10.1-6.4a.6.6 0 0 0 0-1L8.92 5.1a.6.6 0 0 0-.92.5z",
    "stop": "M8.5 6.5h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z",
    "refresh": f"M20 12a8 8 0 1 1-2.6-5.9L20 8.5M20 4v4.5h-4.5@@{LINES}",
    "plus": f"M12 5.5v13M5.5 12h13@@{LINES}",
    "close": f"M6.5 6.5l11 11M17.5 6.5l-11 11@@{LINES}",
    "chevron_down": f"M6.5 9.5l5.5 5.5 5.5-5.5@@{LINES}",
    "chevron_right": f"M9.5 6.5l5.5 5.5-5.5 5.5@@{LINES}",
    "sliders": f"M4 7.5h9M17 7.5h3M4 16.5h3M11 16.5h9M15 5.2v4.6M9 14.2v4.6@@{LINES}",
}
BUTTON_KINDS = {"primary": "btn-primary", "default": "btn", "ghost": "btn-ghost", "danger": "btn btn-danger"}
NO_VALUE = "–"                  # shown for a number that is not there
BUSY_DELAY = 0.2                # s, a button's work shorter than this shows no turning ring (theme.css waits as long)


# ==================== Setup ====================
def setup():
    """Load the stylesheet into every page and give the NiceGUI elements their look. Call once, before the pages are built."""
    ui.add_css(STYLESHEET, shared=True)
    ui.button.default_props("no-caps unelevated")
    ui.select.default_props("outlined dense options-dense hide-bottom-space")
    ui.number.default_props("outlined dense hide-bottom-space")
    # no spelling check: what is typed are names, tags and bus numbers
    ui.input.default_props("outlined dense hide-bottom-space spellcheck=false")
    ui.textarea.default_props("outlined dense autogrow hide-bottom-space spellcheck=false")
    ui.checkbox.default_props("dense")
    # colour names Quasar has no class for, so the stylesheet draws the chosen segment
    ui.toggle.default_props("no-caps unelevated toggle-color=segment toggle-text-color=segment")
    ui.tabs.default_props("dense no-caps align=left")


def apply_colors():
    """Quasar's colours for the page being built (it colours notifications and checkmarks itself)."""
    ui.colors(primary=ACCENT, positive=OK, negative=BAD, warning=WARN)


# ==================== Building blocks ====================
def button(text="", *, icon=None, kind="default", small=False, on_click=None, busy=False):
    """
    A button. `kind`: "primary" (the main action of a page, one at most), "default" (outlined),
    "ghost" (text only, for secondary actions) or "danger". `icon` is a name in ICONS. Without
    text it is a square icon button, which needs a tooltip. `busy`: the click may take a while
    (it waits for Julia), so the button turns into a ring while `on_click` runs (`busy_handler`).
    """
    if busy and on_click is not None:
        element = ui.button(text, icon=ICONS[icon] if icon else None, color=None)
        element.on_click(busy_handler(element, on_click))
    else:
        element = ui.button(text, icon=ICONS[icon] if icon else None, color=None, on_click=on_click)
    element.classes(BUTTON_KINDS[kind])
    if not text:
        element.classes("btn-icon")
    if small:
        element.classes("btn-small")
    return element


def busy_handler(element, handler):
    """
    A click handler for `element` (a button) that runs `handler` (plain or async) and shows that it
    is at work: the button turns into a ring after BUSY_DELAY, so a quick click shows nothing, and
    clicks on it are ignored until `handler` is done, so a double click does not do it twice (Quasar
    itself ignores clicks on a button with its ring). For a page that stays where it is while it waits.
    """

    async def clicked():
        if getattr(element, "at_work", False):
            return
        element.at_work = True
        show_ring = asyncio.get_running_loop().call_later(BUSY_DELAY, lambda: element.props("loading"))
        try:
            result = handler()
            if inspect.isawaitable(result):
                await result
        finally:
            show_ring.cancel()
            element.at_work = False
            element.props(remove="loading")

    return clicked


def grey_out(elements, waiting):
    """Grey out elements that wait for something (they take no clicks), or bring them back."""
    for element in elements:
        if waiting:
            element.classes(add="greyed")
        else:
            element.classes(remove="greyed")


class Cover(ui.element):
    """
    A veil over a part of the page that waits, with a turning ring and a text that says for what.
    It fades in after a moment, so a quick wait shows nothing. It covers its parent (which needs
    `position: relative`), or a grid cell it is placed in. `show(text)` and `hide()`.
    """

    def __init__(self):
        super().__init__("div")
        self.classes("wait-cover")
        with self:
            self.label = ui.label().classes("waiting")
        self.set_visibility(False)

    def show(self, text):
        self.label.text = text
        self.set_visibility(True)

    def hide(self):
        self.set_visibility(False)


def panel():
    """A white block with a hairline border, as wide as the page."""
    return ui.element("div").classes("panel")


def toolbar():
    """The top row of a panel: a fold button or an eyebrow, a `toolbar_text`, then buttons at the right."""
    return ui.element("div").classes("toolbar")


def toolbar_text(text=""):
    """The text of a toolbar: it takes the room left and is cut with "..." when too long."""
    return ui.label(text).classes("toolbar-text")


def sheet():
    """A sheet of settings: its sections stand side by side, four, two or one in a row by the page's width."""
    return ui.element("div").classes("sheet")


class Section(ui.element):
    """One section of a sheet: a small title, with room at its right in `head`, then the content."""

    def __init__(self, title):
        super().__init__("div")
        self.classes("section")
        with self:
            with ui.element("div").classes("section-head") as self.head:
                eyebrow(title)


def dialog():
    """
    A dialog and its white box: `dialog, box = theme.dialog()`, then `with box:` for the content
    (a `toolbar` first, with the title and a close button) and `dialog.open()`.
    """
    element = ui.dialog()
    with element:
        box = ui.element("div").classes("dialog")
    return element, box


def offstage():
    """A holder for parts that show nothing (timers), so they take no room in the layout around them."""
    return ui.element("div").classes("offstage")


def format_number(value, digits):
    """
    A number with a fixed count of decimals, or NO_VALUE when there is none. A text is returned as
    it is (an empty cell in a number column). It formats; it does not round a value again.
    """
    if value is None:
        return NO_VALUE
    if isinstance(value, str):
        return value
    return f"{value:.{digits}f}"


def data_table(columns, rows, footers=()):
    """
    A table of numbers as one element. `columns` is a list of (title, key, digits): `key` is the
    row's key and `digits` the decimals of a number column (right aligned), or None for a text
    column (left aligned). `rows` and `footers` are lists of dicts; footers (totals) stand out.
    The values go in as text: names from a case file cannot bring markup with them.
    """

    def build_row(row, tag):
        cells = []
        for _title, key, digits in columns:
            value = row.get(key)
            if digits is None:
                cells.append(f"<{tag}>{escape('' if value is None else str(value))}</{tag}>")
            else:
                cells.append(f'<{tag} class="num">{escape(format_number(value, digits))}</{tag}>')
        return "<tr>" + "".join(cells) + "</tr>"

    head = "".join(
        f"<th>{escape(title)}</th>" if digits is None else f'<th class="num">{escape(title)}</th>'
        for title, _key, digits in columns
    )
    body = "".join(build_row(row, "td") for row in rows)
    foot = "".join(build_row(row, "td") for row in footers)
    html = f'<table class="data-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody>'
    if foot:
        html += f"<tfoot>{foot}</tfoot>"
    return ui.html(html + "</table>")


def facts():
    """A list of facts: in turn a `fact_label` and its value. `fact` makes both for a plain text value."""
    return ui.element("div").classes("facts")


def fact_label(text):
    """The name of a fact; the next element is its value."""
    return ui.label(text).classes("fact-label")


def fact(name, text):
    """A fact with a text value; returns the value's label."""
    fact_label(name)
    return ui.label(text).classes("fact-value num")


def fields():
    """A two-column grid: in turn a `label` and its control."""
    return ui.element("div").classes("fields")


def stack():
    """Elements under each other, close together."""
    return ui.element("div").classes("stack")


def line():
    """Elements beside each other on one line; give the one that takes the room left the class "grow"."""
    return ui.element("div").classes("line")


def label(text):
    """The label of a control in `fields`."""
    return ui.label(text).classes("field-label")


def eyebrow(text):
    """A small title: of a section, a panel, a table column."""
    return ui.label(text).classes("eyebrow")


def hint(text=""):
    """A small grey line of explanation; it takes no room while empty. `show_hint` changes it."""
    return ui.label(text).classes("hint")


def show_hint(element, text, bad=False, waiting=False):
    """Put `text` in a hint: in red when it reports a problem, after a turning ring when it says what is awaited."""
    element.text = text
    element.classes(replace="hint" + (" bad" if bad else "") + (" waiting" if waiting else ""))


class State(ui.element):
    """A coloured dot and a few words, for the state of something; `pill` gives it a border."""

    def __init__(self, state="", text="", *, pill=False):
        super().__init__("div")
        self.classes("state pill" if pill else "state")
        with self:
            ui.element("span").classes("dot")
            self.label = ui.label()
        self.show(state, text)

    def show(self, state, text):
        """`state` picks the dot's colour (theme.css, ".state"): ready, busy, running, finished, failed, ..."""
        self.props(f"data-state={state or 'none'}")
        self.label.text = text


class FoldButton(ui.button):
    """
    A text button with a chevron that shows and hides a body. The body is built after the button
    (it stands below it), so it is given with `attach(body)`. `on_change(opened)` is called after
    each change.
    """

    def __init__(self, text, *, opened=True, on_change=None):
        super().__init__(text, color=None, on_click=lambda: self.set_opened(not self.opened))
        self.classes("btn-ghost btn-fold")
        self.body = None
        self.opened = opened
        self.on_change = on_change
        self.props["icon"] = ICONS["chevron_down" if opened else "chevron_right"]

    def attach(self, body):
        """The element this button shows and hides; returns it, so it can open a `with` block."""
        self.body = body
        body.set_visibility(self.opened)
        return body

    def set_opened(self, opened):
        self.opened = opened
        self.props["icon"] = ICONS["chevron_down" if opened else "chevron_right"]
        self.update()
        if self.body is not None:
            self.body.set_visibility(opened)
        if self.on_change is not None:
            self.on_change(opened)

    def open(self):
        self.set_opened(True)
