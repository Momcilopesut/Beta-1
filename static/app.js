const form = document.getElementById("search-form");
const input = document.getElementById("ticker-input");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatPriceLine(price) {
  if (!price || price.close === null || price.close === undefined) {
    return "No price data found.";
  }
  let line = `$${price.close.toFixed(2)} as of ${escapeHtml(price.as_of)}`;
  if (price.change_pct !== null && price.change_pct !== undefined) {
    const sign = price.change_pct >= 0 ? "+" : "";
    line += ` <span class="${price.change_pct >= 0 ? "up" : "down"}">(${sign}${price.change_pct.toFixed(1)}%)</span>`;
  }
  return line;
}

function render(data) {
  const newsItems = (data.news || [])
    .map((n) => {
      const published = n.published ? ` <span class="meta">${escapeHtml(n.published)}</span>` : "";
      return `<li><a href="${escapeHtml(n.link)}" target="_blank" rel="noopener">${escapeHtml(n.title)}</a>${published}</li>`;
    })
    .join("");

  resultEl.innerHTML = `
    <h2>${escapeHtml(data.ticker)}</h2>
    <p class="price">${formatPriceLine(data.price)}</p>
    ${
      data.summary
        ? `<p class="summary">${escapeHtml(data.summary)}</p>`
        : `<p class="summary muted">No local-model summary available (is LM Studio's server running?).</p>`
    }
    <h3>Recent headlines</h3>
    <ul class="news-list">${newsItems || '<li class="muted">No recent headlines found.</li>'}</ul>
  `;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;

  statusEl.textContent = `Looking up ${ticker}… this can take a bit (scraping + your local model).`;
  resultEl.innerHTML = "";

  try {
    const res = await fetch(`/api/lookup?ticker=${encodeURIComponent(ticker)}`);
    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = data.error || `Lookup failed (${res.status})`;
      return;
    }
    statusEl.textContent = "";
    render(data);
  } catch (err) {
    statusEl.textContent = `Could not reach the local server: ${err.message}`;
  }
});
