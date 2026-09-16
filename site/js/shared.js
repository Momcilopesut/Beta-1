export async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`${path} returned ${res.status}`);
  }
  return res.json();
}

const VERDICT_CLASSES = {
  Strong: "verdict-strong",
  Favorable: "verdict-favorable",
  Neutral: "verdict-neutral",
  Cautious: "verdict-cautious",
  Weak: "verdict-weak",
};

export function verdictClass(verdict) {
  return VERDICT_CLASSES[verdict] || "verdict-neutral";
}

export function formatNumber(value, { decimals = 1, suffix = "" } = {}) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
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
