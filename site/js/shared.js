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
  const body = summary
    ? `<p>${escapeHtml(summary)}</p>`
    : qualitative
      ? `<p class="meta">No excerpt was available to summarize this filing.</p>`
      : `<p class="meta">AI summary only runs for this week's per-sector finalists (cost control — this layer reads real filing text and spends extra AI budget per company).</p>`;
  return `
    <div class="filing-card">
      <h4><a href="${escapeHtml(filing.url)}" target="_blank" rel="noopener">${escapeHtml(filing.form)}</a> <span class="meta">filed ${escapeHtml(filing.filed)}</span></h4>
      ${body}
    </div>
  `;
}

// --- On-demand lookup config (api/lookup.py, deployed separately to
// Vercel - see README "On-demand lookup"). Stored per-browser in
// localStorage, never sent anywhere but the configured API itself. ---

const LOOKUP_BASE_KEY = "lookupApiBase";
const LOOKUP_SEARCH_KEY = "lookupSearchKey";

function safeLocalStorage() {
  try {
    return window.localStorage;
  } catch {
    return null; // private browsing / blocked storage - lookup config just won't persist
  }
}

export function getLookupConfig() {
  const storage = safeLocalStorage();
  if (!storage) return { apiBase: null, searchKey: null };
  return {
    apiBase: storage.getItem(LOOKUP_BASE_KEY),
    searchKey: storage.getItem(LOOKUP_SEARCH_KEY),
  };
}

export function setLookupConfig(apiBase, searchKey) {
  const storage = safeLocalStorage();
  if (!storage) return;
  if (apiBase) storage.setItem(LOOKUP_BASE_KEY, apiBase.replace(/\/+$/, ""));
  if (searchKey) storage.setItem(LOOKUP_SEARCH_KEY, searchKey);
}

// Prompts once (native prompt() - deliberately minimal, this is a
// single-user personal tool) if no API base is configured yet. Returns the
// config, possibly still incomplete if the user cancels.
export function ensureLookupConfig() {
  let { apiBase, searchKey } = getLookupConfig();
  if (!apiBase) {
    apiBase = window.prompt(
      "Live ticker lookup isn't configured yet.\n\nEnter your deployed lookup API base URL " +
        "(e.g. https://your-project.vercel.app):"
    );
    if (apiBase) {
      searchKey = window.prompt("Enter your search key (leave blank if the API has none configured):") || "";
      setLookupConfig(apiBase, searchKey);
    }
  }
  return getLookupConfig();
}

export async function lookupTicker(ticker, { skipAi = false } = {}) {
  const { apiBase, searchKey } = ensureLookupConfig();
  if (!apiBase) {
    throw new Error("Live lookup isn't configured.");
  }
  const url = new URL("/api/lookup", apiBase);
  url.searchParams.set("ticker", ticker);
  if (skipAi) url.searchParams.set("ai", "0");

  const headers = searchKey ? { "X-Search-Key": searchKey } : {};
  const res = await fetch(url, { headers });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error((body && body.error) || `Live lookup returned ${res.status}`);
  }
  return body;
}
