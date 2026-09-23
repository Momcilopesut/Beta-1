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
    <section class="series-grid">${seriesHtml}</section>
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
