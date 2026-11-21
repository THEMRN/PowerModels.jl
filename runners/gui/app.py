"""
Islanding GUI: a local page in the browser that runs islanding scenarios through one warm Julia
worker. Start it from any folder:

    python runners/gui/app.py          (opens http://localhost:8080)

or double-click start_gui.bat. Options: --port N for another port, --no-browser to not open the
page. Started while it is already running, it only opens the running page.

The plan, the decisions and the contracts are in runners/gui/gui_plan.md. A page is one module
in pages/ with TITLE and build(ctx), listed in PAGES.
"""

import argparse
import socket
import webbrowser
from pathlib import Path

from nicegui import app, ui

import theme
from components.log_dialog import LogDialog
from julia_worker import JuliaWorker
from pages import history, network, run
from session_runs import SessionRuns

# ==================== Settings ====================
PORT = 8080
HOST = "127.0.0.1"              # this machine only (decision 1); NiceGUI would listen on every network address
NATIVE_WINDOW = False           # a desktop window would need pywebview (gui_plan.md, decision 1)
TITLE = "Islanding GUI"
REPO_ROOT = Path(__file__).resolve().parents[2]
PAGES = [run, network, history] # one tab per page module, in this order


class AppContext:
    """
    What the pages share: the Julia worker, the runs of this session, a state dict (what is cached
    from Julia: the case list, each case's information and network), and the repo root. What
    belongs to one browser tab (its Run form, the function that shows one of its pages) is in
    `client_state()`, through which the pages of a tab pass values to each other.
    """

    def __init__(self, worker, repo_root):
        self.worker = worker
        self.runs = SessionRuns(worker)
        self.state = {}
        self.repo_root = repo_root
        self._client_states = {}        # browser tab (client id) -> its dict

    def client_state(self):
        """The dict of the browser tab being built or served; it goes when the tab closes."""
        client = ui.context.client
        if client.id not in self._client_states:
            self._client_states[client.id] = {}
            client.on_delete(lambda: self._client_states.pop(client.id, None))
        return self._client_states[client.id]


ctx = AppContext(JuliaWorker(REPO_ROOT), REPO_ROOT)


def describe_state(state):
    """The Julia state pill's words: the worker's state, and the run in progress while it is busy with one."""
    running = ctx.runs.find_running()
    if state == "busy" and running is not None:
        return f"Julia running · run {running['number']}"
    return f"Julia {state}"


def describe_worker():
    """Tooltip of the Julia state pill: version, process id, the reason it stopped, and what a click shows."""
    worker = ctx.worker
    parts = []
    if worker.julia_version:
        parts.append(f"Julia {worker.julia_version}")
    if worker.pid is not None and worker.is_running():
        parts.append(f"PID {worker.pid}")
    if worker.message:
        parts.append(worker.message)
    parts.append("click for what Julia printed outside the runs")
    return ", ".join(parts)


def build_worker_state():
    """
    The Julia state pill and Restart Julia; the pill follows the worker and the runs in every open
    tab. A click on it shows what Julia printed outside the runs (its start, and why it stopped).
    """
    log_dialog = LogDialog()
    pill = theme.State(pill=True).classes("clickable")
    pill.on("click", lambda: log_dialog.open("Julia, outside the runs", ctx.worker.worker_log))
    with pill:
        tooltip = ui.tooltip()

    def show_state(*_):
        pill.show(ctx.worker.state, describe_state(ctx.worker.state))
        tooltip.text = describe_worker()

    async def restart_julia():
        restart_button.disable()
        try:
            await ctx.worker.restart()
        finally:
            restart_button.enable()

    restart_button = theme.button("Restart Julia", icon="refresh", kind="ghost", on_click=restart_julia)
    restart_button.tooltip("Stop Julia with anything it runs, and start a fresh one")
    show_state()
    removers = [ctx.worker.on_state(show_state), ctx.runs.on_change(show_state)]
    ui.context.client.on_delete(lambda: [remove() for remove in removers])


@ui.page("/")
def main_page():
    """One bar on top (mark, title, page tabs, Julia state), then the chosen page."""
    theme.apply_colors()
    with ui.header():
        with ui.element("div").classes("brand"):
            ui.html(theme.MARK, sanitize=False)
            ui.label(TITLE).classes("brand-title")
        with ui.tabs() as tabs:
            page_tabs = [ui.tab(page.TITLE) for page in PAGES]
        ctx.client_state()["show_page"] = tabs.set_value       # show_page(TITLE) brings a page of this tab forward
        with ui.element("div").classes("header-end"):
            build_worker_state()
    with ui.tab_panels(tabs, value=page_tabs[0], animated=False).classes("w-full"):
        for page, page_tab in zip(PAGES, page_tabs):
            with ui.tab_panel(page_tab):
                page.build(ctx)


def print_state(state, message=""):
    """The worker's state changes on the app's console."""
    detail = f" ({message})" if message else ""
    if state == "ready":
        detail = f" (Julia {ctx.worker.julia_version}, PID {ctx.worker.pid})"
    print(f"-- Julia worker: {state}{detail}", flush=True)


# the look of every page, and the worker, which lives as long as the app
theme.setup()
ctx.worker.on_state(print_state)
app.on_startup(ctx.worker.start)
app.on_shutdown(ctx.worker.stop)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Islanding GUI: a local page that runs islanding scenarios.")
    parser.add_argument("--port", type=int, default=PORT, help=f"port of the local page (default {PORT})")
    parser.add_argument("--no-browser", action="store_true", help="do not open the page in the browser")
    return parser.parse_args()


def is_port_in_use(port):
    """True when something already listens on the local port, most likely this GUI started earlier."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    arguments = parse_arguments()
    page_url = f"http://localhost:{arguments.port}"
    if is_port_in_use(arguments.port):
        # a second start: show the page that is already there instead of failing to bind the port
        print(f"Port {arguments.port} is already in use, so the GUI is probably running already at {page_url}")
        if not arguments.no_browser:
            webbrowser.open(page_url)
    else:
        ui.run(
            host=HOST, port=arguments.port, native=NATIVE_WINDOW, reload=False, title=TITLE, favicon=theme.MARK,
            show=not arguments.no_browser,
        )
