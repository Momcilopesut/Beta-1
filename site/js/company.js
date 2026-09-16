import { fetchJSON, verdictClass, formatNumber, escapeHtml, renderDisclaimerFooter } from "./shared.js";

function tickerFromQuery() {
  return new URLSearchParams(window.location.search).get("ticker");
}

async function main() {
  const content = document.getElementById("content");
  const ticker = tickerFromQuery();

  if (!ticker) {
    content.innerHTML = `<p class="error">No ticker specified. Go back to the <a href="index.html">watchlist</a>.</p>`;
    renderDisclaimerFooter();
    return;
  }

  document.title = `${ticker} – Company Detail`;

  try {
    const doc = await fetchJSON(`../data/companies/${encodeURIComponent(ticker)}.json`);
    content.innerHTML = render(doc);
  } catch (err) {
    const safeTicker = escapeHtml(ticker);
    content.innerHTML = `<p class="error">Could not load data for ${safeTicker} (${escapeHtml(err.message)}).</p>`;
  }
  renderDisclaimerFooter();
}

function render(doc) {
  return `
    <section class="detail-header">
      <h2>${escapeHtml(doc.name)} <span class="ticker-tag">${escapeHtml(doc.ticker)}</span></h2>
      <p class="meta">${escapeHtml(doc.sector || "—")} · ${escapeHtml(doc.industry || "—")} · Updated ${escapeHtml(doc.last_updated)}</p>
    </section>

    <section class="verdicts-detail">
      ${renderScoreCard("Short-Term", doc.scores.short_term)}
      ${renderScoreCard("Long-Term", doc.scores.long_term)}
    </section>

    <section class="narrative">
      <h3>AI Summary</h3>
      <p class="one-liner">${escapeHtml(doc.narrative.one_line_summary) || "Not yet generated — run the pipeline without --skip-ai."}</p>
      <p>${escapeHtml(doc.narrative.short_term_narrative)}</p>
      <p>${escapeHtml(doc.narrative.long_term_narrative)}</p>
    </section>

    <section class="facts">
      <h3>What Matters</h3>
      ${renderFactTier("Critical", doc.narrative.facts.critical, true)}
      ${renderFactTier("Important", doc.narrative.facts.important, true)}
      ${renderFactTier("Minor", doc.narrative.facts.minor, false)}
      ${renderFactTier("Noise (safe to ignore)", doc.narrative.facts.noise, false)}
    </section>

    <section class="breakdown">
      <h3>Score Breakdown</h3>
      ${renderSubscoreTable("Short-Term", doc.scores.short_term)}
      ${renderSubscoreTable("Long-Term", doc.scores.long_term)}
    </section>

    <section class="macro">
      <h3>Macro Context</h3>
      <p>Regime: <strong>${escapeHtml(doc.macro_context.regime)}</strong></p>
      <p>Sector sensitivity: rate = ${escapeHtml(doc.macro_context.sector_sensitivity.rate_sensitivity)}, cyclicality = ${escapeHtml(doc.macro_context.sector_sensitivity.cyclicality)}</p>
      <p><a href="macro.html">See full macro overview &rarr;</a></p>
    </section>

    <section class="sources">
      <h3>Sources</h3>
      <ul>
        ${(doc.sources.sec_filings || [])
          .map(
            (f) =>
              `<li><a href="${escapeHtml(f.url)}" target="_blank" rel="noopener">${escapeHtml(f.form)} filed ${escapeHtml(f.filed)}</a></li>`
          )
          .join("")}
        ${
          doc.sources.sec_companyfacts_url
            ? `<li><a href="${escapeHtml(doc.sources.sec_companyfacts_url)}" target="_blank" rel="noopener">SEC XBRL company facts (raw)</a></li>`
            : ""
        }
      </ul>
    </section>
  `;
}

function renderScoreCard(label, score) {
  const sign = score.macro_adjustment >= 0 ? "+" : "";
  return `
    <div class="score-card ${verdictClass(score.verdict)}">
      <h3>${label}</h3>
      <p class="score-value">${formatNumber(score.final_score, { decimals: 0 })}</p>
      <p class="verdict-label">${escapeHtml(score.verdict)}</p>
      <p class="score-note">Base ${formatNumber(score.base_score, { decimals: 0 })}, ${sign}${score.macro_adjustment} macro</p>
    </div>
  `;
}

function renderFactTier(label, facts, expanded) {
  if (!facts || facts.length === 0) return "";
  const items = facts
    .map(
      (f) =>
        `<li><span class="fact-text">${escapeHtml(f.text)}</span> <span class="fact-source">(${escapeHtml(f.source_metric)}: ${escapeHtml(f.source_value)})</span></li>`
    )
    .join("");
  return `
    <details ${expanded ? "open" : ""}>
      <summary>${label} (${facts.length})</summary>
      <ul>${items}</ul>
    </details>
  `;
}

function renderSubscoreTable(label, score) {
  const rows = score.subscores
    .map(
      (sub) => `
    <tr>
      <td>${escapeHtml(sub.label)}</td>
      <td>${sub.weight_pct}%</td>
      <td>${formatNumber(sub.score, { decimals: 0 })}</td>
      <td>${sub.raw_metrics
        .map((m) => `${escapeHtml(m.metric)}: ${m.raw_value === null ? "—" : escapeHtml(m.raw_value)}`)
        .join(", ")}</td>
    </tr>`
    )
    .join("");
  return `
    <h4>${label}</h4>
    <table class="subscore-table">
      <thead><tr><th>Component</th><th>Weight</th><th>Score</th><th>Raw inputs</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

main();
