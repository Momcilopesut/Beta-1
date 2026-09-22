import { fetchJSON, verdictClass, formatNumber, escapeHtml, renderDisclaimerFooter, renderError } from "./shared.js";

// Canonical GICS-style sector order (Energy -> Real Estate), so sections
// appear in the same order finance convention uses rather than
// alphabetically or by watchlist order.
const SECTOR_ORDER = [
  "Energy",
  "Basic Materials",
  "Industrials",
  "Consumer Cyclical",
  "Consumer Defensive",
  "Healthcare",
  "Financial Services",
  "Technology",
  "Communication Services",
  "Utilities",
  "Real Estate",
];

let allCompanies = [];
let performancePicksBySector = {};
let performanceWindows = [];

async function main() {
  const status = document.getElementById("status");
  const cardsEl = document.getElementById("cards");
  try {
    const [picks, watchlist] = await Promise.all([
      fetchJSON("../data/performance_picks.json"),
      fetchJSON("../data/watchlist.json"),
    ]);
    performancePicksBySector = picks.picks_by_sector;
    performanceWindows = picks.windows;
    allCompanies = watchlist.companies;
    const pickCount = Object.values(performancePicksBySector).reduce(
      (sum, windows) => sum + Object.values(windows).reduce((s, list) => s + list.length, 0),
      0
    );
    status.textContent = pickCount
      ? `Top ${picks.top_n_per_sector} performers per sector, across 5 timeframes, from a screen of ${picks.universe_size} companies · generated ${picks.generated_at}`
      : `Screened ${picks.universe_size} companies · generated ${picks.generated_at} · no performance data yet`;
    cardsEl.innerHTML = pickCount ? renderPerformanceScreen(performancePicksBySector, performanceWindows) : renderNoPicksYet();
  } catch (err) {
    renderError(cardsEl, `Could not load this week's top performers (${err.message}). Has the pipeline run yet?`);
    status.textContent = "";
  }
  renderDisclaimerFooter();
  wireSearch();
}

function renderNoPicksYet() {
  return `<p class="status">No sector had a company with enough price history to rank yet. Check back after the pipeline's next run, or search for any ticker above.</p>`;
}

function wireSearch() {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  const cardsEl = document.getElementById("cards");
  if (!form || !input) return;

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    if (!query) {
      cardsEl.innerHTML = Object.keys(performancePicksBySector).length
        ? renderPerformanceScreen(performancePicksBySector, performanceWindows)
        : renderNoPicksYet();
      return;
    }
    const matches = allCompanies.filter(
      (c) => c.ticker.toLowerCase().includes(query) || c.name.toLowerCase().includes(query)
    );
    cardsEl.innerHTML = matches.length
      ? renderBySector(matches)
      : `<p class="status">No tracked company matches "${escapeHtml(input.value.trim())}". Press Enter to run a live lookup instead.</p>`;
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    // Jump straight to a single tracked match; otherwise go to the ticker
    // as typed - company.html resolves it statically if tracked, or offers
    // a live lookup if not.
    const exact = allCompanies.find((c) => c.ticker.toLowerCase() === query.toLowerCase());
    const target = exact ? exact.ticker : query.toUpperCase();
    window.location.href = `company.html?ticker=${encodeURIComponent(target)}`;
  });
}

// Search results: grouped by sector, re-sorted by Investment Meter score -
// an arbitrary subset matching the query, not the performance screen, so it
// keeps showing the fundamentals badges rather than a rank-by-return list.
function renderBySector(companies) {
  const bySector = new Map();
  for (const company of companies) {
    const sector = company.sector || "Uncategorized";
    if (!bySector.has(sector)) bySector.set(sector, []);
    bySector.get(sector).push(company);
  }

  // Highest Conviction Score first within each sector - companies without
  // enough data for a score (null) sort last rather than crashing the compare.
  for (const list of bySector.values()) {
    list.sort((a, b) => (b.conviction_score ?? -1) - (a.conviction_score ?? -1));
  }

  const orderedSectors = [
    ...SECTOR_ORDER.filter((s) => bySector.has(s)),
    ...[...bySector.keys()].filter((s) => !SECTOR_ORDER.includes(s)).sort(),
  ];

  return orderedSectors
    .map(
      (sector) => `
        <section class="sector-group">
          <h2 class="sector-heading">${escapeHtml(sector)} <span class="sector-count">(${bySector.get(sector).length})</span></h2>
          <div class="card-grid">${bySector.get(sector).map((c) => renderCard(c)).join("")}</div>
        </section>
      `
    )
    .join("");
}

// Default homepage view: for each sector, 5 independently-ranked leaderboards
// (one per pipeline.scoring.performance.WINDOWS entry) - pure price return,
// already ranked and capped by select_top_performers, rendered in that order
// with #1/#2/... rank position, not re-sorted here.
function renderPerformanceScreen(picksBySector, windows) {
  const orderedSectors = [
    ...SECTOR_ORDER.filter((s) => picksBySector[s]),
    ...Object.keys(picksBySector)
      .filter((s) => !SECTOR_ORDER.includes(s))
      .sort(),
  ];

  return orderedSectors
    .map(
      (sector) => `
        <section class="sector-group">
          <h2 class="sector-heading">${escapeHtml(sector)}</h2>
          <div class="perf-grid">
            ${windows.map((w) => renderPerfPanel(w, picksBySector[sector][w.key])).join("")}
          </div>
        </section>
      `
    )
    .join("");
}

function renderPerfPanel(perfWindow, picks) {
  const rows = (picks || []).length
    ? picks.map((c, i) => renderPerfRow(c, i + 1, perfWindow.key)).join("")
    : `<li class="perf-empty">Not enough data yet</li>`;
  return `
    <div class="perf-panel">
      <p class="perf-panel-title">${escapeHtml(perfWindow.label)}</p>
      <ol class="perf-list">${rows}</ol>
    </div>
  `;
}

function fmtReturn(pct) {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${formatNumber(pct, { decimals: 1, suffix: "%" })}`;
}

function renderPerfRow(company, rank, windowKey) {
  const pct = company.returns?.[windowKey];
  const hasPct = pct !== null && pct !== undefined;
  const direction = hasPct ? (pct > 0 ? "perf-up" : pct < 0 ? "perf-down" : "") : "";
  const returnText = hasPct ? fmtReturn(pct) : "—";
  const price = company.price?.close;
  const priceLine =
    price !== undefined && price !== null
      ? `<span class="perf-price">$${formatNumber(price, { decimals: 2 })}</span>`
      : "";
  return `
    <li class="perf-row">
      <a href="company.html?ticker=${encodeURIComponent(company.ticker)}">
        <span class="perf-rank">${rank}</span>
        <span class="perf-id">
          <span class="perf-ticker">${escapeHtml(company.ticker)}</span>
          <span class="perf-name">${escapeHtml(company.name)}</span>
        </span>
        <span class="perf-metrics">
          <span class="perf-return ${direction}">${returnText}</span>
          ${priceLine}
        </span>
      </a>
    </li>
  `;
}

function renderCard(company) {
  const ticker = escapeHtml(company.ticker);
  const grahamBadge =
    company.graham_criteria_total
      ? `<span class="mini-badge" title="Graham defensive-investor criteria passed">Graham ${company.graham_criteria_passed}/${company.graham_criteria_total}</span>`
      : "";
  const mungerBadge =
    company.munger_quality_total !== undefined && company.munger_quality_total !== null
      ? `<span class="mini-badge" title="Munger quality checklist (return on equity, debt, dilution, margins)">Munger ${company.munger_quality_passed}/${company.munger_quality_total}</span>`
      : "";
  const bookValueBadge =
    company.book_value_per_share !== undefined && company.book_value_per_share !== null
      ? `<span class="mini-badge" title="Net worth per share (assets minus liabilities)">Book value $${formatNumber(company.book_value_per_share, { decimals: 2 })}</span>`
      : "";
  const layeredBadge = renderLayeredBadge(company);
  const hasConviction = company.conviction_score !== null && company.conviction_score !== undefined;
  const convictionBadge = hasConviction
    ? `<span class="verdict-badge conviction-badge ${verdictClass(company.conviction_verdict)}">
        Meter: ${escapeHtml(company.conviction_verdict)} (${formatNumber(company.conviction_score, { decimals: 0 })})
      </span>`
    : `<span class="verdict-badge conviction-badge verdict-neutral">Meter: not enough data</span>`;
  const price = company.price?.close;
  const priceLine =
    price !== undefined && price !== null
      ? `<p class="card-price">$${formatNumber(price, { decimals: 2 })}</p>`
      : "";
  return `
    <a class="card" href="company.html?ticker=${encodeURIComponent(company.ticker)}">
      <div class="card-header">
        <span class="ticker-group"><span class="ticker">${ticker}</span></span>
        <span class="name">${escapeHtml(company.name)}</span>
      </div>
      ${priceLine}
      <div class="verdicts">
        ${convictionBadge}
      </div>
      <div class="mini-badges">${grahamBadge}${mungerBadge}${bookValueBadge}${layeredBadge}</div>
    </a>
  `;
}

function renderLayeredBadge(company) {
  const {
    qualitative_moat_present: moat,
    munger_quality_pass: munger,
    valuation_gate_pass: value,
  } = company;
  if (moat === undefined && munger === undefined && value === undefined) return "";
  const parts = [];
  if (munger === true) parts.push("munger");
  if (moat === true) parts.push("moat (Buffett)");
  if (value === true) parts.push("value");
  if (!parts.length) return `<span class="mini-badge" title="Layered analysis: no gates passed yet">layered: —</span>`;
  return `<span class="mini-badge" title="Layered analysis gates passed">${escapeHtml(parts.join(" + "))} ✓</span>`;
}

main();
