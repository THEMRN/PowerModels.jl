// The network drawing of the Network page: buses, lines and group circles on a canvas, with zoom
// (wheel), pan (drag), fit (double click), a tooltip, clicks and a selection box (shift + drag).
//
// It draws what it is told and decides nothing. network_canvas.py passes two props:
//   graph  what is where:   {key, nodes: [[x, y, square]], links: [[a, b]], circles: [[x, y, radius]]}
//   look   how it is drawn: {key, node: {color, size, mark, label, tip}, link: {color, width, arrow, mark, tip},
//                            circle: {fill, line, mark, label, note, tip}}, one value per item in each list
// Positions are in line lengths; sizes and widths are in screen pixels, whatever the zoom.
// A mark is 0 (plain), 1 (selected: an accent ring, or a dashed line with a halo) or 2 (dimmed).
// It emits "pick" {kind: "node" | "link" | "circle" | "none", index, shift, ctrl} for a click,
// "box" {nodes, links, ctrl} for a selection box, and "ready" once, when it first has a size on
// the screen (the page it is on is built with the others, but shown only when its tab is chosen).

const PADDING = 26;            // px between the drawing and the edge of the canvas when fitted
const NODE_HIT = 9;            // px around a bus that still count as on it
const LINK_HIT = 5;            // px around a line
const CLICK_MOVE = 4;          // px the mouse may move between press and release of a click
const ARROW_FROM = 26;         // px a line must be long to get its arrow
const LABELS_FROM = 46;        // px per line length from which every bus shows its label
const ZOOM_MOST = 60;          // largest zoom, in times the fitted view
const FONT = '"Segoe UI", system-ui, sans-serif';
const INK = "#1f2733";         // labels
const HALO = "#ffffff";        // behind labels and selected lines
const ACCENT = "#2563eb";      // the ring of a selected bus, the selection box
const SELECTED = "#d1343f";    // a selected line (a boundary line)

export default {
  template: `<div class="network-canvas"><canvas ref="canvas"></canvas><div ref="tip" class="network-tip"></div></div>`,
  props: { graph: Object, look: Object },

  mounted() {
    this.view = { scale: 1, x: 0, y: 0, fitted: true };     // screen = world * scale + (x, y)
    this.fitScale = 1;
    this.hover = null;                                      // {kind, index} under the mouse
    this.press = null;                                      // the mouse press in progress
    this.box = null;                                        // the selection box in progress, in screen px
    this.frame = null;
    this.graphKey = this.graph ? this.graph.key : null;     // the graph that the view was fitted to
    const canvas = this.$refs.canvas;
    canvas.addEventListener("wheel", (event) => this.onWheel(event), { passive: false });
    canvas.addEventListener("mousedown", (event) => this.onDown(event));
    canvas.addEventListener("mousemove", (event) => this.onMove(event));
    canvas.addEventListener("mouseleave", () => this.setHover(null));
    canvas.addEventListener("dblclick", () => this.fit());
    this.onWindowMove = (event) => this.onDrag(event);
    this.onWindowUp = (event) => this.onUp(event);
    window.addEventListener("mousemove", this.onWindowMove);
    window.addEventListener("mouseup", this.onWindowUp);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.$el);
    this.resize();
  },

  beforeUnmount() {
    window.removeEventListener("mousemove", this.onWindowMove);
    window.removeEventListener("mouseup", this.onWindowUp);
    this.resizeObserver.disconnect();
    cancelAnimationFrame(this.frame);
  },

  activated() {
    this.resize();
  },

  watch: {
    graph() {
      if (this.graph.key !== this.graphKey) {
        this.graphKey = this.graph.key;
        this.hover = null;
        this.fit();
      }
      this.redraw();
    },
    look() {
      this.redraw();
    },
  },

  methods: {
    // -------------------- the view --------------------
    resize() {
      const canvas = this.$refs.canvas;
      const width = this.$el.clientWidth;
      const height = this.$el.clientHeight;
      if (!width || !height) return;                        // hidden: keep what there is
      if (!this.shown) {                                    // on the screen for the first time
        this.shown = true;
        this.$emit("ready");
      }
      const ratio = window.devicePixelRatio || 1;
      const center = this.width ? this.toWorld(this.width / 2, this.height / 2) : null;
      this.width = width;
      this.height = height;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      this.ratio = ratio;
      const scale = this.view.scale;
      this.findFit();
      if (this.view.fitted || !center) {
        this.fit();
      } else {                                              // keep what was in the middle there
        this.view.scale = scale;
        this.view.x = width / 2 - center[0] * scale;
        this.view.y = height / 2 - center[1] * scale;
        this.redraw();
      }
    },

    findBounds() {
      let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
      for (const [x, y, radius] of this.graph.circles || []) {
        left = Math.min(left, x - radius); right = Math.max(right, x + radius);
        top = Math.min(top, y - radius); bottom = Math.max(bottom, y + radius);
      }
      for (const [x, y] of this.graph.nodes || []) {
        left = Math.min(left, x); right = Math.max(right, x);
        top = Math.min(top, y); bottom = Math.max(bottom, y);
      }
      if (left > right) return { left: -1, right: 1, top: -1, bottom: 1 };
      return { left, right, top, bottom };
    },

    findFit() {
      const bounds = this.findBounds();
      const wide = Math.max(bounds.right - bounds.left, 1e-6);
      const high = Math.max(bounds.bottom - bounds.top, 1e-6);
      this.bounds = bounds;
      this.fitScale = Math.max(1e-3, Math.min((this.width - 2 * PADDING) / wide, (this.height - 2 * PADDING - 14) / high));
    },

    fit() {
      if (!this.width) return;
      this.findFit();
      const bounds = this.bounds;
      this.view.scale = this.fitScale;
      this.view.x = this.width / 2 - ((bounds.left + bounds.right) / 2) * this.fitScale;
      this.view.y = this.height / 2 + 7 - ((bounds.top + bounds.bottom) / 2) * this.fitScale;
      this.view.fitted = true;
      this.redraw();
    },

    // show the buses with these indices, with room around them
    show(indices) {
      const nodes = (indices || []).map((index) => this.graph.nodes[index]).filter(Boolean);
      if (!nodes.length || !this.width) return;
      const xs = nodes.map((node) => node[0]);
      const ys = nodes.map((node) => node[1]);
      const wide = Math.max(Math.max(...xs) - Math.min(...xs), 2.5);
      const high = Math.max(Math.max(...ys) - Math.min(...ys), 2.5);
      const scale = Math.min((this.width - 6 * PADDING) / wide, (this.height - 6 * PADDING) / high, this.fitScale * ZOOM_MOST);
      this.view.scale = Math.max(scale, this.fitScale);
      this.view.x = this.width / 2 - ((Math.max(...xs) + Math.min(...xs)) / 2) * this.view.scale;
      this.view.y = this.height / 2 - ((Math.max(...ys) + Math.min(...ys)) / 2) * this.view.scale;
      this.view.fitted = false;
      this.redraw();
    },

    toScreen(x, y) {
      return [x * this.view.scale + this.view.x, y * this.view.scale + this.view.y];
    },

    toWorld(x, y) {
      return [(x - this.view.x) / this.view.scale, (y - this.view.y) / this.view.scale];
    },

    // -------------------- the mouse --------------------
    findPlace(event) {
      const rect = this.$refs.canvas.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top];
    },

    onWheel(event) {
      event.preventDefault();
      const [x, y] = this.findPlace(event);
      const factor = Math.exp(-event.deltaY * 0.0015);
      const scale = Math.min(Math.max(this.view.scale * factor, this.fitScale * 0.6), this.fitScale * ZOOM_MOST);
      const world = this.toWorld(x, y);
      this.view.scale = scale;
      this.view.x = x - world[0] * scale;
      this.view.y = y - world[1] * scale;
      this.view.fitted = false;
      this.redraw();
    },

    onDown(event) {
      if (event.button !== 0) return;
      const [x, y] = this.findPlace(event);
      this.press = { x, y, viewX: this.view.x, viewY: this.view.y, moved: false, box: event.shiftKey };
      event.preventDefault();
    },

    onDrag(event) {
      if (!this.press) return;
      const [x, y] = this.findPlace(event);
      if (Math.hypot(x - this.press.x, y - this.press.y) > CLICK_MOVE) this.press.moved = true;
      if (!this.press.moved) return;
      if (this.press.box) {
        this.box = [this.press.x, this.press.y, x, y];
      } else {
        this.view.x = this.press.viewX + x - this.press.x;
        this.view.y = this.press.viewY + y - this.press.y;
        this.view.fitted = false;
      }
      this.setHover(null);
      this.redraw();
    },

    onUp(event) {
      const press = this.press;
      if (!press) return;
      this.press = null;
      const [x, y] = this.findPlace(event);
      if (!press.moved) {
        const hit = this.findHit(x, y) || { kind: "none", index: -1 };
        this.$emit("pick", { kind: hit.kind, index: hit.index, shift: event.shiftKey, ctrl: event.ctrlKey || event.metaKey });
      } else if (press.box) {
        this.$emit("box", { ...this.findInBox(press.x, press.y, x, y), ctrl: event.ctrlKey || event.metaKey });
        this.box = null;
        this.redraw();
      }
    },

    onMove(event) {
      if (this.press) return;
      const [x, y] = this.findPlace(event);
      this.setHover(this.findHit(x, y), x, y);
    },

    // what is at a place of the screen: a bus before a line before a circle
    findHit(x, y) {
      const nodes = this.graph.nodes || [];
      const sizes = (this.look.node || {}).size || [];
      const grow = this.findGrowth();
      let best = null, nearest = Infinity;
      for (let index = 0; index < nodes.length; index++) {
        const [nodeX, nodeY] = this.toScreen(nodes[index][0], nodes[index][1]);
        const distance = Math.hypot(nodeX - x, nodeY - y) - (sizes[index] || 3) * grow;
        if (distance < NODE_HIT - 3 && distance < nearest) { nearest = distance; best = index; }
      }
      if (best !== null) return { kind: "node", index: best };
      const links = this.graph.links || [];
      nearest = LINK_HIT;
      for (let index = 0; index < links.length; index++) {
        const [fromX, fromY] = this.toScreen(...nodes[links[index][0]]);
        const [toX, toY] = this.toScreen(...nodes[links[index][1]]);
        const dx = toX - fromX, dy = toY - fromY;
        const along = Math.max(0, Math.min(1, ((x - fromX) * dx + (y - fromY) * dy) / Math.max(dx * dx + dy * dy, 1e-9)));
        const distance = Math.hypot(x - fromX - along * dx, y - fromY - along * dy);
        if (distance < nearest) { nearest = distance; best = index; }
      }
      if (best !== null) return { kind: "link", index: best };
      const circles = this.graph.circles || [];
      const [worldX, worldY] = this.toWorld(x, y);
      for (let index = 0; index < circles.length; index++) {
        if (Math.hypot(worldX - circles[index][0], worldY - circles[index][1]) <= circles[index][2]) best = index;
      }
      return best === null ? null : { kind: "circle", index: best };
    },

    findInBox(x1, y1, x2, y2) {
      const left = Math.min(x1, x2), right = Math.max(x1, x2), top = Math.min(y1, y2), bottom = Math.max(y1, y2);
      const inside = (x, y) => x >= left && x <= right && y >= top && y <= bottom;
      const nodes = [], links = [];
      (this.graph.nodes || []).forEach((node, index) => {
        if (inside(...this.toScreen(node[0], node[1]))) nodes.push(index);
      });
      (this.graph.links || []).forEach((link, index) => {
        const from = this.toScreen(...this.graph.nodes[link[0]]), to = this.toScreen(...this.graph.nodes[link[1]]);
        if (inside((from[0] + to[0]) / 2, (from[1] + to[1]) / 2)) links.push(index);
      });
      return { nodes, links };
    },

    setHover(hit, x, y) {
      const same = (hit && this.hover && hit.kind === this.hover.kind && hit.index === this.hover.index) || (!hit && !this.hover);
      this.hover = hit;
      const tip = this.$refs.tip;
      const text = hit ? (((this.look[hit.kind] || {}).tip || [])[hit.index] || "") : "";
      if (!text) {
        tip.style.display = "none";
      } else {
        tip.textContent = text;
        tip.style.display = "block";
        const wide = tip.offsetWidth, high = tip.offsetHeight;
        tip.style.left = Math.max(4, Math.min(x + 14, this.width - wide - 4)) + "px";
        tip.style.top = Math.max(4, y + 16 + high > this.height ? y - high - 10 : y + 16) + "px";
      }
      this.$refs.canvas.style.cursor = hit && hit.kind !== "circle" ? "pointer" : "default";
      if (!same) this.redraw();
    },

    // -------------------- drawing --------------------
    redraw() {
      cancelAnimationFrame(this.frame);
      this.frame = requestAnimationFrame(() => this.draw());
    },

    // buses grow a little when zoomed in, so that they stay easy to see and to hit
    findGrowth() {
      return Math.min(2.2, Math.max(1, Math.pow(this.view.scale / this.fitScale, 0.4)));
    },

    draw() {
      const canvas = this.$refs.canvas;
      if (!canvas || !this.width) return;
      const started = performance.now();
      const context = canvas.getContext("2d");
      context.setTransform(this.ratio, 0, 0, this.ratio, 0, 0);
      context.clearRect(0, 0, this.width, this.height);
      const nodes = this.graph.nodes || [], links = this.graph.links || [], circles = this.graph.circles || [];
      const nodeLook = this.look.node || {}, linkLook = this.look.link || {}, circleLook = this.look.circle || {};
      const places = nodes.map((node) => this.toScreen(node[0], node[1]));
      const grow = this.findGrowth();
      const hover = this.hover || {};
      context.lineCap = "round";

      // the circles of the groups
      circles.forEach(([x, y, radius], index) => {
        const [centerX, centerY] = this.toScreen(x, y);
        const marked = (circleLook.mark || [])[index] === 1;
        context.beginPath();
        context.arc(centerX, centerY, radius * this.view.scale, 0, 2 * Math.PI);
        context.fillStyle = (circleLook.fill || [])[index] || "rgba(0,0,0,0.03)";
        context.fill();
        context.setLineDash(marked ? [7, 4] : [4, 4]);
        context.lineWidth = marked ? 2 : 1;
        context.strokeStyle = (circleLook.line || [])[index] || "#c4c9d2";
        context.stroke();
      });
      context.setLineDash([]);

      // the lines: plain ones first, the selected ones over them with a halo
      const drawLink = (index, halo) => {
        const from = places[links[index][0]], to = places[links[index][1]];
        const mark = (linkLook.mark || [])[index] || 0;
        const width = ((linkLook.width || [])[index] || 1) + (hover.kind === "link" && hover.index === index ? 1.5 : 0);
        context.beginPath();
        context.moveTo(from[0], from[1]);
        context.lineTo(to[0], to[1]);
        if (halo) {
          context.setLineDash([]);
          context.lineWidth = width + 4;
          context.strokeStyle = HALO;
          context.stroke();
          return;
        }
        context.globalAlpha = mark === 2 ? 0.25 : 1;
        context.setLineDash(mark === 1 ? [7, 5] : []);
        context.lineWidth = mark === 1 ? Math.max(width, 2.4) : width;
        context.strokeStyle = mark === 1 ? SELECTED : (linkLook.color || [])[index] || "#b6bcc6";
        context.stroke();
        context.setLineDash([]);

        const arrow = (linkLook.arrow || [])[index] || 0;      // 1 points to the link's second bus, -1 to its first
        const length = Math.hypot(to[0] - from[0], to[1] - from[1]);
        if (arrow && length >= ARROW_FROM) {
          const size = Math.min(4 + context.lineWidth * 1.6, 9) * Math.min(1.5, Math.max(1, grow * 0.8));
          const ux = ((to[0] - from[0]) / length) * arrow, uy = ((to[1] - from[1]) / length) * arrow;
          const middleX = (from[0] + to[0]) / 2, middleY = (from[1] + to[1]) / 2;
          context.beginPath();
          context.moveTo(middleX + ux * size, middleY + uy * size);
          context.lineTo(middleX - ux * size * 0.7 - uy * size * 0.75, middleY - uy * size * 0.7 + ux * size * 0.75);
          context.lineTo(middleX - ux * size * 0.7 + uy * size * 0.75, middleY - uy * size * 0.7 - ux * size * 0.75);
          context.closePath();
          context.fillStyle = context.strokeStyle;
          context.fill();
          context.lineWidth = 1;
          context.strokeStyle = HALO;
          context.stroke();
        }
        context.globalAlpha = 1;
      };
      const marked = [];
      for (let index = 0; index < links.length; index++) {
        if (((linkLook.mark || [])[index] || 0) === 1) marked.push(index);
        else drawLink(index, false);
      }
      marked.forEach((index) => drawLink(index, true));
      marked.forEach((index) => drawLink(index, false));

      // the buses: a circle, or a square for a bus with a generator
      const drawNode = (index) => {
        const [x, y] = places[index];
        if (x < -20 || y < -20 || x > this.width + 20 || y > this.height + 20) return;
        const mark = (nodeLook.mark || [])[index] || 0;
        const hovered = hover.kind === "node" && hover.index === index;
        const size = ((nodeLook.size || [])[index] || 3) * grow + (hovered ? 1.5 : 0);
        context.globalAlpha = mark === 2 ? 0.3 : 1;
        context.beginPath();
        if (nodes[index][2]) context.rect(x - size, y - size, 2 * size, 2 * size);
        else context.arc(x, y, size, 0, 2 * Math.PI);
        context.fillStyle = (nodeLook.color || [])[index] || "#8a93a3";
        context.fill();
        context.lineWidth = 1;
        context.strokeStyle = HALO;
        context.stroke();
        context.globalAlpha = 1;
        if (mark === 1 || hovered) {
          context.beginPath();
          if (nodes[index][2]) context.rect(x - size - 2.5, y - size - 2.5, 2 * size + 5, 2 * size + 5);
          else context.arc(x, y, size + 2.5, 0, 2 * Math.PI);
          context.lineWidth = mark === 1 ? 2 : 1.2;
          context.strokeStyle = mark === 1 ? ACCENT : INK;
          context.stroke();
        }
      };
      const selected = [];
      for (let index = 0; index < nodes.length; index++) {
        if (((nodeLook.mark || [])[index] || 0) === 1) selected.push(index);
        else drawNode(index);
      }
      selected.forEach(drawNode);

      // labels: of every bus when zoomed in, else of the selected ones only (when they are few)
      const drawText = (text, x, y, size, weight, color, align) => {
        context.font = `${weight} ${size}px ${FONT}`;
        context.textAlign = align;
        context.lineJoin = "round";
        context.lineWidth = 3;
        context.strokeStyle = HALO;
        context.strokeText(text, x, y);
        context.fillStyle = color;
        context.fillText(text, x, y);
      };
      context.textBaseline = "middle";
      const labels = nodeLook.label || [];
      const all = this.view.scale >= LABELS_FROM;
      if (all || selected.length <= 40) {
        const shown = all ? nodes.map((_, index) => index) : selected;
        for (const index of shown) {
          const [x, y] = places[index];
          if (!labels[index] || x < 0 || y < 0 || x > this.width || y > this.height) continue;
          const size = ((nodeLook.size || [])[index] || 3) * grow;
          drawText(labels[index], x + size + 4, y, 10.5, 400, INK, "left");
        }
      }
      if (hover.kind === "node" && labels[hover.index] && !all) {
        const [x, y] = places[hover.index];
        drawText(labels[hover.index], x + ((nodeLook.size || [])[hover.index] || 3) * grow + 5, y, 10.5, 600, INK, "left");
      }

      // the names of the groups, above their circles
      context.textBaseline = "alphabetic";
      circles.forEach(([x, y, radius], index) => {
        const label = (circleLook.label || [])[index];
        if (!label) return;
        const [centerX, centerY] = this.toScreen(x, y);
        const top = centerY - radius * this.view.scale;
        const note = (circleLook.note || [])[index];
        drawText(label, centerX, top - (note ? 17 : 5), 12, 600, (circleLook.ink || [])[index] || INK, "center");
        if (note) drawText(note, centerX, top - 4, 11, 400, INK, "center");
      });

      // the selection box
      if (this.box) {
        const [x1, y1, x2, y2] = this.box;
        context.fillStyle = "rgba(37, 99, 235, 0.08)";
        context.strokeStyle = ACCENT;
        context.lineWidth = 1;
        context.setLineDash([4, 3]);
        context.fillRect(x1, y1, x2 - x1, y2 - y1);
        context.strokeRect(x1, y1, x2 - x1, y2 - y1);
        context.setLineDash([]);
      }
      this.lastDrawMs = performance.now() - started;
    },
  },
};
