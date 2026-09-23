import { fetchJSON, escapeHtml, renderDisclaimerFooter } from "./shared.js";
import { macroGlossaryEntry } from "./macro-glossary.js";

async function main() {
  const content = document.getElementById("content");
  try {
    const doc = await fetchJSON("../data/macro.json");
    content.innerHTML = render(doc);
  } catch (err) {
    content.innerHTML = `<p class="error">Could not load macro data (${escapeHtml(err.message)}). Has the pipeline run yet?</p>`;
  }
  renderDisclaimerFooter();
}

function render(doc) {
  const seriesHtml = (doc.series || []).map(renderSeriesCard).join("");
  return `
    <section class="regime">
      <h2>Current Macro Regime: <span class="regime-tag">${escapeHtml(doc.regime)}</span></h2>
      <p class="meta">Updated ${escapeHtml(doc.generated_at)}</p>
    </section>
    ${renderCycleContext(doc.cycle_context)}
    ${renderCapitalEfficiency(doc.capital_efficiency)}
    <section class="series-grid">${seriesHtml}</section>
  `;
}

const CE_STATS = [
  {
    key: "roic_pct",
    sentimentKey: "roic",
    label: "Return on Invested Capital (ROIC)",
    explanation:
      "Aggregate after-tax operating profit (NOPAT) divided by aggregate invested capital, summed across every " +
      "tracked company's latest statements. How efficiently this universe turns the capital it's been given into profit.",
  },
  {
    key: "reinvestment_rate_pct",
    sentimentKey: "reinvestment_rate",
    label: "Reinvestment Rate",
    explanation:
      "The share of NOPAT plowed back into the businesses (CapEx minus depreciation, plus the change in working " +
      "capital) rather than available for dividends or buybacks. Neither high nor low is inherently good - what " +
      "matters is how much growth that reinvestment is actually buying (see Expected Growth).",
  },
  {
    key: "expected_growth_pct",
    sentimentKey: "expected_growth",
    label: "Expected Growth",
    explanation:
      "ROIC x Reinvestment Rate - the fundamental, organic earnings growth this reinvestment should buy. The same " +
      "growth rate achieved with a lower reinvestment rate (a higher ROIC) is the stronger outcome, since it " +
      "leaves more free cash flow for dividends or buybacks.",
  },
  {
    key: "wacc_pct",
    sentimentKey: "wacc",
    label: "Cost of Capital (WACC)",
    explanation:
      "A simplified weighted-average cost of capital: the 10-year Treasury yield plus a configured equity risk " +
      "premium (cost of equity, beta assumed at 1.0 - this is being measured against the market itself), blended " +
      "with an after-tax cost of debt, weighted by aggregate market cap vs. aggregate debt.",
  },
  {
    key: "value_creation_pct",
    sentimentKey: "value_creation",
    label: "Value Creation (ROIC − WACC)",
    explanation:
      "Positive means this universe is earning more on its capital than that capital costs - creating value, even " +
      "if earnings per share growth alone might have suggested otherwise. Negative means the opposite: it's " +
      "destroying value regardless of how fast earnings are growing.",
  },
];

function renderCapitalEfficiency(ce) {
  if (!ce) return "";
  const sentiment = ce.sentiment || {};
  const cards = CE_STATS.map((stat) => {
    const value = ce[stat.key];
    const valueText = value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
    const sentimentClass = sentiment[stat.sentimentKey] ? ` metric-value-${sentiment[stat.sentimentKey]}` : "";
    return `
      <div class="ce-card">
        <h4>${escapeHtml(stat.label)}</h4>
        <p class="ce-value${sentimentClass}">${valueText}</p>
        <p class="ce-explanation">${escapeHtml(stat.explanation)}</p>
      </div>
    `;
  }).join("");

  return `
    <section class="capital-efficiency">
      <h3>Market Capital Efficiency</h3>
      <p class="meta">Bottom-up, computed from ${ce.companies_covered} tracked companies' own latest financial
      statements - no aggregate data vendor (Compustat, FactSet, Bloomberg) needed, since every one of these
      companies' statements is already fetched here every run. See each card for what it measures and why.</p>
      <div class="ce-grid">${cards}</div>
    </section>
  `;
}

function renderCycleContext(cycle) {
  if (!cycle) return "";
  const favored = (cycle.historically_favored_sectors || []).map(escapeHtml).join(", ");
  const lagging = (cycle.historically_lagging_sectors || []).map(escapeHtml).join(", ");
  return `
    <section class="cycle-context">
      <h3>Business-Cycle Context: ${escapeHtml(cycle.phase_name)}</h3>
      <p>${escapeHtml(cycle.description)}</p>
      <p><strong>Historically favored sectors:</strong> ${favored || "—"}</p>
      <p><strong>Historically lagging sectors:</strong> ${lagging || "—"}</p>
      <p class="meta">${escapeHtml(cycle.note)}</p>
    </section>
  `;
}

function renderSeriesCard(series) {
  const value = series.latest_value === null || series.latest_value === undefined ? "—" : series.latest_value;
  const entry = macroGlossaryEntry(series.series_id);
  return `
    <div class="series-card">
      <h3>${escapeHtml(series.label)}</h3>
      <p class="series-value">${value} <span class="series-date">(${escapeHtml(series.as_of || "—")})</span></p>
      ${renderMood(series.mood)}
      ${renderSparkline(series.history)}
      ${renderSeriesInfo(entry)}
      <p><a href="${escapeHtml(series.source_url)}" target="_blank" rel="noopener">View on FRED &rarr;</a></p>
    </div>
  `;
}

function renderMood(mood) {
  if (!mood) return "";
  const sentimentClass = mood.sentiment ? ` mood-${escapeHtml(mood.sentiment)}` : "";
  return `
    <p class="series-mood${sentimentClass}" title="${escapeHtml(mood.detail)}">
      <span class="mood-emoji" aria-hidden="true">${escapeHtml(mood.emoji)}</span> ${escapeHtml(mood.label)}
    </p>
  `;
}

function renderSeriesInfo(entry) {
  if (!entry) return "";
  return `
    <details class="series-info">
      <summary>What is this?</summary>
      <div class="metric-info">
        <p><strong>What it is:</strong> ${escapeHtml(entry.explanation)}</p>
        <p><strong>Why it matters:</strong> ${escapeHtml(entry.significance)}</p>
        <p><strong>How its volatility affects the economy:</strong> ${escapeHtml(entry.volatilityImpact)}</p>
      </div>
    </details>
  `;
}

function renderSparkline(history) {
  const values = (history || []).map((h) => h.value).filter((v) => v !== null && v !== undefined);
  if (values.length < 2) return "";

  const width = 240;
  const height = 48;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return `
    <svg class="sparkline" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="Trend sparkline">
      <polyline points="${points}" fill="none" stroke="currentColor" stroke-width="2" />
    </svg>
  `;
}

main();
