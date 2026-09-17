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

async function main() {
  const status = document.getElementById("status");
  const cardsEl = document.getElementById("cards");
  try {
    const data = await fetchJSON("../data/watchlist.json");
    status.textContent = `Last updated: ${data.generated_at} · ${data.companies.length} companies tracked`;
    cardsEl.innerHTML = renderBySector(data.companies);
  } catch (err) {
    renderError(cardsEl, `Could not load watchlist data (${err.message}). Has the pipeline run yet?`);
    status.textContent = "";
  }
  renderDisclaimerFooter();
}

function renderBySector(companies) {
  const bySector = new Map();
  for (const company of companies) {
    const sector = company.sector || "Uncategorized";
    if (!bySector.has(sector)) bySector.set(sector, []);
    bySector.get(sector).push(company);
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
          <div class="card-grid">${bySector.get(sector).map(renderCard).join("")}</div>
        </section>
      `
    )
    .join("");
}

function renderCard(company) {
  const ticker = escapeHtml(company.ticker);
  const grahamBadge =
    company.graham_criteria_total
      ? `<span class="mini-badge" title="Graham defensive-investor criteria passed">Graham ${company.graham_criteria_passed}/${company.graham_criteria_total}</span>`
      : "";
  const piotroskiBadge =
    company.piotroski_f_score !== undefined && company.piotroski_f_score !== null
      ? `<span class="mini-badge" title="Piotroski F-Score">F-Score ${company.piotroski_f_score}/9</span>`
      : "";
  return `
    <a class="card" href="company.html?ticker=${encodeURIComponent(company.ticker)}">
      <div class="card-header">
        <span class="ticker">${ticker}</span>
        <span class="name">${escapeHtml(company.name)}</span>
      </div>
      <div class="verdicts">
        <span class="verdict-badge ${verdictClass(company.short_term_verdict)}">
          Short-term: ${escapeHtml(company.short_term_verdict)} (${formatNumber(company.short_term_score, { decimals: 0 })})
        </span>
        <span class="verdict-badge ${verdictClass(company.long_term_verdict)}">
          Long-term: ${escapeHtml(company.long_term_verdict)} (${formatNumber(company.long_term_score, { decimals: 0 })})
        </span>
      </div>
      <div class="mini-badges">${grahamBadge}${piotroskiBadge}</div>
      <p class="summary">${escapeHtml(company.one_line_summary) || "No AI summary available yet."}</p>
    </a>
  `;
}

main();
