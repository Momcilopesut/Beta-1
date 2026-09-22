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
let weeklyPicksBySector = {};

async function main() {
  const status = document.getElementById("status");
  const cardsEl = document.getElementById("cards");
  try {
    const [picks, watchlist] = await Promise.all([
      fetchJSON("../data/weekly_picks.json"),
      fetchJSON("../data/watchlist.json"),
    ]);
    weeklyPicksBySector = picks.picks_by_sector;
    allCompanies = watchlist.companies;
    const pickCount = Object.values(weeklyPicksBySector).reduce((sum, list) => sum + list.length, 0);
    status.textContent = pickCount
      ? `This week's top ${picks.top_n_per_sector} per sector, from a screen of ${picks.universe_size} companies · generated ${picks.generated_at}`
      : `Screened ${picks.universe_size} companies · generated ${picks.generated_at} · no confident picks yet`;
    cardsEl.innerHTML = pickCount ? renderWeeklyPicks(weeklyPicksBySector) : renderNoPicksYet();
  } catch (err) {
    renderError(cardsEl, `Could not load this week's picks (${err.message}). Has the pipeline run yet?`);
    status.textContent = "";
  }
  renderDisclaimerFooter();
  wireSearch();
}

function renderNoPicksYet() {
  return `<p class="status">No sector had a company with enough data to rank yet. Check back after the pipeline's next run, or search for any ticker above.</p>`;
}

function wireSearch() {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  const cardsEl = document.getElementById("cards");
  if (!form || !input) return;

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    if (!query) {
      cardsEl.innerHTML = Object.keys(weeklyPicksBySector).length ? renderWeeklyPicks(weeklyPicksBySector) : renderNoPicksYet();
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

// Search results: grouped by sector, re-sorted by score - an arbitrary
// subset matching the query, not this week's ranked picks, so no rank badges.
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

// Default homepage view: this week's top picks, already ranked and capped
// per sector by pipeline.scoring.screening.select_top_picks - rendered in
// that order with a #1/#2/... rank badge, not re-sorted here.
function renderWeeklyPicks(picksBySector) {
  const orderedSectors = [
    ...SECTOR_ORDER.filter((s) => picksBySector[s]?.length),
    ...Object.keys(picksBySector)
      .filter((s) => !SECTOR_ORDER.includes(s) && picksBySector[s]?.length)
      .sort(),
  ];

  return orderedSectors
    .map(
      (sector) => `
        <section class="sector-group">
          <h2 class="sector-heading">${escapeHtml(sector)} <span class="sector-count">(top ${picksBySector[sector].length})</span></h2>
          <div class="card-grid">${picksBySector[sector].map((c, i) => renderCard(c, i + 1)).join("")}</div>
        </section>
      `
    )
    .join("");
}

function renderCard(company, rank) {
  const ticker = escapeHtml(company.ticker);
  const rankBadge = rank ? `<span class="mini-badge pick-rank">#${rank}</span>` : "";
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
  return `
    <a class="card" href="company.html?ticker=${encodeURIComponent(company.ticker)}">
      <div class="card-header">
        <span class="ticker-group">${rankBadge}<span class="ticker">${ticker}</span></span>
        <span class="name">${escapeHtml(company.name)}</span>
      </div>
      <div class="verdicts">
        ${convictionBadge}
      </div>
      <div class="mini-badges">${grahamBadge}${mungerBadge}${bookValueBadge}${layeredBadge}</div>
      <p class="summary">${escapeHtml(company.one_line_summary) || "No AI summary available yet."}</p>
    </a>
  `;
}

function renderLayeredBadge(company) {
  const {
    quant_gate_pass: quant,
    qualitative_moat_present: moat,
    munger_quality_pass: munger,
    valuation_gate_pass: value,
  } = company;
  if (quant === undefined && moat === undefined && munger === undefined && value === undefined) return "";
  const parts = [];
  if (quant === true) parts.push("quant");
  if (munger === true) parts.push("munger");
  if (moat === true) parts.push("moat");
  if (value === true) parts.push("value");
  if (!parts.length) return `<span class="mini-badge" title="Layered analysis: no gates passed yet">layered: —</span>`;
  return `<span class="mini-badge" title="Layered analysis gates passed">${escapeHtml(parts.join(" + "))} ✓</span>`;
}

main();
