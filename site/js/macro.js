import { fetchJSON, escapeHtml, renderDisclaimerFooter } from "./shared.js";

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
    <section class="series-grid">${seriesHtml}</section>
  `;
}

function renderSeriesCard(series) {
  const value = series.latest_value === null || series.latest_value === undefined ? "—" : series.latest_value;
  return `
    <div class="series-card">
      <h3>${escapeHtml(series.label)}</h3>
      <p class="series-value">${value} <span class="series-date">(${escapeHtml(series.as_of || "—")})</span></p>
      ${renderSparkline(series.history)}
      <p><a href="${escapeHtml(series.source_url)}" target="_blank" rel="noopener">View on FRED &rarr;</a></p>
    </div>
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
