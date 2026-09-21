import {
  fetchJSON,
  verdictClass,
  formatNumber,
  escapeHtml,
  renderDisclaimerFooter,
  lookupTicker,
} from "./shared.js";

function tickerFromQuery() {
  return new URLSearchParams(window.location.search).get("ticker");
}

async function main() {
  const content = document.getElementById("content");
  const ticker = tickerFromQuery();

  if (!ticker) {
    content.innerHTML = `<p class="error">No ticker specified. Go back to the <a href="index.html">watchlist</a>.</p>`;
    renderDisclaimerFooter();
    return;
  }

  document.title = `${ticker} – Company Detail`;

  try {
    const doc = await fetchJSON(`../data/companies/${encodeURIComponent(ticker)}.json`);
    content.innerHTML = render(doc);
  } catch {
    renderNotTracked(content, ticker);
  }
  renderDisclaimerFooter();
}

function renderNotTracked(content, ticker) {
  const safeTicker = escapeHtml(ticker);
  content.innerHTML = `
    <section class="not-tracked">
      <p class="error">${safeTicker} isn't in the tracked watchlist.</p>
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
