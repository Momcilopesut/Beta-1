import {
  fetchJSON,
  verdictClass,
  formatNumber,
  escapeHtml,
  renderDisclaimerFooter,
  lookupTicker,
} from "./shared.js";
import { METRIC_GLOSSARY, glossaryEntry } from "./metrics-glossary.js";
import { computeInvestmentMeter } from "./meter-calculator.js";

function tickerFromQuery() {
  return new URLSearchParams(window.location.search).get("ticker");
}

async function main() {
  const content = document.getElementById("content");
  const ticker = tickerFromQuery();

  if (!ticker) {
    content.innerHTML = `<p class="error">No ticker specified. Go back to <a href="index.html">this week's top picks</a>.</p>`;
    renderDisclaimerFooter();
    return;
  }

  document.title = `${ticker} – Company Detail`;

  try {
    const doc = await fetchJSON(`../data/companies/${encodeURIComponent(ticker)}.json`);
    content.innerHTML = render(doc);
    wireWhatIfCalculator(doc);
  } catch {
    renderNotTracked(content, ticker);
  }
  renderDisclaimerFooter();
}

function renderNotTracked(content, ticker) {
  const safeTicker = escapeHtml(ticker);
  content.innerHTML = `
    <section class="not-tracked">
      <p class="error">${safeTicker} isn't in the current screening universe.</p>
      <p class="meta">You can run a live, on-demand analysis instead — the same scoring, checklists,
      and AI narrative as the tracked companies, computed fresh right now via a separate lookup
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
    wireWhatIfCalculator(doc);
  } catch (err) {
    content.innerHTML = `
      <p class="error">Live analysis failed for ${safeTicker}: ${escapeHtml(err.message)}</p>
      <button id="run-live-lookup" class="live-lookup-button">Try again</button>
    `;
    document.getElementById("run-live-lookup").addEventListener("click", () => runLiveLookup(content, ticker));
  }
}

function render(doc) {
  const onDemandBanner = doc.on_demand
    ? `<p class="on-demand-banner">Live on-demand analysis — not part of the tracked watchlist, computed just now.</p>`
    : "";
  return `
    ${onDemandBanner}
    <section class="detail-header">
      <h2>${escapeHtml(doc.name)} <span class="ticker-tag">${escapeHtml(doc.ticker)}</span></h2>
      <p class="meta">${escapeHtml(doc.sector || "—")} · ${escapeHtml(doc.industry || "—")} · Updated ${escapeHtml(doc.last_updated)}</p>
    </section>

    <section class="verdicts-detail">
      ${renderConvictionCard(doc.layered_analysis)}
    </section>

    ${renderKeyMetricsReference(doc.metrics)}

    ${renderBalanceSheetBasics(doc.fundamentals, doc.layered_analysis)}

    ${renderFiveYearHistory(doc.five_year_history)}

    <section class="narrative">
      <h3>AI Summary</h3>
      <p class="one-liner">${escapeHtml(doc.narrative.one_line_summary) || "Not yet generated — run the pipeline without --skip-ai."}</p>
      <p>${escapeHtml(doc.narrative.narrative)}</p>
    </section>

    <section class="facts">
      <h3>What Matters</h3>
      ${renderFactTier("Critical", doc.narrative.facts.critical, true)}
      ${renderFactTier("Important", doc.narrative.facts.important, true)}
      ${renderFactTier("Minor", doc.narrative.facts.minor, false)}
      ${renderFactTier("Noise (safe to ignore)", doc.narrative.facts.noise, false)}
    </section>

    ${renderLayeredAnalysis(doc)}

    ${renderValueInvesting(doc.value_investing)}

    ${renderWhatIfCalculator(doc)}

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
        <h3>Investment Meter <span class="attribution">(Graham · Buffett · Munger)</span></h3>
        ${gauge}
        <p class="score-note">Needs Graham's checklist to have evaluated data.</p>
      </div>
    `;
  }
  const b = layered.conviction_score_breakdown || {};
  return `
    <div class="score-card ${verdictClass(layered.conviction_verdict)} meter-card">
      <h3>Investment Meter <span class="attribution">(Graham · Buffett · Munger)</span></h3>
      ${gauge}
      <p class="score-note">Graham checklist ${formatNumber(b.base_score, { decimals: 0 })}% ×
      ${formatNumber(b.munger_multiplier, { decimals: 2 })} Munger quality ×
      ${formatNumber(b.moat_multiplier, { decimals: 2 })} Buffett moat ×
      ${formatNumber(b.valuation_multiplier, { decimals: 2 })} Graham valuation</p>
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
    return `
      <details class="metric-row">
        <summary>
          <span class="metric-label">${escapeHtml(m.label)}</span>
          <span class="metric-value">${escapeHtml(formatMetricValue(m.key, value))}</span>
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
      <p class="meta">This company's own numbers - tap any row for what it means and why it matters.</p>
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
      <p class="meta">Price ÷ book value: ${fmt(valuation?.pb_ratio, 2)}× · Graham Number (a simple fair-value estimate from earnings and book value): $${fmt(valuation?.graham_number, 2)}, a margin of safety of ${fmt(valuation?.graham_upside_pct, 0, "%")}</p>
      ${
        valuation?.ncav_margin_pct !== null && valuation?.ncav_margin_pct !== undefined && valuation.ncav_margin_pct > 0
          ? `<p class="meta">Graham's strictest test also passes: even just the current assets, after paying off every liability, are worth ${fmt(valuation.ncav_margin_pct, 0, "%")} more than the whole stock costs today.</p>`
          : ""
      }
      ${
        layered?.required_margin_of_safety_pct !== undefined && layered?.required_margin_of_safety_pct !== null
          ? `<p class="meta">Required margin of safety: ${formatNumber(layered.required_margin_of_safety_pct, { decimals: 0, suffix: "%" })} (Graham's convention — a real discount to estimated fair value, not just trading below it by any amount).</p>`
          : ""
      }
    </section>
  `;
}

// --- 5-year history: earnings/spending/cash/debt over time, and this
// stock's yearly return vs. the market (SPY, standing in for "the stock
// market average") over the same years. Plain inline SVG, same approach as
// the meter gauge above - no charting library. ---

const HISTORY_SERIES = [
  { key: "earnings", label: "Earnings", colorVar: "--hist-earnings" },
  { key: "spending", label: "Spending", colorVar: "--hist-spending" },
  { key: "cash", label: "Cash", colorVar: "--hist-cash" },
  { key: "debt", label: "Debt", colorVar: "--hist-debt" },
];

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

function renderFundamentalsTrendChart(years) {
  const width = 480;
  const height = 260;
  const plotLeft = 60;
  const plotRight = width - 66;
  const plotTop = 16;
  const plotBottom = height - 32;

  const domain = computeYDomain(years.flatMap((y) => HISTORY_SERIES.map((s) => y[s.key])));
  if (!domain) return "";

  const xFor = (i) => plotLeft + (i / (years.length - 1)) * (plotRight - plotLeft);
  const yFor = (v) => plotTop + (1 - (v - domain.min) / (domain.max - domain.min)) * (plotBottom - plotTop);

  const gridlines = [0, 0.5, 1]
    .map((f) => {
      const value = domain.min + f * (domain.max - domain.min);
      const y = yFor(value);
      return `
        <line x1="${plotLeft}" y1="${y.toFixed(1)}" x2="${plotRight}" y2="${y.toFixed(1)}" stroke="var(--border)" stroke-width="1" />
        <text x="${(plotLeft - 8).toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="end" class="chart-axis-label">${escapeHtml(fmtDollars(value))}</text>
      `;
    })
    .join("");

  const xLabels = years
    .map(
      (y, i) =>
        `<text x="${xFor(i).toFixed(1)}" y="${height - 10}" text-anchor="middle" class="chart-axis-label">${escapeHtml((y.fiscal_year || "").slice(0, 4))}</text>`
    )
    .join("");

  const seriesSvg = HISTORY_SERIES.map((s) => {
    const points = years.map((y, i) => ({ i, v: y[s.key] })).filter((p) => p.v !== null && p.v !== undefined);
    if (!points.length) return "";
    const path = points.map((p, idx) => `${idx === 0 ? "M" : "L"} ${xFor(p.i).toFixed(1)} ${yFor(p.v).toFixed(1)}`).join(" ");
    const dots = points
      .map(
        (p) =>
          `<circle cx="${xFor(p.i).toFixed(1)}" cy="${yFor(p.v).toFixed(1)}" r="4" fill="var(${s.colorVar})" stroke="var(--bg)" stroke-width="2" />`
      )
      .join("");
    const last = points[points.length - 1];
    const endLabel = `<text x="${(xFor(last.i) + 7).toFixed(1)}" y="${(yFor(last.v) + 3).toFixed(1)}" class="chart-end-label">${escapeHtml(fmtDollars(last.v))}</text>`;
    return `<path d="${path}" fill="none" stroke="var(${s.colorVar})" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />${dots}${endLabel}`;
  }).join("");

  const legend = HISTORY_SERIES.map(
    (s) => `<li><span class="legend-swatch" style="background:var(${s.colorVar})"></span>${escapeHtml(s.label)}</li>`
  ).join("");

  return `
    <div class="chart-block">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Earnings, spending, cash, and debt over the last ${years.length} years">
        ${gridlines}
        ${seriesSvg}
        ${xLabels}
      </svg>
      <ul class="chart-legend">${legend}</ul>
    </div>
  `;
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

  const trendChart = renderFundamentalsTrendChart(years);
  const comparisonChart = renderMarketComparisonChart(years);

  return `
    <section class="five-year-history">
      <h3>5-Year Trend</h3>
      <p class="meta">How much the company earned, spent, kept in cash, and owed, year by year.</p>
      ${trendChart || `<p class="meta">Not enough data yet to chart this.</p>`}
      <p class="meta">How the stock did each year, compared to just owning the whole stock market (the S&amp;P 500).</p>
      ${comparisonChart || `<p class="meta">Not enough price history yet to compare this stock's yearly return to the market.</p>`}
    </section>
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
      <h3>Value Investing Checklists <span class="attribution">(Graham / Munger)</span></h3>
      <div class="checklist-columns">
        <div class="checklist-card">
          <h4>Graham Defensive Investor ${graham ? `<span class="checklist-score">${graham.passed}/${graham.evaluated} evaluated</span>` : ""}</h4>
          <ul class="checklist">${renderChecklistRows(graham?.criteria)}</ul>
        </div>
        <div class="checklist-card">
          <h4>Munger Quality Checklist ${munger ? `<span class="checklist-score">${munger.passed}/${munger.evaluated} evaluated</span>` : ""}</h4>
          <ul class="checklist">${renderChecklistRows(munger?.criteria)}</ul>
        </div>
      </div>
    </section>
  `;
}

// --- What-If: Investment Meter Calculator. Drag a metric, watch the score
// recompute live - entirely client-side via site/js/meter-calculator.js,
// seeded from this company's own real data so it starts in exact agreement
// with the page's own displayed score. ---

const CALC_SLIDERS = [
  { key: "marketCap", label: "Market cap", min: 0, max: 3e12, fmt: (v) => fmtDollars(v), criterion: "Graham #1: adequate size (≥ $2B)" },
  { key: "currentRatio", label: "Current ratio", min: 0, max: 5, fmt: (v) => fmt(v, 2), criterion: "Graham #2: financial condition, simplified (≥ 2)" },
  { key: "epsGrowthCagr3yr", label: "EPS growth (3yr CAGR)", min: -30, max: 60, fmt: (v) => fmt(v, 1, "%"), criterion: "Graham #5: earnings growth (≥ 2.9%/yr)" },
  { key: "peTtm", label: "P/E", min: 0, max: 60, fmt: (v) => fmt(v, 1, "×"), criterion: "Graham #6: moderate P/E (≤ 15)" },
  { key: "pbRatio", label: "P/B", min: 0, max: 20, fmt: (v) => fmt(v, 2, "×"), criterion: "Graham #7: P/E × P/B with the row above (≤ 22.5)" },
  { key: "roePct", label: "ROE", min: -20, max: 150, fmt: (v) => fmt(v, 1, "%"), criterion: "Munger #1: return on equity (≥ 15%)" },
  { key: "debtToEquity", label: "Debt / Equity", min: 0, max: 5, fmt: (v) => fmt(v, 2), criterion: "Munger #2: debt discipline (≤ 1.0)" },
  { key: "marginOfSafetyPct", label: "Margin of safety (Graham upside)", min: -100, max: 100, fmt: (v) => fmt(v, 1, "%"), criterion: "Graham's valuation gate (≥ 15%)" },
];

const CALC_TOGGLES = [
  { key: "earningsStability", label: "Graham #3: earnings stability (positive net income every year)" },
  { key: "dividendRecord", label: "Graham #4: currently pays a dividend" },
  { key: "dilution", label: "Munger #3: not diluting shareholders" },
  { key: "moatPresent", label: "Buffett: durable moat present" },
];

function extendedRange(seed, min, max) {
  if (seed === null || seed === undefined) return { min, max };
  return { min: Math.min(min, seed), max: Math.max(max, seed) };
}

function seedCalculatorInputs(doc) {
  const metrics = doc.metrics || {};
  const graham = doc.value_investing?.graham_defensive?.criteria || [];
  const munger = doc.value_investing?.munger_quality?.criteria || [];
  const findPassed = (criteria, substr) => {
    const match = criteria.find((c) => c.criterion.toLowerCase().includes(substr));
    return match ? match.passed : null;
  };
  const marginTrendLabel = { 20: "declining", 60: "stable", 100: "improving" }[metrics.margin_trend_score] ?? null;

  return {
    marketCap: doc.market_cap ?? null,
    currentRatio: metrics.current_ratio ?? null,
    earningsStability: findPassed(graham, "earnings stability"),
    dividendRecord: findPassed(graham, "dividend"),
    epsGrowthCagr3yr: metrics.eps_growth_cagr_3yr_pct ?? null,
    peTtm: metrics.pe_ttm ?? null,
    pbRatio: metrics.pb_ratio ?? null,
    roePct: metrics.roe_pct ?? null,
    debtToEquity: metrics.debt_to_equity ?? null,
    dilution: findPassed(munger, "diluting"),
    marginTrend: marginTrendLabel,
    moatPresent: doc.qualitative ? doc.qualitative.moat_present : null,
    marginOfSafetyPct: metrics.graham_upside_pct ?? null,
  };
}

function renderCalcResult(result) {
  const gauge = renderMeterGauge(result.score, result.verdict);
  const breakdown = result.breakdown
    ? `<p class="score-note">Graham checklist ${fmt(result.breakdown.baseScore, 0)}% ×
       ${fmt(result.breakdown.mungerMultiplier, 2)} Munger quality ×
       ${fmt(result.breakdown.moatMultiplier, 2)} Buffett moat ×
       ${fmt(result.breakdown.valuationMultiplier, 2)} Graham valuation</p>`
    : `<p class="score-note">Not enough data to score.</p>`;

  return `
    <div class="score-card ${result.verdict ? verdictClass(result.verdict) : "verdict-neutral"} meter-card">
      ${gauge}
      ${breakdown}
    </div>
    <div class="checklist-columns">
      <div class="checklist-card">
        <h4>Graham Defensive <span class="checklist-score">${result.graham.passed}/${result.graham.evaluated} evaluated</span></h4>
        <ul class="checklist">${renderChecklistRows(result.graham.criteria)}</ul>
      </div>
      <div class="checklist-card">
        <h4>Munger Quality <span class="checklist-score">${result.munger.passed}/${result.munger.evaluated} evaluated</span></h4>
        <ul class="checklist">${renderChecklistRows(result.munger.criteria)}</ul>
      </div>
    </div>
  `;
}

function renderWhatIfCalculator(doc) {
  const actualScore = doc.layered_analysis?.conviction_score;
  if (actualScore === null || actualScore === undefined) {
    return `
      <section class="what-if-calculator">
        <h3>What-If: Investment Meter Calculator</h3>
        <p class="meta">Needs Graham's checklist to have evaluated data before this becomes interactive.</p>
      </section>
    `;
  }

  const seed = seedCalculatorInputs(doc);

  const sliderRows = CALC_SLIDERS.map((c) => {
    const value = seed[c.key];
    const range = extendedRange(value, c.min, c.max);
    return `
      <div class="calc-row">
        <label for="calc-${c.key}">${escapeHtml(c.label)}<span class="calc-hint">${escapeHtml(c.criterion)}</span></label>
        <div class="calc-control">
          <input type="range" id="calc-${c.key}" min="${range.min}" max="${range.max}" step="any"
            value="${value ?? range.min}" ${value === null ? "disabled" : ""} />
          <output id="calc-${c.key}-out">${escapeHtml(c.fmt(value))}</output>
        </div>
      </div>
    `;
  }).join("");

  const marginTrendRow = `
    <div class="calc-row">
      <label for="calc-marginTrend">Margin trend<span class="calc-hint">Munger #4: margins stable or improving</span></label>
      <select id="calc-marginTrend">
        <option value="declining" ${seed.marginTrend === "declining" ? "selected" : ""}>Declining</option>
        <option value="stable" ${seed.marginTrend === "stable" ? "selected" : ""}>Stable</option>
        <option value="improving" ${seed.marginTrend === "improving" ? "selected" : ""}>Improving</option>
      </select>
    </div>
  `;

  const toggleRows = CALC_TOGGLES.map(
    (c) => `
      <div class="calc-row">
        <label for="calc-${c.key}">${escapeHtml(c.label)}</label>
        <select id="calc-${c.key}">
          <option value="true" ${seed[c.key] === true ? "selected" : ""}>Pass</option>
          <option value="false" ${seed[c.key] === false ? "selected" : ""}>Fail</option>
          <option value="null" ${seed[c.key] === null ? "selected" : ""}>Unknown</option>
        </select>
      </div>
    `
  ).join("");

  return `
    <section class="what-if-calculator">
      <h3>What-If: Investment Meter Calculator</h3>
      <p class="meta">Drag a metric and watch the Investment Meter recompute live - a way to see how much (or how
      little) one number actually moves the overall score. Runs entirely in your browser, seeded from this
      company's real data below, so it starts in exact agreement with the score above. One simplification: the
      "financial condition" row here checks only the current ratio, not the full debt-vs-working-capital test the
      real screen also applies.</p>
      <div class="calc-layout">
        <div class="calc-controls">
          ${sliderRows}
          ${marginTrendRow}
          ${toggleRows}
          <button type="button" id="calc-reset" class="live-lookup-button">Reset to actual</button>
        </div>
        <div class="calc-result" id="calc-result"></div>
      </div>
    </section>
  `;
}

function wireWhatIfCalculator(doc) {
  const section = document.querySelector(".what-if-calculator");
  const resultEl = document.getElementById("calc-result");
  if (!section || !resultEl) return;

  const seed = seedCalculatorInputs(doc);
  const inputs = { ...seed };

  function updateResult() {
    resultEl.innerHTML = renderCalcResult(computeInvestmentMeter(inputs));
  }

  CALC_SLIDERS.forEach((c) => {
    const el = document.getElementById(`calc-${c.key}`);
    const out = document.getElementById(`calc-${c.key}-out`);
    if (!el) return;
    el.addEventListener("input", () => {
      const v = parseFloat(el.value);
      inputs[c.key] = Number.isNaN(v) ? null : v;
      if (out) out.textContent = c.fmt(inputs[c.key]);
      updateResult();
    });
  });

  const marginTrendEl = document.getElementById("calc-marginTrend");
  marginTrendEl?.addEventListener("change", () => {
    inputs.marginTrend = marginTrendEl.value;
    updateResult();
  });

  CALC_TOGGLES.forEach((c) => {
    const el = document.getElementById(`calc-${c.key}`);
    if (!el) return;
    el.addEventListener("change", () => {
      inputs[c.key] = el.value === "true" ? true : el.value === "false" ? false : null;
      updateResult();
    });
  });

  document.getElementById("calc-reset")?.addEventListener("click", () => {
    Object.assign(inputs, seed);
    CALC_SLIDERS.forEach((c) => {
      const el = document.getElementById(`calc-${c.key}`);
      const out = document.getElementById(`calc-${c.key}-out`);
      if (el) el.value = inputs[c.key] ?? el.min;
      if (out) out.textContent = c.fmt(inputs[c.key]);
    });
    if (marginTrendEl) marginTrendEl.value = inputs.marginTrend;
    CALC_TOGGLES.forEach((c) => {
      const el = document.getElementById(`calc-${c.key}`);
      if (el) el.value = inputs[c.key] === true ? "true" : inputs[c.key] === false ? "false" : "null";
    });
    updateResult();
  });

  updateResult();
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

function renderQuantScorecard(quantScore) {
  if (!quantScore) return "";
  const rows = Object.entries(quantScore.metrics || {})
    .map(([key, m]) => {
      const comparator = m.higher_is_better ? "&ge;" : "&le;";
      return `<li>${renderChecklistIcon(m.pass)}<span class="checklist-text"><span class="checklist-label">${escapeHtml(m.label)}</span><span class="checklist-detail">${m.value === null ? "no data" : formatNumber(m.value, { decimals: 1 })} (threshold ${comparator} ${m.threshold})</span></span></li>`;
    })
    .join("");
  return `
    <div class="layered-card">
      <h4>Quant Screen <span class="layered-gate ${gateClass(quantScore.gate_pass)}">${gateLabel(quantScore.gate_pass)}</span></h4>
      <p class="checklist-note">${quantScore.evaluated ? `${quantScore.passed}/${quantScore.evaluated} evaluated metrics pass (${formatNumber(quantScore.quant_score_pct, { decimals: 0, suffix: "%" })})` : "Not enough data to evaluate."}</p>
      <ul class="checklist">${rows}</ul>
      <p class="meta">A fast, deterministic balance-sheet/cash filter — no AI, no news. Gates whether the qualitative layer below ran at all.</p>
    </div>
  `;
}

function renderMungerQuality(munger, mungerQualityPass) {
  if (!munger) return "";
  return `
    <div class="layered-card">
      <h4>Munger Quality <span class="layered-gate ${gateClass(mungerQualityPass)}">${gateLabel(mungerQualityPass)}</span></h4>
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

function renderQualitative(qualitative) {
  if (!qualitative) {
    return `
      <div class="layered-card">
        <h4>Qualitative (10-K) <span class="layered-gate gate-unknown">Not run</span></h4>
        <p class="meta">Only runs for companies that pass the quant screen (cost control — this layer reads real
        filing text and spends extra AI budget per company).</p>
      </div>
    `;
  }
  const redFlags = (qualitative.red_flags || [])
    .map((f) => `<li>${escapeHtml(f)}</li>`)
    .join("");
  return `
    <div class="layered-card">
      <h4>Qualitative (10-K) <span class="layered-gate ${gateClass(qualitative.moat_present)}">${qualitative.moat_present ? "Moat found" : "No moat found"}</span></h4>
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
  if (!layered && !doc.quant_score) return "";
  const flags = (layered?.flags || []).map((f) => `<li>${escapeHtml(f)}</li>`).join("");
  return `
    <section class="layered-analysis">
      <h3>Layered Analysis <span class="attribution">(the quant screen, Munger's quality checklist, and Buffett's moat read stay visible separately, then combine with Graham's valuation gate above — via gates and multipliers, never a naive average — into the Investment Meter)</span></h3>
      ${layered ? `<p class="layered-overall">${escapeHtml(layered.overall)}</p>` : ""}
      ${flags ? `<ul class="layered-flags">${flags}</ul>` : ""}
      <div class="layered-columns">
        ${renderQuantScorecard(doc.quant_score)}
        ${renderMungerQuality(doc.value_investing?.munger_quality, layered?.munger_quality_pass)}
        ${renderQualitative(doc.qualitative)}
      </div>
    </section>
  `;
}

main();
