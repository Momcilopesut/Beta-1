import {
  fetchJSON,
  verdictClass,
  formatNumber,
  escapeHtml,
  renderDisclaimerFooter,
  lookupTicker,
} from "./shared.js";
import { METRIC_GLOSSARY, glossaryEntry } from "./metrics-glossary.js";

function tickerFromQuery() {
  return new URLSearchParams(window.location.search).get("ticker");
}

async function main() {
  const content = document.getElementById("content");
  const ticker = tickerFromQuery();

  if (!ticker) {
    content.innerHTML = `<p class="error">No ticker specified. Go back to <a href="index.html">this week's top performers</a>.</p>`;
    renderDisclaimerFooter();
    return;
  }

  document.title = `${ticker} – Company Detail`;

  try {
    const doc = await fetchJSON(`../data/companies/${encodeURIComponent(ticker)}.json`);
    content.innerHTML = render(doc);
    wireDetailPage(content, doc);
  } catch {
    renderNotTracked(content, ticker);
  }
  renderDisclaimerFooter();
}

function wireDetailPage(content, doc) {
  const years = doc.five_year_history?.years;
  if (years && years.length >= 2) {
    initTrendCompare(content, years);
  }
}

function renderNotTracked(content, ticker) {
  const safeTicker = escapeHtml(ticker);
  content.innerHTML = `
    <section class="not-tracked">
      <p class="error">${safeTicker} isn't in the current screening universe.</p>
      <p class="meta">You can run a live, on-demand analysis instead — the same scoring, checklists,
      and moat read as the tracked companies, computed fresh right now via a separate lookup
      service. This spends real API budget per lookup, so it only runs when you ask.</p>
      <button id="run-live-lookup" class="live-lookup-button">Run live analysis for ${safeTicker}</button>
    </section>
  `;
  document.getElementById("run-live-lookup").addEventListener("click", () => runLiveLookup(content, ticker));
}

async function runLiveLookup(content, ticker) {
  const safeTicker = escapeHtml(ticker);
  content.innerHTML = `<p class="status">Analyzing ${safeTicker} live&hellip; this can take up to a minute.</p>`;
  try {
    const doc = await lookupTicker(ticker);
    content.innerHTML = render(doc);
    wireDetailPage(content, doc);
  } catch (err) {
    content.innerHTML = `
      <p class="error">Live analysis failed for ${safeTicker}: ${escapeHtml(err.message)}</p>
      <button id="run-live-lookup" class="live-lookup-button">Try again</button>
    `;
    document.getElementById("run-live-lookup").addEventListener("click", () => runLiveLookup(content, ticker));
  }
}

function renderPriceHeader(price) {
  const close = price?.close;
  if (close === undefined || close === null) return "";
  const asOf = price?.as_of ? ` <span class="price-as-of">as of ${escapeHtml(price.as_of)}</span>` : "";
  return `<p class="detail-price">$${formatNumber(close, { decimals: 2 })}${asOf}</p>`;
}

function renderWebsiteLink(website) {
  if (!website) return "";
  return `<p class="meta"><a href="${escapeHtml(website)}" target="_blank" rel="noopener">Company website ↗</a> <span class="meta">(investor relations is usually linked from there — this is the company's general site, not a verified IR-specific URL)</span></p>`;
}

function render(doc) {
  const onDemandBanner = doc.on_demand
    ? `<p class="on-demand-banner">Live on-demand analysis — not part of the tracked watchlist, computed just now.</p>`
    : "";
  return `
    ${onDemandBanner}
    <section class="detail-header">
      <h2>${escapeHtml(doc.name)} <span class="ticker-tag">${escapeHtml(doc.ticker)}</span></h2>
      ${renderPriceHeader(doc.price)}
      <p class="meta">${escapeHtml(doc.sector || "—")} · ${escapeHtml(doc.industry || "—")} · Updated ${escapeHtml(doc.last_updated)}</p>
      ${renderWebsiteLink(doc.website)}
    </section>

    <section class="verdicts-detail">
      ${renderConvictionCard(doc.layered_analysis)}
    </section>

    ${renderKeyMetricsReference(doc.metrics)}

    ${renderBalanceSheetBasics(doc.fundamentals, doc.layered_analysis)}

    ${renderFiveYearHistory(doc.five_year_history)}

    ${renderLayeredAnalysis(doc)}

    ${renderValueInvesting(doc.value_investing)}

    <section class="macro">
      <h3>Macro Context</h3>
      <p>Regime: <strong>${escapeHtml(doc.macro_context.regime)}</strong></p>
      <p>Sector sensitivity: rate = ${escapeHtml(doc.macro_context.sector_sensitivity.rate_sensitivity)}, cyclicality = ${escapeHtml(doc.macro_context.sector_sensitivity.cyclicality)}</p>
      <p><a href="macro.html">See full macro overview &rarr;</a></p>
    </section>

    ${renderRecentFilings(doc)}

    <section class="sources">
      <h3>Sources</h3>
      <ul>
        ${
          doc.sources.sec_companyfacts_url
            ? `<li><a href="${escapeHtml(doc.sources.sec_companyfacts_url)}" target="_blank" rel="noopener">SEC XBRL company facts (raw)</a></li>`
            : ""
        }
      </ul>
    </section>
  `;
}

const FILING_SUMMARY_KEY = { "10-K": "filing_summary_10k", "10-Q": "filing_summary_10q", "8-K": "filing_summary_8k" };

function renderFilingCard(filing, qualitative) {
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

function renderRecentFilings(doc) {
  const filings = doc.sources?.sec_filings || [];
  if (!filings.length) return "";
  return `
    <section class="recent-filings">
      <h3>Recent Filings <span class="attribution">(latest 10-K, 10-Q, and 8-K, each with a short AI summary when available)</span></h3>
      <div class="filings-grid">
        ${filings.map((f) => renderFilingCard(f, doc.qualitative)).join("")}
      </div>
    </section>
  `;
}

// --- The meter: an inline SVG semi-circle gauge, five bands matching the
// verdict thresholds/colors already defined in site/css/styles.css (light
// and dark mode both covered since these read the same CSS custom
// properties the rest of the page uses for verdict colors). ---

const GAUGE_BANDS = [
  { min: 0, max: 25, colorVar: "--weak" },
  { min: 25, max: 40, colorVar: "--cautious" },
  { min: 40, max: 60, colorVar: "--neutral" },
  { min: 60, max: 75, colorVar: "--favorable" },
  { min: 75, max: 100, colorVar: "--strong" },
];

function polarToCartesian(cx, cy, r, angleDeg) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy - r * Math.sin(rad) };
}

function scoreToAngleDeg(score) {
  return 180 - (Math.max(0, Math.min(100, score)) / 100) * 180;
}

function gaugeArcPath(cx, cy, r, scoreStart, scoreEnd) {
  const start = polarToCartesian(cx, cy, r, scoreToAngleDeg(scoreStart));
  const end = polarToCartesian(cx, cy, r, scoreToAngleDeg(scoreEnd));
  return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${r} ${r} 0 0 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
}

function renderMeterGauge(score, verdict) {
  const cx = 100;
  const cy = 96;
  const r = 78;
  const strokeWidth = 16;
  const hasScore = score !== null && score !== undefined;

  const bands = GAUGE_BANDS.map(
    (b) =>
      `<path d="${gaugeArcPath(cx, cy, r, b.min, b.max)}" stroke="var(${b.colorVar})" stroke-width="${strokeWidth}" fill="none" />`
  ).join("");

  let needle = "";
  if (hasScore) {
    const tip = polarToCartesian(cx, cy, r - strokeWidth - 8, scoreToAngleDeg(score));
    needle = `
      <line x1="${cx}" y1="${cy}" x2="${tip.x.toFixed(2)}" y2="${tip.y.toFixed(2)}" stroke="var(--fg)" stroke-width="3" stroke-linecap="round" />
      <circle cx="${cx}" cy="${cy}" r="6" fill="var(--fg)" />
    `;
  }

  const label = hasScore
    ? `Investment meter: ${formatNumber(score, { decimals: 0 })}${verdict ? ", " + verdict : ""}`
    : "Investment meter: not enough data";

  return `
    <div class="meter-gauge">
      <svg viewBox="0 0 200 108" width="220" height="119" role="img" aria-label="${escapeHtml(label)}">
        ${bands}
        ${needle}
      </svg>
      <p class="meter-score">${hasScore ? formatNumber(score, { decimals: 0 }) : "—"}</p>
      <p class="meter-verdict">${verdict ? escapeHtml(verdict) : "Not enough data"}</p>
    </div>
  `;
}

function renderConvictionCard(layered) {
  const hasScore = layered && layered.conviction_score !== null && layered.conviction_score !== undefined;
  const gauge = renderMeterGauge(hasScore ? layered.conviction_score : null, hasScore ? layered.conviction_verdict : null);

  if (!hasScore) {
    return `
      <div class="score-card verdict-neutral meter-card">
        <h3>Investment Meter</h3>
        ${gauge}
        <p class="score-note">Needs the defensive checklist to have evaluated data.</p>
      </div>
    `;
  }
  const b = layered.conviction_score_breakdown || {};
  return `
    <div class="score-card ${verdictClass(layered.conviction_verdict)} meter-card">
      <h3>Investment Meter</h3>
      ${gauge}
      <p class="score-note">Base checklist ${formatNumber(b.base_score, { decimals: 0 })}% ×
      ${formatNumber(b.munger_multiplier, { decimals: 2 })} quality checklist ×
      ${formatNumber(b.moat_multiplier, { decimals: 2 })} moat read ×
      ${formatNumber(b.valuation_multiplier, { decimals: 2 })} valuation gate</p>
    </div>
  `;
}

function fmt(v, decimals = 1, suffix = "") {
  return v === null || v === undefined ? "—" : formatNumber(v, { decimals, suffix });
}

function fmtDollars(v) {
  return v === null || v === undefined ? "—" : `$${formatNumber(v, { compact: true })}`;
}

// --- Key Metrics Reference: every metric this tool scores on, this
// company's own current value, and (tap to expand) what it means and why
// it matters - see site/js/metrics-glossary.js for the shared content and
// site/glossary.html for the full standalone reference. ---

const MARGIN_TREND_LABELS = { 20: "Declining", 60: "Stable", 100: "Improving" };

// Green/yellow/red read on each metric, reusing the same thresholds this
// app's own checklists already score against (pipeline/scoring/
// value_investing.py, aggregation.py's margin-of-safety convention) rather
// than inventing new ones - so a metric colored green here is the same
// "green" as a passing checklist row. Returns "good" | "neutral" | "bad" |
// null. null means no data, or - for total_assets/total_liabilities/
// book_value_per_share - a metric that's pure scale with no inherent
// direction (a bigger number isn't better or worse on its own) and for
// ncav_margin_pct, which the glossary itself explains is expected to be
// sharply negative for a normal large-cap, so coloring it red would flag
// something that isn't actually a problem for the companies this tool
// tracks.
function metricSentiment(key, value) {
  if (value === null || value === undefined) return null;
  switch (key) {
    case "pe_ttm": // cheaper is better; >15 fails the defensive checklist's own bar
      return value <= 15 ? "good" : value <= 25 ? "neutral" : "bad";
    case "pb_ratio": // <=1.5x book is classic deep-value territory
      return value <= 1.5 ? "good" : value <= 3 ? "neutral" : "bad";
    case "graham_upside_pct": // mirrors aggregation.py's own margin-of-safety flags
      return value >= 15 ? "good" : value >= 0 ? "neutral" : "bad";
    case "graham_multiple": // 22.5 is this tool's own combined P/E x P/B ceiling
      return value <= 22.5 ? "good" : value <= 35 ? "neutral" : "bad";
    case "debt_to_equity": // 1.0 is the defensive checklist's own leverage bar
      return value <= 1.0 ? "good" : value <= 2.0 ? "neutral" : "bad";
    case "debt_to_ebitda": // standard leverage read: <2x low, >4x stretched
      return value <= 2 ? "good" : value <= 4 ? "neutral" : "bad";
    case "current_ratio": // 2.0 is the defensive checklist's own bar; <1.0 means short-term liabilities exceed short-term assets
      return value >= 2.0 ? "good" : value >= 1.0 ? "neutral" : "bad";
    case "fcf_margin_pct": // negative means burning cash, not just generating less of it
      return value >= 15 ? "good" : value >= 0 ? "neutral" : "bad";
    case "eps_growth_cagr_3yr_pct": // 2.9%/yr merely passes the checklist; double digits is a clearly strong signal
      return value >= 10 ? "good" : value >= 0 ? "neutral" : "bad";
    case "roe_pct": // 15% is the quality checklist's own bar
      return value >= 15 ? "good" : value >= 0 ? "neutral" : "bad";
    case "margin_trend_score": // already categorical: 20 declining / 60 stable / 100 improving
      return value >= 100 ? "good" : value >= 60 ? "neutral" : "bad";
    case "shareholders_equity": // negative net worth is unambiguous - liabilities exceed assets
      return value > 0 ? "good" : "bad";
    default: // ncav_margin_pct, total_assets, total_liabilities, book_value_per_share
      return null;
  }
}

function formatMetricValue(key, value) {
  if (value === null || value === undefined) return "—";
  switch (key) {
    case "pe_ttm":
    case "pb_ratio":
    case "debt_to_ebitda":
    case "graham_multiple":
      return fmt(value, 2, "×");
    case "debt_to_equity":
    case "current_ratio":
      return fmt(value, 2);
    case "graham_upside_pct":
    case "ncav_margin_pct":
    case "fcf_margin_pct":
    case "eps_growth_cagr_3yr_pct":
    case "roe_pct":
      return fmt(value, 1, "%");
    case "margin_trend_score":
      return MARGIN_TREND_LABELS[value] || String(value);
    case "total_assets":
    case "total_liabilities":
    case "shareholders_equity":
      return fmtDollars(value);
    case "book_value_per_share":
      return `$${fmt(value, 2)}`;
    default:
      return fmt(value, 2);
  }
}

function renderKeyMetricsReference(metrics) {
  if (!metrics) return "";
  const rows = METRIC_GLOSSARY.map((m) => {
    const value = metrics[m.key];
    const sentiment = metricSentiment(m.key, value);
    const valueClass = sentiment ? ` metric-value-${sentiment}` : "";
    return `
      <details class="metric-row">
        <summary>
          <span class="metric-label">${escapeHtml(m.label)}</span>
          <span class="metric-value${valueClass}">${escapeHtml(formatMetricValue(m.key, value))}</span>
        </summary>
        <div class="metric-info">
          <p><strong>What it is:</strong> ${escapeHtml(m.explanation)}</p>
          <p><strong>Why it matters:</strong> ${escapeHtml(m.significance)}</p>
          <p><strong>How it moves the business:</strong> ${escapeHtml(m.volatilityImpact)}</p>
        </div>
      </details>
    `;
  }).join("");

  return `
    <section class="key-metrics-reference">
      <h3>Key Metrics Reference <span class="attribution"><a href="glossary.html">full glossary &rarr;</a></span></h3>
      <p class="meta">This company's own numbers - tap any row for what it means and why it matters. Colored
      where the value clearly signals better (green) or worse (red) for this company's finances; some figures
      are shown in gray because they're pure scale (bigger isn't inherently better or worse).</p>
      <div class="metric-rows">${rows}</div>
    </section>
  `;
}

function renderBalanceSheetBasics(fundamentals, layered) {
  const basics = fundamentals?.balance_sheet_basics;
  const valuation = fundamentals?.valuation;
  if (!basics && !valuation) return "";
  return `
    <section class="balance-sheet-basics">
      <h3>Assets vs. Liabilities</h3>
      <p class="meta">The most basic question in investing: does this company own more than it owes?</p>
      <ul class="basics-list">
        <li>Owns (total assets): <strong>${fmtDollars(basics?.total_assets)}</strong></li>
        <li>Owes (total liabilities): <strong>${fmtDollars(basics?.total_liabilities)}</strong></li>
        <li>What's left over (net worth): <strong>${fmtDollars(basics?.shareholders_equity)}</strong></li>
        <li>Net worth per share (book value): <strong>$${fmt(basics?.book_value_per_share, 2)}</strong></li>
      </ul>
      <p class="checklist-label">Is the price fair for what's owned?</p>
      <p class="meta">Price ÷ book value: ${fmt(valuation?.pb_ratio, 2)}× · Fair-value estimate (a simple estimate from earnings and book value): $${fmt(valuation?.graham_number, 2)}, a margin of safety of ${fmt(valuation?.graham_upside_pct, 0, "%")}</p>
      ${
        valuation?.ncav_margin_pct !== null && valuation?.ncav_margin_pct !== undefined && valuation.ncav_margin_pct > 0
          ? `<p class="meta">The strictest test here also passes: even just the current assets, after paying off every liability, are worth ${fmt(valuation.ncav_margin_pct, 0, "%")} more than the whole stock costs today.</p>`
          : ""
      }
      ${
        layered?.required_margin_of_safety_pct !== undefined && layered?.required_margin_of_safety_pct !== null
          ? `<p class="meta">Required margin of safety: ${formatNumber(layered.required_margin_of_safety_pct, { decimals: 0, suffix: "%" })} (this tool's convention — a real discount to estimated fair value, not just trading below it by any amount).</p>`
          : ""
      }
    </section>
  `;
}

// --- 5-year history: revenue/profit/debt/spending/cash over time, and this
// stock's yearly return vs. the market (SPY, standing in for "the stock
// market average") over the same years. Plain inline SVG, same approach as
// the meter gauge above - no charting library. ---

const TREND_SERIES = [
  { key: "revenue", label: "Total Revenue", colorVar: "--trend-revenue" },
  { key: "earnings", label: "Net Profit", colorVar: "--trend-profit" },
  { key: "debt", label: "Debt", colorVar: "--trend-debt" },
  { key: "spending", label: "Spending", colorVar: "--trend-spending" },
  { key: "cash", label: "Cash Reserve", colorVar: "--trend-cash" },
];
const TREND_MAX_SELECTED = 5;
const TREND_ARROW = { up: "↑", down: "↓", flat: "→" };

function fmtPctSigned(v) {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${formatNumber(v, { decimals: 1, suffix: "%" })}`;
}

// Always includes 0 in the domain (so a zero baseline/axis is always valid
// to draw), but only pads *below* zero when the data actually goes
// negative - otherwise an all-positive series would get a stray "-$0.3B"
// tick from padding alone.
function computeYDomain(values) {
  const defined = values.filter((v) => v !== null && v !== undefined);
  if (!defined.length) return null;
  const dataMin = Math.min(0, ...defined);
  const dataMax = Math.max(0, ...defined);
  const span = dataMax - dataMin || 1;
  return {
    min: dataMin < 0 ? dataMin - span * 0.05 : 0,
    max: dataMax + span * 0.1,
  };
}

// Points where this series actually has a value - real statement data
// (unlike the prototype this was designed in) can have gaps, so every
// calculation below works off defined points only, never a guessed or
// interpolated one.
function trendDefinedPoints(data) {
  return data.map((v, i) => ({ i, v })).filter((p) => p.v !== null && p.v !== undefined);
}

// Year-over-year change vs the immediately preceding year in the series -
// null for the first year shown, or when either year's value is missing.
function trendYoyChange(data, i) {
  if (i === 0) return null;
  const prev = data[i - 1];
  const curr = data[i];
  if (prev === null || prev === undefined || curr === null || curr === undefined || !prev) return null;
  const pct = ((curr - prev) / prev) * 100;
  return { pct, direction: pct > 0 ? "up" : pct < 0 ? "down" : "flat" };
}

function trendTileSVG(s) {
  const width = 220, height = 130;
  const plotLeft = 10, plotRight = width - 10, plotTop = 22, plotBottom = height - 22;
  const points = trendDefinedPoints(s.data);
  if (points.length < 2) {
    return `<div class="trend-tile-empty">Not enough ${escapeHtml(s.label.toLowerCase())} history yet</div>`;
  }

  const values = points.map((p) => p.v);
  const minV = Math.min(...values), maxV = Math.max(...values);
  const span = maxV - minV || Math.abs(maxV) * 0.1 || 1;
  const yMin = minV - span * 0.15, yMax = maxV + span * 0.15;
  const xFor = (i) => plotLeft + (i / (s.data.length - 1)) * (plotRight - plotLeft);
  const yFor = (v) => plotTop + (1 - (v - yMin) / (yMax - yMin)) * (plotBottom - plotTop);

  const linePath = points.map((p, idx) => `${idx === 0 ? "M" : "L"} ${xFor(p.i).toFixed(1)} ${yFor(p.v).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  const areaPath = `${linePath} L ${xFor(last.i).toFixed(1)} ${plotBottom.toFixed(1)} L ${xFor(points[0].i).toFixed(1)} ${plotBottom.toFixed(1)} Z`;
  const dots = points
    .map((p) => `<circle class="trend-dot" cx="${xFor(p.i).toFixed(1)}" cy="${yFor(p.v).toFixed(1)}" r="2.2" fill="var(${s.colorVar})" />`)
    .join("");

  const first = points[0];
  const change = first.v ? ((last.v - first.v) / first.v) * 100 : null;
  const changeLabel = change === null ? "" : `${change >= 0 ? "+" : ""}${change.toFixed(0)}%`;

  return `
    <svg viewBox="0 0 ${width} ${height}">
      <text x="10" y="15" class="trend-tile-title">${escapeHtml(s.label)}</text>
      ${changeLabel ? `<text x="${width - 10}" y="15" text-anchor="end" class="trend-tile-change" style="fill:var(${s.colorVar})">${changeLabel}</text>` : ""}
      <path d="${areaPath}" fill="var(${s.colorVar})" opacity="0.1" />
      <path d="${linePath}" fill="none" stroke="var(${s.colorVar})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
      ${dots}
      <text x="10" y="${height - 8}" class="chart-axis-label">${escapeHtml(fmtDollars(first.v))}</text>
      <text x="${width - 10}" y="${height - 8}" text-anchor="end" class="chart-axis-label">${escapeHtml(fmtDollars(last.v))}</text>
    </svg>
  `;
}

// A small multiples grid (revenue/profit/debt/spending/cash, tap to select
// up to all 5) plus a compare chart below it that overlays every selected
// metric in its own color, independently scaled so a $400B and a $30B
// metric can share one picture. Tapping a year under the compare chart
// pops up every currently-selected metric's value and year-over-year
// change for that year at once - not a per-point click, so adding or
// removing a metric while the popup is open updates it live rather than
// requiring it to be reopened.
function initTrendCompare(root, years) {
  const series = TREND_SERIES.map((s) => ({ ...s, data: years.map((y) => (y[s.key] ?? null)) }));
  const yearLabels = years.map((y) => (y.fiscal_year || "").slice(0, 4));

  let selected = [];
  let activeYearIdx = null;

  const tileGrid = root.querySelector(".trend-tile-grid");
  const compareArea = root.querySelector(".trend-compare-area");
  const panelLabel = root.querySelector(".trend-panel-label");
  const popup = root.querySelector(".trend-dp-popup");
  const popupTitle = root.querySelector(".trend-dp-title");
  const popupRows = root.querySelector(".trend-dp-rows");

  function hidePopup() {
    popup.hidden = true;
  }

  function showYearPopup(yearIdx, anchorEl, chosen) {
    popupTitle.textContent = yearLabels[yearIdx];
    popupRows.innerHTML = chosen
      .map((s) => {
        const value = s.data[yearIdx];
        if (value === null || value === undefined) {
          return `
            <li class="trend-dp-row">
              <span class="trend-dp-row-swatch" style="background:var(${s.colorVar})"></span>
              <span class="trend-dp-row-label">${escapeHtml(s.label)}</span>
              <span class="trend-dp-row-value">No data</span>
            </li>
          `;
        }
        const change = trendYoyChange(s.data, yearIdx);
        const changeHtml = change
          ? `<span class="trend-dp-row-change trend-${change.direction}">${TREND_ARROW[change.direction]} ${change.pct > 0 ? "+" : ""}${change.pct.toFixed(1)}%</span>`
          : `<span class="trend-dp-row-change trend-muted">${yearIdx === 0 ? "first year" : "no prior data"}</span>`;
        return `
          <li class="trend-dp-row">
            <span class="trend-dp-row-swatch" style="background:var(${s.colorVar})"></span>
            <span class="trend-dp-row-label">${escapeHtml(s.label)}</span>
            <span class="trend-dp-row-value" style="color:var(${s.colorVar})">${escapeHtml(fmtDollars(value))}</span>
            ${changeHtml}
          </li>
        `;
      })
      .join("");

    popup.hidden = false;
    if (anchorEl) {
      const rect = anchorEl.getBoundingClientRect();
      const popupRect = popup.getBoundingClientRect();
      let left = rect.left + rect.width / 2 - popupRect.width / 2;
      let top = rect.top - popupRect.height - 10;
      if (top < 8) top = rect.bottom + 10;
      left = Math.max(8, Math.min(left, window.innerWidth - popupRect.width - 8));
      popup.style.left = `${left}px`;
      popup.style.top = `${top}px`;
    }
  }

  function wireYearTicks(container, chosen) {
    container.querySelectorAll(".trend-year-tick").forEach((tick) => {
      const idx = parseInt(tick.dataset.yearIdx, 10);
      const activate = (e) => {
        e.stopPropagation();
        activeYearIdx = activeYearIdx === idx ? null : idx;
        renderCompare();
      };
      tick.addEventListener("click", activate);
      tick.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate(e);
        }
      });
    });
  }

  function renderTiles() {
    panelLabel.textContent = `Tap to compare (${selected.length} of ${TREND_MAX_SELECTED} selected)`;
    tileGrid.innerHTML = series
      .map((s) => {
        const isSelected = selected.includes(s.key);
        const isDisabled = !isSelected && selected.length >= TREND_MAX_SELECTED;
        const idx = selected.indexOf(s.key);
        return `
          <button type="button" class="trend-tile ${isSelected ? "selected" : ""} ${isDisabled ? "disabled" : ""}"
            style="--tile-color:var(${s.colorVar})" data-key="${s.key}" ${isDisabled ? "disabled" : ""}>
            <span class="trend-tile-check">${isSelected ? idx + 1 : ""}</span>
            ${trendTileSVG(s)}
          </button>
        `;
      })
      .join("");

    tileGrid.querySelectorAll(".trend-tile").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        // A deliberate in-app action, not a "click elsewhere" - otherwise
        // the document-level listener that closes an open year popup on
        // outside clicks would immediately close it again after this.
        e.stopPropagation();
        const key = btn.dataset.key;
        if (selected.includes(key)) {
          selected = selected.filter((k) => k !== key);
        } else if (selected.length < TREND_MAX_SELECTED) {
          selected = [...selected, key];
        }
        renderTiles();
        renderCompare();
      });
    });
  }

  function renderCompare() {
    if (selected.length < 2) {
      compareArea.innerHTML = `<p class="trend-compare-empty">Tap a second metric above to compare it directly against the first.</p>`;
      activeYearIdx = null;
      hidePopup();
      return;
    }

    const chosen = selected.map((key) => series.find((s) => s.key === key));
    const width = 640, height = 300;
    const plotLeft = 16, plotRight = width - 16, plotTop = 20, plotBottom = height - 26;
    const xFor = (i) => plotLeft + (i / (yearLabels.length - 1)) * (plotRight - plotLeft);

    const scaled = chosen.map((s) => {
      const points = trendDefinedPoints(s.data);
      const values = points.map((p) => p.v);
      const minV = values.length ? Math.min(...values) : 0;
      const maxV = values.length ? Math.max(...values) : 1;
      const span = maxV - minV || Math.abs(maxV) * 0.1 || 1;
      const yMin = minV - span * 0.2, yMax = maxV + span * 0.2;
      const yFor = (v) => plotTop + (1 - (v - yMin) / (yMax - yMin)) * (plotBottom - plotTop);
      return { ...s, points, yFor };
    });

    const guide = activeYearIdx !== null
      ? `<line class="trend-year-guide" x1="${xFor(activeYearIdx).toFixed(1)}" x2="${xFor(activeYearIdx).toFixed(1)}" y1="${plotTop}" y2="${plotBottom}" />`
      : "";

    const lines = scaled
      .map((s) => {
        if (s.points.length < 2) return "";
        const linePath = s.points.map((p, idx) => `${idx === 0 ? "M" : "L"} ${xFor(p.i).toFixed(1)} ${s.yFor(p.v).toFixed(1)}`).join(" ");
        const dots = s.points
          .map((p) => {
            const isActive = activeYearIdx === p.i;
            const r = isActive ? 4.5 : 3;
            const ring = isActive ? `stroke="var(--bg)" stroke-width="2"` : "";
            return `<circle class="trend-dot" cx="${xFor(p.i).toFixed(1)}" cy="${s.yFor(p.v).toFixed(1)}" r="${r}" fill="var(${s.colorVar})" ${ring} />`;
          })
          .join("");
        return `<path d="${linePath}" fill="none" stroke="var(${s.colorVar})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />${dots}`;
      })
      .join("");

    const yearTicks = yearLabels
      .map((label, i) => {
        const cx = xFor(i);
        const half = Math.min(cx - plotLeft, plotRight - cx, (plotRight - plotLeft) / (yearLabels.length - 1) / 2);
        const hitX = cx - half, hitW = half * 2;
        return `
          <g class="trend-year-tick ${activeYearIdx === i ? "active" : ""}" data-year-idx="${i}" tabindex="0" role="button" aria-label="Show ${escapeHtml(label)} details">
            <rect x="${hitX.toFixed(1)}" y="${plotTop}" width="${hitW.toFixed(1)}" height="${(plotBottom - plotTop).toFixed(1)}" fill="transparent" />
            <text x="${cx.toFixed(1)}" y="${height - 8}" text-anchor="middle" class="chart-axis-label trend-year-label">${escapeHtml(label)}</text>
          </g>
        `;
      })
      .join("");

    const legend = chosen
      .map((s) => `<li><span class="trend-legend-line" style="background:var(${s.colorVar})"></span>${escapeHtml(s.label)}</li>`)
      .join("");

    compareArea.innerHTML = `
      <div class="trend-compare-chart">
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(chosen.map((s) => s.label).join(" vs. "))} over the last ${yearLabels.length} years">${guide}${lines}${yearTicks}</svg>
      </div>
      <ul class="trend-legend">${legend}</ul>
      <p class="trend-hint">
        Each line is scaled to its own range so trend shape reads clearly regardless of dollar size - tap
        a year below the chart to compare every selected metric's value and year-over-year change at once.
        <button type="button" class="trend-clear-btn">Clear selection</button>
      </p>
    `;
    compareArea.querySelector(".trend-clear-btn").addEventListener("click", () => {
      selected = [];
      activeYearIdx = null;
      renderTiles();
      renderCompare();
    });
    wireYearTicks(compareArea, chosen);

    if (activeYearIdx !== null) {
      const tickLabel = compareArea.querySelector(`.trend-year-tick[data-year-idx="${activeYearIdx}"] .trend-year-label`);
      showYearPopup(activeYearIdx, tickLabel, chosen);
    } else {
      hidePopup();
    }
  }

  root.querySelector(".trend-dp-close").addEventListener("click", (e) => {
    e.stopPropagation();
    activeYearIdx = null;
    renderCompare();
  });
  document.addEventListener("click", (e) => {
    if (activeYearIdx === null) return;
    if (popup.contains(e.target)) return;
    if (e.target.closest && e.target.closest(".trend-year-tick")) return;
    activeYearIdx = null;
    renderCompare();
  });

  renderTiles();
  renderCompare();
}

function renderReturnBar(x, value, barWidth, color, zeroY, yFor) {
  if (value === null || value === undefined) return "";
  const y = yFor(value);
  const top = Math.min(y, zeroY);
  const barHeight = Math.max(1, Math.abs(y - zeroY));
  const labelY = value >= 0 ? top - 4 : top + barHeight + 10;
  return `
    <rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="2" fill="${color}" />
    <text x="${(x + barWidth / 2).toFixed(1)}" y="${labelY.toFixed(1)}" text-anchor="middle" class="chart-value-label">${escapeHtml(fmtPctSigned(value))}</text>
  `;
}

function renderMarketComparisonChart(years) {
  const width = 480;
  const height = 240;
  const plotLeft = 44;
  const plotRight = width - 16;
  const plotTop = 24;
  const plotBottom = height - 32;

  const domain = computeYDomain(years.flatMap((y) => [y.stock_return_pct, y.market_return_pct]));
  if (!domain) return "";

  const yFor = (v) => plotTop + (1 - (v - domain.min) / (domain.max - domain.min)) * (plotBottom - plotTop);
  const zeroY = yFor(0);
  const groupWidth = (plotRight - plotLeft) / years.length;
  const barWidth = Math.min(20, groupWidth * 0.28);
  const gap = 3;

  const bars = years
    .map((y, i) => {
      const groupCenter = plotLeft + groupWidth * (i + 0.5);
      const stockBar = renderReturnBar(groupCenter - barWidth - gap / 2, y.stock_return_pct, barWidth, "var(--accent)", zeroY, yFor);
      const marketBar = renderReturnBar(groupCenter + gap / 2, y.market_return_pct, barWidth, "var(--muted)", zeroY, yFor);
      const yearLabel = `<text x="${groupCenter.toFixed(1)}" y="${height - 10}" text-anchor="middle" class="chart-axis-label">${escapeHtml((y.fiscal_year || "").slice(0, 4))}</text>`;
      return stockBar + marketBar + yearLabel;
    })
    .join("");

  const zeroLine = `<line x1="${plotLeft}" y1="${zeroY.toFixed(1)}" x2="${plotRight}" y2="${zeroY.toFixed(1)}" stroke="var(--border)" stroke-width="1" />`;

  return `
    <div class="chart-block">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="This stock's yearly return compared to the S&amp;P 500, last ${years.length} years">
        ${zeroLine}
        ${bars}
      </svg>
      <ul class="chart-legend">
        <li><span class="legend-swatch" style="background:var(--accent)"></span>This stock</li>
        <li><span class="legend-swatch" style="background:var(--muted)"></span>The market (S&amp;P 500)</li>
      </ul>
    </div>
  `;
}

function renderFiveYearHistory(fiveYearHistory) {
  const years = fiveYearHistory?.years;
  if (!years || years.length < 2) {
    return `
      <section class="five-year-history">
        <h3>5-Year Trend</h3>
        <p class="meta">Not enough history yet to chart a trend for this company.</p>
      </section>
    `;
  }

  const comparisonChart = renderMarketComparisonChart(years);

  return `
    <section class="five-year-history">
      <h3>5-Year Trend</h3>
      <p class="meta">Total revenue, net profit, debt, spending, and cash reserve, year by year. Tap a metric
      below to add it to the comparison chart, then tap a year to see every metric you're comparing at once.</p>
      <div class="trend-panel">
        <p class="trend-panel-label"></p>
        <div class="trend-grid trend-tile-grid"></div>
      </div>
      <div class="trend-panel">
        <p class="trend-panel-label">Comparison</p>
        <div class="trend-compare-area"></div>
      </div>
      <div class="trend-dp-popup" hidden>
        <button type="button" class="trend-dp-close" aria-label="Close">&times;</button>
        <p class="trend-dp-title"></p>
        <ul class="trend-dp-rows"></ul>
      </div>
      <p class="meta">How the stock did each year, compared to just owning the whole stock market (the S&amp;P 500).</p>
      ${comparisonChart || `<p class="meta">Not enough price history yet to compare this stock's yearly return to the market.</p>`}
    </section>
  `;
}

function renderChecklistIcon(passed) {
  if (passed === true) return '<span class="check-pass" title="Passed">✓</span>';
  if (passed === false) return '<span class="check-fail" title="Failed">✗</span>';
  return '<span class="check-unknown" title="Not enough data to evaluate">?</span>';
}

function renderChecklistRows(criteria) {
  return (criteria || [])
    .map(
      (c) =>
        `<li>${renderChecklistIcon(c.passed)}<span class="checklist-text"><span class="checklist-label">${escapeHtml(c.criterion)}</span><span class="checklist-detail">${escapeHtml(c.detail || "")}</span></span></li>`
    )
    .join("");
}

function renderValueInvesting(valueInvesting) {
  if (!valueInvesting) return "";
  const graham = valueInvesting.graham_defensive;
  const munger = valueInvesting.munger_quality;

  return `
    <section class="value-investing">
      <h3>Value Investing Checklists</h3>
      <div class="checklist-columns">
        <div class="checklist-card">
          <h4>Defensive Checklist ${graham ? `<span class="checklist-score">${graham.passed}/${graham.evaluated} evaluated</span>` : ""}</h4>
          <ul class="checklist">${renderChecklistRows(graham?.criteria)}</ul>
        </div>
        <div class="checklist-card">
          <h4>Quality Checklist ${munger ? `<span class="checklist-score">${munger.passed}/${munger.evaluated} evaluated</span>` : ""}</h4>
          <ul class="checklist">${renderChecklistRows(munger?.criteria)}</ul>
        </div>
      </div>
    </section>
  `;
}

function gateLabel(pass) {
  if (pass === true) return "Pass";
  if (pass === false) return "Fail";
  return "Not evaluated";
}

function gateClass(pass) {
  if (pass === true) return "gate-pass";
  if (pass === false) return "gate-fail";
  return "gate-unknown";
}

function renderMungerQuality(munger, mungerQualityPass) {
  if (!munger) return "";
  return `
    <div class="layered-card">
      <h4>Quality Checklist <span class="layered-gate ${gateClass(mungerQualityPass)}">${gateLabel(mungerQualityPass)}</span></h4>
      <p class="checklist-note">${munger.evaluated ? `${munger.passed}/${munger.evaluated} evaluated criteria pass` : "Not enough data to evaluate."}</p>
      <ul class="checklist">${renderChecklistRows(munger.criteria)}</ul>
      <p class="meta">Return on equity, debt discipline, dilution, and margin trend — does the business actually earn good returns on capital, not just look statistically cheap.</p>
    </div>
  `;
}

const MOAT_LABELS = {
  network_effects: "Network effects",
  cost_advantage: "Cost advantage",
  intangible_assets: "Intangible assets (brand/patents/licenses)",
  switching_costs: "Switching costs",
  efficient_scale: "Efficient scale",
  none: "None identified",
};

function renderBuffettMoat(qualitative) {
  if (!qualitative) {
    return `
      <div class="layered-card">
        <h4>Moat Read (10-K) <span class="layered-gate gate-unknown">Not run</span></h4>
        <p class="meta">Only runs for this week's per-sector finalists (cost control — this layer reads real
        filing text and spends extra AI budget per company).</p>
      </div>
    `;
  }
  const redFlags = (qualitative.red_flags || [])
    .map((f) => `<li>${escapeHtml(f)}</li>`)
    .join("");
  return `
    <div class="layered-card">
      <h4>Moat Read (10-K) <span class="layered-gate ${gateClass(qualitative.moat_present)}">${qualitative.moat_present ? "Moat found" : "No moat found"}</span></h4>
      <p><strong>${escapeHtml(MOAT_LABELS[qualitative.moat_type] || qualitative.moat_type)}</strong></p>
      <p>${escapeHtml(qualitative.moat_explanation)}</p>
      ${redFlags ? `<p class="checklist-label">Red flags from the filing</p><ul>${redFlags}</ul>` : `<p class="meta">No red flags called out in the excerpts.</p>`}
      <p class="meta">Grounded in this company's own 10-K text (extraction: ${escapeHtml(qualitative.extraction_confidence)}) —
      unlike the rest of this page, these claims are prompt-grounded, not code-verified against a fixed metric list.</p>
    </div>
  `;
}

function renderLayeredAnalysis(doc) {
  const layered = doc.layered_analysis;
  if (!layered) return "";
  const flags = (layered.flags || []).map((f) => `<li>${escapeHtml(f)}</li>`).join("");
  return `
    <section class="layered-analysis">
      <h3>Layered Analysis <span class="attribution">(the quality checklist and moat read stay visible separately, then combine with the defensive checklist and valuation gate above — via multipliers, never a naive average — into the Investment Meter)</span></h3>
      <p class="layered-overall">${escapeHtml(layered.overall)}</p>
      ${flags ? `<ul class="layered-flags">${flags}</ul>` : ""}
      <div class="layered-columns">
        ${renderMungerQuality(doc.value_investing?.munger_quality, layered.munger_quality_pass)}
        ${renderBuffettMoat(doc.qualitative)}
      </div>
    </section>
  `;
}

main();
