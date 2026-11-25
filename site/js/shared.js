export async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`${path} returned ${res.status}`);
  }
  return res.json();
}

export function formatNumber(value, { decimals = 1, suffix = "", compact = false } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (compact) {
    // For big dollar figures (total assets, liabilities, ...) - "$264.9B"
    // reads at a glance; the raw digit string doesn't, especially for
    // someone new to this ("think of this as software for an 11 year old").
    return `${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value))}${suffix}`;
  }
  return `${Number(value).toFixed(decimals)}${suffix}`;
}

// All page-rendering code below uses this before interpolating any string
// that ultimately comes from fetched JSON (pipeline-generated, but some of
// it - company names, AI narrative text - originates outside our own code)
// or from the URL (the ?ticker= query param), rather than trusting it
// verbatim inside innerHTML.
export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderDisclaimerFooter() {
  const footer = document.createElement("footer");
  footer.className = "disclaimer";
  footer.textContent =
    "This is not financial advice. All figures are estimates based on automated analysis of public data and may contain errors or delays.";
  document.body.appendChild(footer);
}

export function renderError(container, message) {
  container.innerHTML = `<p class="error"></p>`;
  container.querySelector(".error").textContent = message;
}

// --- SEC filing cards: shared by the company page's own Recent Filings
// section and the cross-company Filings Digest page, so the "which
// qualitative field holds this form's summary" mapping and the card markup
// only exist once. ---

export const FILING_SUMMARY_KEY = { "10-K": "filing_summary_10k", "10-Q": "filing_summary_10q", "8-K": "filing_summary_8k" };

export function renderFilingCard(filing, qualitative) {
  const summary = qualitative?.[FILING_SUMMARY_KEY[filing.form]];
  return `
    <div class="filing-card">
      <h4><a href="${escapeHtml(filing.url)}" target="_blank" rel="noopener">${escapeHtml(filing.form)}</a> <span class="meta">filed ${escapeHtml(filing.filed)}</span></h4>
      <p>${escapeHtml(summary)}</p>
    </div>
  `;
}

function renderFilingListRow(filing) {
  return `<li><a href="${escapeHtml(filing.url)}" target="_blank" rel="noopener">${escapeHtml(filing.form)}</a> <span class="meta">filed ${escapeHtml(filing.filed)}</span></li>`;
}

// Splits a company's filings into two treatments: ones with an AI summary
// get the fuller card (renderFilingCard, above), ones without just get a
// plain document-link row - no point giving an empty card the same visual
// weight as one with real content. Shared by the company page's Recent
// Filings section and the cross-company Filings Digest page.
export function renderFilingsSection(filings, qualitative) {
  const withSummary = filings.filter((f) => qualitative?.[FILING_SUMMARY_KEY[f.form]]);
  const withoutSummary = filings.filter((f) => !qualitative?.[FILING_SUMMARY_KEY[f.form]]);
  const cards = withSummary.length
    ? `<div class="filings-grid">${withSummary.map((f) => renderFilingCard(f, qualitative)).join("")}</div>`
    : "";
  const list = withoutSummary.length
    ? `<ul class="filings-list">${withoutSummary.map(renderFilingListRow).join("")}</ul>`
    : "";
  return cards + list;
}

// --- On-demand lookup. app.py serves /api/lookup on this exact origin
// (see README's "Running the app") - this is always a same-origin call
// now, no separately-deployed API, no stored config, no prompting. ---

export async function lookupTicker(ticker, { skipAi = false } = {}) {
  const url = new URL("/api/lookup", window.location.origin);
  url.searchParams.set("ticker", ticker);
  if (skipAi) url.searchParams.set("ai", "0");

  let res;
  try {
    res = await fetch(url);
  } catch {
    throw new Error("Could not reach the local server - make sure app.py is running (see README's \"Running the app\").");
  }
  if (res.ok) return res.json();
  const body = await res.json().catch(() => null);
  throw new Error((body && body.error) || `Live lookup returned ${res.status}`);
}
