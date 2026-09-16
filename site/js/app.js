import { fetchJSON, verdictClass, formatNumber, escapeHtml, renderDisclaimerFooter, renderError } from "./shared.js";

async function main() {
  const status = document.getElementById("status");
  const cardsEl = document.getElementById("cards");
  try {
    const data = await fetchJSON("../data/watchlist.json");
    status.textContent = `Last updated: ${data.generated_at} · ${data.companies.length} companies tracked`;
    cardsEl.innerHTML = data.companies.map(renderCard).join("");
  } catch (err) {
    renderError(cardsEl, `Could not load watchlist data (${err.message}). Has the pipeline run yet?`);
    status.textContent = "";
  }
  renderDisclaimerFooter();
}

function renderCard(company) {
  const ticker = escapeHtml(company.ticker);
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
      <p class="summary">${escapeHtml(company.one_line_summary) || "No AI summary available yet."}</p>
    </a>
  `;
}

main();
