import { fetchJSON, formatNumber, escapeHtml, renderDisclaimerFooter, renderError } from "./shared.js";
import { buildSearchIndex, search as searchIndex } from "./search-index.js";

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

let allCompanies = [];
let searchIdx = [];
let performancePicksBySector = {};
let performanceWindows = [];

async function main() {
  const status = document.getElementById("status");
  const cardsEl = document.getElementById("cards");
  // Wired up immediately, before the background data fetch below - an
  // untracked-ticker lookup (the whole point of the search box) doesn't
  // depend on this page's own performance-screen data at all, and a slow
  // or failed fetch shouldn't leave the search box inert in the meantime.
  wireSearch();
  try {
    const [picks, watchlist] = await Promise.all([
      fetchJSON("../data/performance_picks.json"),
      fetchJSON("../data/watchlist.json"),
    ]);
    performancePicksBySector = picks.picks_by_sector;
    performanceWindows = picks.windows;
    allCompanies = watchlist.companies;
    searchIdx = buildSearchIndex(allCompanies);
    const pickCount = Object.values(performancePicksBySector).reduce(
      (sum, windows) => sum + Object.values(windows).reduce((s, list) => s + list.length, 0),
      0
    );
    status.textContent = pickCount
      ? `Top ${picks.top_n_per_sector} performers per sector, across 5 timeframes, from a screen of ${picks.universe_size} companies · generated ${picks.generated_at}`
      : `Screened ${picks.universe_size} companies · generated ${picks.generated_at} · no performance data yet`;
    cardsEl.innerHTML = pickCount ? renderPerformanceScreen(performancePicksBySector, performanceWindows) : renderNoPicksYet();
  } catch (err) {
    renderError(cardsEl, `Could not load this week's top performers (${err.message}). Has the pipeline run yet?`);
    status.textContent = "";
  }
  renderDisclaimerFooter();
}

function renderNoPicksYet() {
  return `<p class="status">No sector had a company with enough price history to rank yet. Check back after the pipeline's next run, or search for any ticker above.</p>`;
}

// Typeahead suggestion box: as you type, a dropdown of up to 8 ranked
// matches (see site/js/search-index.js) appears under the input - arrow
// keys + Enter or a click jump straight to that company's page. Enter with
// nothing highlighted keeps the old behavior: jump to a single exact
// tracked match, or to the ticker as typed (company.html offers a live
// lookup if it isn't tracked).
function wireSearch() {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  const suggestionsEl = document.getElementById("search-suggestions");
  if (!form || !input || !suggestionsEl) return;

  let currentMatches = [];
  let activeIndex = -1;

  function goToTicker(ticker) {
    window.location.href = `company.html?ticker=${encodeURIComponent(ticker)}`;
  }

  function closeSuggestions() {
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    currentMatches = [];
    activeIndex = -1;
  }

  function setActive(index) {
    const items = suggestionsEl.querySelectorAll("li[data-ticker]");
    items.forEach((el) => el.classList.remove("active"));
    activeIndex = index;
    if (index >= 0 && index < items.length) {
      items[index].classList.add("active");
      items[index].scrollIntoView({ block: "nearest" });
    }
  }

  function renderSuggestions(query, matches) {
    currentMatches = matches;
    activeIndex = -1;
    if (!matches.length) {
      suggestionsEl.innerHTML = `<li class="suggestion-empty">No tracked match for "${escapeHtml(query)}" — press Enter to look it up.</li>`;
    } else {
      suggestionsEl.innerHTML = matches
        .map(
          (m, i) => `
            <li role="option" data-index="${i}" data-ticker="${escapeHtml(m.ticker)}">
              <span class="suggestion-ticker">${escapeHtml(m.ticker)}</span>
              <span class="suggestion-name">${escapeHtml(m.name)}</span>
              <span class="suggestion-sector">${escapeHtml(m.sector || "")}</span>
            </li>
          `
        )
        .join("");
    }
    suggestionsEl.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  input.addEventListener("input", () => {
    const query = input.value.trim();
    if (!query) {
      closeSuggestions();
      return;
    }
    renderSuggestions(query, searchIndex(searchIdx, query, 8));
  });

  input.addEventListener("keydown", (event) => {
    if (suggestionsEl.hidden) return;
    if (event.key === "ArrowDown" && currentMatches.length) {
      event.preventDefault();
      setActive(Math.min(activeIndex + 1, currentMatches.length - 1));
    } else if (event.key === "ArrowUp" && currentMatches.length) {
      event.preventDefault();
      setActive(Math.max(activeIndex - 1, 0));
    } else if (event.key === "Escape") {
      closeSuggestions();
    } else if (event.key === "Enter" && activeIndex >= 0 && currentMatches[activeIndex]) {
      event.preventDefault();
      goToTicker(currentMatches[activeIndex].ticker);
    }
  });

  // mousedown (not click) fires before the input's blur, so the dropdown
  // is still populated when this handler reads it.
  suggestionsEl.addEventListener("mousedown", (event) => {
    const li = event.target.closest("li[data-ticker]");
    if (li) goToTicker(li.dataset.ticker);
  });

  input.addEventListener("blur", () => {
    setTimeout(closeSuggestions, 100);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    if (activeIndex >= 0 && currentMatches[activeIndex]) {
      goToTicker(currentMatches[activeIndex].ticker);
      return;
    }
    const exact = allCompanies.find((c) => c.ticker.toLowerCase() === query.toLowerCase());
    goToTicker(exact ? exact.ticker : query.toUpperCase());
  });
}

// Default homepage view: for each sector, 5 independently-ranked leaderboards
// (one per pipeline.scoring.performance.WINDOWS entry) - pure price return,
// already ranked and capped by select_top_performers, rendered in that order
// with #1/#2/... rank position, not re-sorted here.
function renderPerformanceScreen(picksBySector, windows) {
  const orderedSectors = [
    ...SECTOR_ORDER.filter((s) => picksBySector[s]),
    ...Object.keys(picksBySector)
      .filter((s) => !SECTOR_ORDER.includes(s))
      .sort(),
  ];

  return orderedSectors
    .map(
      (sector) => `
        <section class="sector-group">
          <h2 class="sector-heading">${escapeHtml(sector)}</h2>
          <div class="perf-grid">
            ${windows.map((w) => renderPerfPanel(w, picksBySector[sector][w.key])).join("")}
          </div>
        </section>
      `
    )
    .join("");
}

function renderPerfPanel(perfWindow, picks) {
  const rows = (picks || []).length
    ? picks.map((c, i) => renderPerfRow(c, i + 1, perfWindow.key)).join("")
    : `<li class="perf-empty">Not enough data yet</li>`;
  return `
    <div class="perf-panel">
      <p class="perf-panel-title">${escapeHtml(perfWindow.label)}</p>
      <ol class="perf-list">${rows}</ol>
    </div>
  `;
}

function fmtReturn(pct) {
  const sign = pct > 0 ? "+" : "";
  return `${sign}${formatNumber(pct, { decimals: 1, suffix: "%" })}`;
}

function renderPerfRow(company, rank, windowKey) {
  const pct = company.returns?.[windowKey];
  const hasPct = pct !== null && pct !== undefined;
  const direction = hasPct ? (pct > 0 ? "perf-up" : pct < 0 ? "perf-down" : "") : "";
  const returnText = hasPct ? fmtReturn(pct) : "—";
  const price = company.price?.close;
  const priceLine =
    price !== undefined && price !== null
      ? `<span class="perf-price">$${formatNumber(price, { decimals: 2 })}</span>`
      : "";
  return `
    <li class="perf-row">
      <a href="company.html?ticker=${encodeURIComponent(company.ticker)}">
        <span class="perf-rank">${rank}</span>
        <span class="perf-id">
          <span class="perf-ticker">${escapeHtml(company.ticker)}</span>
          <span class="perf-name">${escapeHtml(company.name)}</span>
        </span>
        <span class="perf-metrics">
          <span class="perf-return ${direction}">${returnText}</span>
          ${priceLine}
        </span>
      </a>
    </li>
  `;
}

main();
