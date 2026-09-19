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

const CONVICTION_COMPONENT_LABELS = {
  graham_pct: "Graham checklist",
  piotroski_pct: "Piotroski F-Score",
};

function renderConvictionCard(layered) {
  if (!layered || layered.conviction_score === null || layered.conviction_score === undefined) {
    return `
      <div class="score-card verdict-neutral">
        <h3>Conviction Score</h3>
        <p class="score-value">—</p>
        <p class="verdict-label">Not enough data</p>
        <p class="score-note">Needs the Graham or Piotroski checklist to have evaluated data.</p>
      </div>
    `;
  }
  const b = layered.conviction_score_breakdown || {};
  const parts = Object.entries(b.components || {})
    .map(([key, value]) => `${CONVICTION_COMPONENT_LABELS[key] || key} ${formatNumber(value, { decimals: 0 })}`)
    .join(", ");
  return `
    <div class="score-card ${verdictClass(layered.conviction_verdict)}">
      <h3>Conviction Score</h3>
      <p class="score-value">${formatNumber(layered.conviction_score, { decimals: 0 })}</p>
      <p class="verdict-label">${escapeHtml(layered.conviction_verdict)}</p>
      <p class="score-note">Base ${formatNumber(b.base_score, { decimals: 0 })} (${parts}) × ${formatNumber(b.moat_multiplier, { decimals: 2 })} moat × ${formatNumber(b.valuation_multiplier, { decimals: 2 })} valuation</p>
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
          ? `<p class="meta">Required margin of safety for this company: ${formatNumber(layered.required_margin_of_safety_pct, { decimals: 0, suffix: "%" })} (Klarman: scales up with red flags / thin data, not a flat number — see README).</p>`
          : ""
      }
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

function renderValueInvesting(valueInvesting) {
  if (!valueInvesting) return "";
  const graham = valueInvesting.graham_defensive;
  const piotroski = valueInvesting.piotroski_f_score;

  const grahamRows = (graham?.criteria || [])
    .map(
      (c) =>
        `<li>${renderChecklistIcon(c.passed)}<span class="checklist-text"><span class="checklist-label">${escapeHtml(c.criterion)}</span><span class="checklist-detail">${escapeHtml(c.detail)}</span></span></li>`
    )
    .join("");

  const piotroskiRows = (piotroski?.criteria || [])
    .map(
      (c) =>
        `<li>${renderChecklistIcon(c.passed)}<span class="checklist-text"><span class="checklist-label">${escapeHtml(c.criterion)}</span></span></li>`
    )
    .join("");

  const piotroskiNote = piotroski?.note
    ? `<p class="checklist-note">${escapeHtml(piotroski.note)}</p>`
    : "";

  return `
    <section class="value-investing">
      <h3>Value Investing Checklist <span class="attribution">(Graham / Buffett / Munger frameworks)</span></h3>
      <div class="checklist-columns">
        <div class="checklist-card">
          <h4>Graham Defensive Investor ${graham ? `<span class="checklist-score">${graham.passed}/${graham.evaluated} evaluated</span>` : ""}</h4>
          <ul class="checklist">${grahamRows}</ul>
        </div>
        <div class="checklist-card">
          <h4>Piotroski F-Score ${piotroski ? `<span class="checklist-score">${piotroski.score}/${piotroski.evaluated} evaluated (max 9)</span>` : ""}</h4>
          ${piotroskiNote}
          <ul class="checklist">${piotroskiRows}</ul>
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
      <h3>Layered Analysis <span class="attribution">(quant screen and qualitative moat read stay visible separately, then combine with the balance-sheet valuation gate above — via gates and multipliers, never a naive average — into the Conviction Score)</span></h3>
      ${layered ? `<p class="layered-overall">${escapeHtml(layered.overall)}</p>` : ""}
      ${flags ? `<ul class="layered-flags">${flags}</ul>` : ""}
      <div class="layered-columns">
        ${renderQuantScorecard(doc.quant_score)}
        ${renderQualitative(doc.qualitative)}
      </div>
    </section>
  `;
}

main();
