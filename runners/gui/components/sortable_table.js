// A table of rows to choose from: sorted by a click on a column title (again for the other way),
// one row selected by a click or the arrow keys, and opened by a double-click or Enter. One element
// for the whole table, so that a few hundred rows stay quick; sortable_table.py is its Python side.
//
// Props:
//   columns   [{key, label, numeric, wide}]: `numeric` aligns right; `wide` lets the column take the room left
//   rows      [{id, tone, tones: {<key>: class}, <key>: text, sort: {<key>: value}}]: `tone` is a class for the row
//             ("muted", "warn"), `tones` a class for single cells ("cell-bad", "cell-warn");
//             a column sorts by `sort[key]` when it is there, else by its text; no value sorts last
//   selected  the id of the selected row, or null
//   order     {key, descending}: the first sorting
// It emits "select" with the id of the row clicked or reached with the arrow keys, and "open" with
// the id of the row double-clicked, or of the selected row when Enter is pressed.

export default {
  template: `
    <div class="sortable-table" tabindex="0" @keydown="onKey">
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column.key" @click="sortBy(column.key)"
                :class="['col-' + column.key, {num: column.numeric, wide: column.wide, sorted: sortKey === column.key}]">
              {{ column.label }}<span class="sort-mark">{{ sortKey === column.key ? (descending ? " ▾" : " ▴") : "" }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in sortedRows" :key="row.id" :ref="'row-' + row.id" @click="choose(row.id)" @dblclick="open(row.id)"
              :class="[row.tone || '', {selected: row.id === chosen}]">
            <td v-for="column in columns" :key="column.key"
                :class="['col-' + column.key, (row.tones || {})[column.key] || '', {num: column.numeric, wide: column.wide}]"
                :title="column.wide ? row[column.key] : null">{{ row[column.key] }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="sortable-empty">{{ empty }}</div>
    </div>`,
  props: { columns: Array, rows: Array, selected: String, order: Object, empty: String },

  data() {
    return {
      sortKey: (this.order || {}).key || null,
      descending: Boolean((this.order || {}).descending),
      chosen: this.selected || null,
    };
  },

  watch: {
    selected(value) {
      this.chosen = value || null;
    },
  },

  computed: {
    sortedRows() {
      const key = this.sortKey;
      if (!key) return this.rows;
      const valueOf = (row) => {
        const value = row.sort && key in row.sort ? row.sort[key] : row[key];
        return value === null || value === undefined || value === "" || value === "–" ? null : value;
      };
      const sign = this.descending ? -1 : 1;
      return [...this.rows].sort((a, b) => {
        const first = valueOf(a), second = valueOf(b);
        if (first === null || second === null) return first === second ? 0 : first === null ? 1 : -1;
        if (typeof first === "number" && typeof second === "number") return sign * (first - second);
        return sign * String(first).localeCompare(String(second), undefined, { numeric: true, sensitivity: "base" });
      });
    },
  },

  methods: {
    sortBy(key) {
      if (this.sortKey === key) {
        this.descending = !this.descending;
      } else {
        this.sortKey = key;
        this.descending = false;
      }
    },

    choose(id) {
      this.chosen = id;
      this.$emit("select", id);
    },

    open(id) {
      window.getSelection().removeAllRanges(); // the word a double-click selects
      this.chosen = id;
      this.$emit("open", id);
    },

    onKey(event) {
      if (event.key === "Enter") {
        if (this.chosen === null) return;
        event.preventDefault();
        this.open(this.chosen);
        return;
      }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      event.preventDefault();
      const rows = this.sortedRows;
      if (!rows.length) return;
      const place = rows.findIndex((row) => row.id === this.chosen);
      const next = place < 0 ? 0 : Math.min(Math.max(place + (event.key === "ArrowDown" ? 1 : -1), 0), rows.length - 1);
      this.choose(rows[next].id);
      this.$nextTick(() => {
        const element = this.$refs["row-" + rows[next].id];
        const row = Array.isArray(element) ? element[0] : element;
        if (row) row.scrollIntoView({ block: "nearest", inline: "nearest" });
      });
    },
  },
};
