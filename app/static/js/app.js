/* Build Steward — client glue. Vanilla + Alpine, no build step. */
(function () {
  "use strict";

  // --- Theme -------------------------------------------------------------
  function currentDark() {
    return document.documentElement.classList.contains("dark");
  }

  window.stewardShell = function () {
    return {
      menuOpen: false,
      dark: currentDark(),
      init() {
        this.dark = currentDark();
      },
      toggleTheme() {
        this.dark = !this.dark;
        document.documentElement.classList.toggle("dark", this.dark);
        try { localStorage.setItem("steward-theme", this.dark ? "dark" : "light"); } catch (e) {}
        // persist server-side default (best effort) + refresh charts
        var body = new URLSearchParams({ theme: this.dark ? "dark" : "light" });
        fetch("/api/theme", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body }).catch(function () {});
        window.dispatchEvent(new CustomEvent("steward-theme-changed", { detail: { dark: this.dark } }));
      },
      toast(detail) { window.Steward.toast(detail); },
    };
  };

  // --- Add / edit transaction slide-over ---------------------------------
  window.txnForm = function () {
    return {
      open: false,
      editingId: null,
      type: "expense",
      amount: "", payee: "", account_id: "", transfer_account_id: "",
      category_id: "", note: "", tags: "", date: "",
      splitOn: false, splits: [],
      overrideBudget: false, budgetMonth: "",
      addAnother: false,
      suggestions: [], showSug: false,
      recentPayees: [], recentAmounts: [],
      salaryNote: "",

      init() {
        this.date = (this.$root.dataset.today) || new Date().toISOString().slice(0, 10);
        this.$watch("type", () => this.loadRecents());
      },
      get splitOk() {
        return this.round(this.splitTotal()) === this.round(this.amount || 0);
      },
      round(v) { return Math.round((parseFloat(v) || 0) * 100) / 100; },
      catName(id) { return (window.__stewardCats || {})[id] || ""; },

      reset() {
        this.editingId = null; this.type = "expense"; this.amount = "";
        this.payee = ""; this.account_id = this.$root.dataset.defaultAccount || "";
        this.transfer_account_id = "";
        this.category_id = ""; this.note = ""; this.tags = "";
        this.date = (this.$root.dataset.today) || new Date().toISOString().slice(0, 10);
        this.splitOn = false; this.splits = []; this.overrideBudget = false;
        this.budgetMonth = ""; this.suggestions = []; this.showSug = false; this.salaryNote = "";
      },
      openNew(preset) {
        this.reset();
        // Quick-add into a specific budget category (from the Budget page).
        if (preset && preset.category_id) { this.type = "expense"; this.category_id = String(preset.category_id); }
        if (preset && preset.type) this.type = preset.type;
        if (preset && preset.account_id) this.account_id = String(preset.account_id);
        this.open = true;
        this.loadRecents();
        this.$nextTick(() => this.focusAmount());
      },
      focusAmount() { if (this.$refs.amount) this.$refs.amount.focus(); },

      // Recent-payee / recent-amount quick-entry chips (new transactions only).
      loadRecents() {
        if (this.editingId || this.type === "transfer") {
          this.recentPayees = []; this.recentAmounts = []; return;
        }
        fetch("/transactions/recents?type=" + encodeURIComponent(this.type))
          .then(function (r) { return r.json(); })
          .then((d) => { this.recentPayees = d.payees || []; this.recentAmounts = d.amounts || []; })
          .catch(() => {});
      },
      amtLabel(v) {
        var n = parseFloat(v);
        if (isNaN(n)) return v;
        return "₹" + n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
      },
      pickAmount(v) { this.amount = String(v); this.focusAmount(); },

      openEdit(id) {
        fetch("/transactions/" + id + "/json").then(function (r) { return r.json(); })
          .then((d) => {
            this.reset();
            this.editingId = d.id; this.type = d.type; this.amount = d.amount;
            this.payee = d.payee; this.account_id = d.account_id || "";
            this.transfer_account_id = d.transfer_account_id || "";
            this.category_id = d.category_id || ""; this.note = d.note; this.tags = d.tags;
            this.date = d.date;
            if (d.splits && d.splits.length) {
              this.splitOn = true;
              this.splits = d.splits.map(function (s) { return { category_id: s.category_id || "", amount: s.amount }; });
            }
            this.open = true;
            this.checkSalary();
          });
      },

      openDuplicate(id) {
        // Pre-fill the form from an existing transaction but save it as a NEW
        // one (editingId stays null), dated today — "log this again".
        fetch("/transactions/" + id + "/json").then(function (r) { return r.json(); })
          .then((d) => {
            this.reset();                       // editingId=null, date=today
            this.type = d.type; this.amount = d.amount;
            this.payee = d.payee; this.account_id = d.account_id || "";
            this.transfer_account_id = d.transfer_account_id || "";
            this.category_id = d.category_id || ""; this.note = d.note; this.tags = d.tags;
            if (d.splits && d.splits.length) {
              this.splitOn = true;
              this.splits = d.splits.map(function (s) { return { category_id: s.category_id || "", amount: s.amount }; });
            }
            this.open = true;
            this.checkSalary();
            this.$nextTick(() => this.focusAmount());
          });
      },

      addSplit() { this.splits.push({ category_id: "", amount: "" }); },
      removeSplit(i) { this.splits.splice(i, 1); if (!this.splits.length) this.splitOn = false; },
      splitTotal() {
        return this.splits.reduce((a, s) => a + (parseFloat(s.amount) || 0), 0).toFixed(2);
      },

      searchPayees() {
        if (this.type === "transfer") { this.showSug = false; return; }
        var q = encodeURIComponent(this.payee || "");
        fetch("/transactions/payees?q=" + q).then(function (r) { return r.json(); })
          .then((list) => { this.suggestions = list; this.showSug = list.length > 0; });
      },
      pickSuggestion(s) {
        this.payee = s.payee;
        if (s.type) this.type = s.type;
        if (s.account_id) this.account_id = s.account_id;
        if (s.category_id && !this.splitOn) this.category_id = s.category_id;
        this.showSug = false;
      },

      checkSalary() {
        this.salaryNote = "";
        if (this.type !== "income" || !this.date || this.overrideBudget) return;
        var win = parseInt(this.$root.dataset.salaryWindow || "7", 10);
        var d = new Date(this.date + "T00:00:00");
        var end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
        var daysLeft = Math.round((end - d) / 86400000);
        if (daysLeft < win) {
          var nm = new Date(d.getFullYear(), d.getMonth() + 1, 1);
          this.salaryNote = "Counts in " + nm.toLocaleString("en", { month: "long" }) + "'s budget";
        }
      },

      beforeSubmit() { /* placeholder for htmx submit hook */ },
      submit() {
        if (this.type === "transfer") {
          if (!this.transfer_account_id) return Steward.toast({ kind: "error", message: "Choose a destination account." });
        }
        if (this.splitOn && !this.splitOk) {
          return Steward.toast({ kind: "error", message: "Splits must add up to the total." });
        }
        this.$refs.form.requestSubmit();
      },
      onSaved(e) {
        if (this.addAnother && !this.editingId) {
          var keepType = this.type, keepAccount = this.account_id, keepDate = this.date;
          this.reset();
          this.type = keepType; this.account_id = keepAccount; this.date = keepDate;
          this.loadRecents();
          this.$nextTick(() => this.focusAmount());
        } else {
          this.open = false;
        }
      },
    };
  };

  // --- Accounts page modal (inline; page-load content = reliable reactivity) --
  window.accountsPage = function () {
    var blank = { id: "", name: "", type: "savings_bank", opening_balance: "0", icon: "🏦", color: "#1E6B4E", sms_identifiers: "" };
    return {
      modalOpen: false,
      form: Object.assign({}, blank),
      openNew() { this.form = Object.assign({}, blank); this.modalOpen = true; },
      openEdit(d) {
        this.form = { id: d.id, name: d.name, type: d.type,
                      opening_balance: String(d.opening_balance), icon: d.icon, color: d.color,
                      sms_identifiers: d.sms_identifiers || "" };
        this.modalOpen = true;
      },
      close() { this.modalOpen = false; },
    };
  };

  // --- Recurring rules page modal ---------------------------------------
  window.recurringPage = function () {
    var blank = {
      id: "", payee: "", amount: "", type: "expense", category_id: "",
      account_id: "", transfer_account_id: "", frequency: "monthly",
      day_of_month: 1, weekday: 0, month_of_year: 1, next_due_date: "",
      mode: "auto_create", note: "", tags: "", active: true,
    };
    return {
      modalOpen: false,
      form: Object.assign({}, blank),
      openNew() { this.form = Object.assign({}, blank, { next_due_date: this.$root.dataset.today }); this.modalOpen = true; },
      openEdit(d) { this.form = Object.assign({}, blank, d); this.modalOpen = true; },
      close() { this.modalOpen = false; },
    };
  };

  // --- Sinking funds page (two modals: goal + allocate) -----------------
  window.fundsPage = function () {
    var blankFund = { id: "", name: "", target_amount: "", target_date: "",
                      icon: "🎯", note: "", saved: "0" };

    // Mirrors timeutil.months_between: whole months, floored at zero. Kept in
    // step with the server on purpose — the modal's preview and the goal card
    // must never quote different figures for the same date.
    function monthsBetween(from, to) {
      var a = from.split("-").map(Number), b = to.split("-").map(Number);
      var diff = (b[0] - a[0]) * 12 + (b[1] - a[1]);
      if (b[2] < a[2]) diff -= 1;
      return Math.max(diff, 0);
    }

    return {
      fundModalOpen: false,
      allocOpen: false,
      spendOpen: false,
      fundForm: Object.assign({}, blankFund),
      alloc: { fundId: "", fundName: "", source: "", amount: "" },
      spend: { fundId: "", name: "", allocs: [], picked: [], amount: "", date: "", payee: "", archive: true },

      /* What the chosen target date costs per month, live while you type, so
         the date can be picked against what you can actually set aside rather
         than discovered after saving. Null when there is nothing to say. */
      get pace() {
        var target = parseFloat(this.fundForm.target_amount);
        var when = this.fundForm.target_date;
        var today = (this.$root && this.$root.dataset.today) || "";
        if (!(target > 0) || !when || !today) return null;

        var remaining = Math.max(target - (parseFloat(this.fundForm.saved) || 0), 0);
        if (remaining <= 0) return { state: "funded" };
        if (when < today) return { state: "past" };

        var months = monthsBetween(today, when);
        if (months < 1) return { state: "now", monthly: this.rupees(remaining) };
        // Rounded up, as funds.fund_status does, so the goal isn't left short.
        return { state: "pace", months: months,
                 monthly: this.rupees(Math.ceil(remaining / months)) };
      },
      rupees(v) { return "₹" + Math.round(v).toLocaleString("en-IN"); },

      openNewFund() { this.fundForm = Object.assign({}, blankFund); this.fundModalOpen = true; },
      openEditFund(d) { this.fundForm = Object.assign({}, blankFund, d); this.fundModalOpen = true; },
      openAllocate(id, name) {
        this.alloc = { fundId: id, fundName: name, source: "", amount: "" };
        this.allocOpen = true;
      },
      openSpend(fund) {
        var today = (this.$root && this.$root.dataset.today) || "";
        var allocs = fund.allocs || [];
        this.spend = {
          fundId: fund.id, name: fund.name, allocs: allocs,
          picked: allocs.map(function (a) { return String(a.id); }),  // all pre-checked
          amount: "", date: today, payee: "", archive: true,
        };
        this.spendOpen = true;
      },
    };
  };

  // --- Mutual funds tab (holding search + SIP NAV autofill) --------------
  window.mfPage = function () {
    return {
      holdingOpen: false,
      txnOpen: false,
      sipOpen: false,
      holding: { id: "", scheme_code: "", scheme_name: "", fund_house: "",
                 plan_type: "direct", asset_type: "equity", goal: "" },
      results: [], searching: false, query: "",
      txn: { holding_id: "", holding_name: "", scheme_code: "", type: "sip",
             date: "", amount: "", nav: "", units: "" },
      sip: { holding_id: "", amount: "", start_date: "", step_up_pct: "", account_id: "" },
      navNote: "",

      openSip() {
        this.sip = { holding_id: "", amount: "", start_date: this.$root.dataset.today,
                     step_up_pct: "", account_id: "" };
        this.sipOpen = true;
      },
      sipProjection() {
        var a = parseFloat(this.sip.amount), s = parseFloat(this.sip.step_up_pct);
        if (!(a > 0) || !(s > 0)) return "";
        var y1 = Math.round(a * (1 + s / 100));
        var y2 = Math.round(a * Math.pow(1 + s / 100, 2));
        return "After step-up: ~₹" + y1.toLocaleString("en-IN") + "/mo in year 2, ~₹" +
               y2.toLocaleString("en-IN") + "/mo in year 3.";
      },

      openHolding() {
        this.holding = { id: "", scheme_code: "", scheme_name: "", fund_house: "",
                         plan_type: "direct", asset_type: "equity", goal: "" };
        this.results = []; this.query = ""; this.holdingOpen = true;
      },
      searchSchemes() {
        if (this.query.trim().length < 3) { this.results = []; return; }
        this.searching = true;
        fetch("/savings/mf/search?q=" + encodeURIComponent(this.query))
          .then(function (r) { return r.json(); })
          .then((list) => { this.results = list; this.searching = false; })
          .catch(() => { this.searching = false; });
      },
      pickScheme(s) {
        this.holding.scheme_code = s.scheme_code;
        this.holding.scheme_name = s.scheme_name;
        this.results = []; this.query = s.scheme_name;
      },

      openTxn(holdingId, name, code) {
        this.txn = { holding_id: holdingId, holding_name: name, scheme_code: code,
                     type: "sip", date: this.$root.dataset.today, amount: "", nav: "", units: "" };
        this.navNote = ""; this.txnOpen = true;
      },
      autofillNav() {
        if (!this.txn.scheme_code || !this.txn.date) return;
        this.navNote = "Fetching NAV…";
        fetch("/savings/mf/nav?code=" + this.txn.scheme_code + "&date=" + this.txn.date)
          .then(function (r) { return r.json(); })
          .then((d) => {
            if (d.ok) {
              this.txn.nav = d.nav; this.computeUnits();
              this.navNote = "NAV on " + d.as_of;
            } else { this.navNote = "NAV unavailable — enter it manually."; }
          })
          .catch(() => { this.navNote = "Couldn't fetch NAV."; });
      },
      computeUnits() {
        var a = parseFloat(this.txn.amount), n = parseFloat(this.txn.nav);
        if (a > 0 && n > 0) this.txn.units = (a / n).toFixed(4);
      },
    };
  };

  // --- Categories management page ---------------------------------------
  window.categoriesPage = function () {
    var blank = { id: "", name: "", kind: "expense", icon: "🏷️", group: "", locked: false };
    return {
      modalOpen: false,
      form: Object.assign({}, blank),
      openNew(kind) { this.form = Object.assign({}, blank, { kind: kind || "expense" }); this.modalOpen = true; },
      openEdit(d) { this.form = Object.assign({}, blank, d); this.modalOpen = true; },
      close() { this.modalOpen = false; },
    };
  };

  // Keyboard: "N" opens the add slide-over (when not typing in a field).
  document.addEventListener("keydown", function (e) {
    if (e.key !== "n" && e.key !== "N") return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
    e.preventDefault();
    window.dispatchEvent(new CustomEvent("open-add"));
  });

  // --- Toasts ------------------------------------------------------------
  var Steward = window.Steward = window.Steward || {};

  Steward.toast = function (opts) {
    if (typeof opts === "string") opts = { message: opts };
    opts = opts || {};
    var host = document.getElementById("toast-host");
    if (!host) return;
    var kind = opts.kind || "info";
    var colors = {
      success: "var(--c-primary)", info: "var(--c-primary)",
      warn: "var(--c-warn)", error: "var(--c-danger)", over: "var(--c-danger)",
    };
    var el = document.createElement("div");
    el.className = "toast flex items-start gap-3";
    el.style.borderLeft = "4px solid rgb(" + (colors[kind] || colors.info) + ")";
    el.innerHTML =
      '<span class="text-lg leading-none">' + (opts.icon || (kind === "error" || kind === "over" ? "⚠️" : kind === "warn" ? "🔔" : "✅")) + "</span>" +
      '<div class="min-w-0 flex-1">' +
        (opts.title ? '<div class="font-medium text-sm">' + escapeHtml(opts.title) + "</div>" : "") +
        '<div class="text-sm muted">' + escapeHtml(opts.message || "") + "</div>" +
      "</div>" +
      '<button class="muted hover:text-ink text-sm" aria-label="Dismiss">✕</button>';
    el.style.transition = "opacity .2s ease, transform .2s ease";
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    host.appendChild(el);
    requestAnimationFrame(function () { el.style.opacity = "1"; el.style.transform = "none"; });
    var close = function () {
      el.style.opacity = "0"; el.style.transform = "translateY(6px)";
      setTimeout(function () { el.remove(); }, 220);
    };
    el.querySelector("button").addEventListener("click", close);
    if (opts.timeout !== 0) setTimeout(close, opts.timeout || 4500);
  };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // htmx triggers toasts via response header HX-Trigger: {"steward-toast": {...}}.
  // A window-level listener catches the bubbled event regardless of Alpine/htmx
  // wiring on any particular element.
  window.addEventListener("steward-toast", function (e) {
    if (!e || !e.detail) return;
    if (Array.isArray(e.detail)) e.detail.forEach(function (d) { d && Steward.toast(d); });
    else Steward.toast(e.detail);
  });

  // --- Chart helpers -----------------------------------------------------
  // CSS var()s do NOT resolve inside SVG attributes ApexCharts emits, so we
  // read computed values to concrete colours before handing them to Apex.
  Steward.cssColor = function (name) {
    var raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    if (!raw) return "#1E6B4E";
    // tokens are "R G B" channel triplets
    if (/^\d+\s+\d+\s+\d+$/.test(raw)) return "rgb(" + raw + ")";
    return raw;
  };

  Steward.palette = function () {
    return {
      primary: Steward.cssColor("--c-primary"),
      primaryStrong: Steward.cssColor("--c-primary-strong"),
      gold: Steward.cssColor("--c-gold"),
      danger: Steward.cssColor("--c-danger"),
      ink: Steward.cssColor("--c-ink"),
      inkSoft: Steward.cssColor("--c-ink-soft"),
      border: Steward.cssColor("--c-border"),
      surface: Steward.cssColor("--c-surface"),
    };
  };

  Steward.baseChartOptions = function () {
    var p = Steward.palette();
    return {
      chart: { fontFamily: "system-ui, Segoe UI, sans-serif", foreColor: p.inkSoft,
               toolbar: { show: false }, animations: { easing: "easeinout", speed: 500 } },
      grid: { borderColor: p.border, strokeDashArray: 4 },
      tooltip: { theme: currentDark() ? "dark" : "light" },
      dataLabels: { enabled: false },
      legend: { labels: { colors: p.inkSoft } },
    };
  };

  // Sparkline for the summary strip.
  Steward.sparkline = function (el, data) {
    if (!el || !window.ApexCharts) return;
    var p = Steward.palette();
    var chart = new ApexCharts(el, {
      chart: { type: "area", height: 44, sparkline: { enabled: true },
               animations: { enabled: true, speed: 400 } },
      stroke: { curve: "smooth", width: 2 },
      series: [{ data: data }],
      colors: [p.primary],
      fill: { type: "gradient", gradient: { opacityFrom: 0.35, opacityTo: 0 } },
      tooltip: { enabled: false },
    });
    chart.render();
    el._chart = chart;
    return chart;
  };

  // Categorical palette for multi-series charts (one per net-worth bucket).
  Steward.categorical = function () {
    var dark = currentDark();
    return dark
      ? ["#47BB8D", "#E2B45C", "#5FBFA9", "#E08A5B", "#9AA3AE", "#A78BFA", "#F0C674"]
      : ["#1E6B4E", "#B08014", "#3D8F7B", "#C2703D", "#6B7280", "#7C4DD6", "#C79A2E"];
  };

  Steward.inr = function (v) {
    v = Math.round(v);
    if (Math.abs(v) >= 10000000) return "₹" + (v / 10000000).toFixed(2) + "Cr";
    if (Math.abs(v) >= 100000) return "₹" + (v / 100000).toFixed(2) + "L";
    if (Math.abs(v) >= 1000) return "₹" + (v / 1000).toFixed(1) + "k";
    return "₹" + v;
  };

  function mount(el, opts) {
    if (!el || !window.ApexCharts) return null;
    if (el._chart) { try { el._chart.destroy(); } catch (e) {} }
    el._chart = new ApexCharts(el, opts);
    el._chart.render();
    return el._chart;
  }

  Steward.donut = function (el, labels, values) {
    return mount(el, Object.assign(Steward.baseChartOptions(), {
      chart: { type: "donut", height: 300 },
      series: values, labels: labels, colors: Steward.categorical(),
      legend: { position: "bottom", labels: { colors: Steward.palette().inkSoft } },
      plotOptions: { pie: { donut: { size: "68%", labels: { show: true,
        total: { show: true, label: "Total", formatter: function (w) {
          return Steward.inr(w.globals.seriesTotals.reduce(function (a, b) { return a + b; }, 0)); } } } } } },
      tooltip: { y: { formatter: Steward.inr } }, stroke: { width: 0 },
    }));
  };

  Steward.areaTrend = function (el, dates, totals) {
    var p = Steward.palette();
    return mount(el, Object.assign(Steward.baseChartOptions(), {
      chart: { type: "area", height: 320, toolbar: { show: false } },
      series: [{ name: "Net worth", data: totals }],
      xaxis: { type: "datetime", categories: dates },
      yaxis: { labels: { formatter: Steward.inr } },
      colors: [p.primary], stroke: { curve: "smooth", width: 2.5 },
      fill: { type: "gradient", gradient: { opacityFrom: 0.35, opacityTo: 0.02 } },
      tooltip: { x: { format: "dd MMM yyyy" }, y: { formatter: Steward.inr } },
    }));
  };

  Steward.stackedArea = function (el, dates, seriesList) {
    return mount(el, Object.assign(Steward.baseChartOptions(), {
      chart: { type: "area", height: 320, stacked: true, toolbar: { show: false } },
      series: seriesList,
      xaxis: { type: "datetime", categories: dates },
      yaxis: { labels: { formatter: Steward.inr } },
      colors: Steward.categorical(), stroke: { curve: "smooth", width: 1 },
      fill: { type: "gradient", gradient: { opacityFrom: 0.55, opacityTo: 0.15 } },
      legend: { position: "bottom" },
      tooltip: { x: { format: "dd MMM yyyy" }, y: { formatter: Steward.inr } },
    }));
  };

  Steward.barChart = function (el, categories, seriesList, opts) {
    opts = opts || {};
    return mount(el, Object.assign(Steward.baseChartOptions(), {
      chart: { type: "bar", height: opts.height || 320, toolbar: { show: false } },
      series: seriesList,
      xaxis: { categories: categories },
      yaxis: { labels: { formatter: Steward.inr } },
      colors: opts.colors || Steward.categorical(),
      plotOptions: { bar: { borderRadius: 4, columnWidth: opts.horizontal ? "70%" : "55%", horizontal: !!opts.horizontal } },
      legend: { position: "bottom" },
      tooltip: { y: { formatter: Steward.inr } },
    }));
  };

  // Re-theme charts when the theme flips.
  window.addEventListener("steward-theme-changed", function () {
    if (window.ApexCharts && ApexCharts.exec) { /* charts re-read on next render */ }
  });

  // --- Global htmx loading bar ------------------------------------------
  function ensureBar() {
    var bar = document.getElementById("steward-loadbar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "steward-loadbar";
      document.body.appendChild(bar);
    }
    return bar;
  }
  var pending = 0;
  document.addEventListener("htmx:beforeRequest", function () {
    pending++;
    var bar = ensureBar();
    bar.classList.add("on");
  });
  function done() {
    pending = Math.max(0, pending - 1);
    if (pending === 0) {
      var bar = document.getElementById("steward-loadbar");
      if (bar) bar.classList.remove("on");
    }
  }
  document.addEventListener("htmx:afterRequest", done);
  document.addEventListener("htmx:responseError", done);
  document.addEventListener("htmx:sendError", function () {
    done();
    Steward.toast({ kind: "error", message: "Network error — please try again." });
  });

  // --- Accessibility: associate <label class="field-label"> with its control -
  // Links label -> input via for/id so clicking a label focuses its field and
  // screen readers announce them together. Runs on load and after htmx swaps.
  function associateLabels(root) {
    root = root || document;
    var labels = root.querySelectorAll ? root.querySelectorAll("label.field-label:not([for])") : [];
    labels.forEach(function (label) {
      if (label.querySelector("input, select, textarea")) return; // already wraps a control
      var parent = label.parentElement;
      var control = parent && parent.querySelector("input, select, textarea");
      if (control) {
        if (!control.id) control.id = "f_" + Math.random().toString(36).slice(2, 9);
        label.setAttribute("for", control.id);
      }
    });
  }
  document.addEventListener("DOMContentLoaded", function () { associateLabels(document); });
  document.addEventListener("htmx:afterSettle", function (e) { associateLabels(e.target || document); });
  // The add-transaction slide-over is Alpine-rendered; re-scan when it opens.
  window.addEventListener("open-add", function () { setTimeout(function () { associateLabels(document); }, 60); });
  window.addEventListener("open-edit", function () { setTimeout(function () { associateLabels(document); }, 60); });

  // --- Service worker (PWA install support) -----------------------------
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/static/sw.js").catch(function () {});
    });
  }
})();
