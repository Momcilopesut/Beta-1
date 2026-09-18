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
      ${renderScoreCard("Short-Term", doc.scores.short_term)}
      ${renderScoreCard("Long-Term", doc.scores.long_term)}
    </section>

    <section class="narrative">
      <h3>AI Summary</h3>
      <p class="one-liner">${escapeHtml(doc.narrative.one_line_summary) || "Not yet generated — run the pipeline without --skip-ai."}</p>
      <p>${escapeHtml(doc.narrative.short_term_narrative)}</p>
      <p>${escapeHtml(doc.narrative.long_term_narrative)}</p>
    </section>

    <section class="facts">
      <h3>What Matters</h3>
      ${renderFactTier("Critical", doc.narrative.facts.critical, true)}
      ${renderFactTier("Important", doc.narrative.facts.important, true)}
      ${renderFactTier("Minor", doc.narrative.facts.minor, false)}
      ${renderFactTier("Noise (safe to ignore)", doc.narrative.facts.noise, false)}
    </section>

    <section class="breakdown">
      <h3>Score Breakdown</h3>
      ${renderSubscoreTable("Short-Term", doc.scores.short_term)}
      ${renderSubscoreTable("Long-Term", doc.scores.long_term)}
    </section>

    ${renderLayeredAnalysis(doc)}

    ${renderValueInvesting(doc.value_investing)}

    ${renderSupplyDemand(doc.price)}

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

function renderScoreCard(label, score) {
  const sign = score.macro_adjustment >= 0 ? "+" : "";
  return `
    <div class="score-card ${verdictClass(score.verdict)}">
      <h3>${label}</h3>
      <p class="score-value">${formatNumber(score.final_score, { decimals: 0 })}</p>
      <p class="verdict-label">${escapeHtml(score.verdict)}</p>
      <p class="score-note">Base ${formatNumber(score.base_score, { decimals: 0 })}, ${sign}${score.macro_adjustment} macro</p>
    </div>
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

function renderSupplyDemand(price) {
  if (!price) return "";
  const relMomentum = price.sector_relative_momentum_pct;
  const volumeRatio = price.volume_vs_avg_ratio;
  if (relMomentum === null && volumeRatio === null && relMomentum === undefined && volumeRatio === undefined) {
    return "";
  }
  return `
    <section class="supply-demand">
      <h3>Supply &amp; Demand Signals</h3>
      <p class="meta">Observed divergences from the stock's own sector peers and its own average volume - a
      description of what the price/volume data shows, not a claim about why.</p>
      <ul>
        ${
          relMomentum !== null && relMomentum !== undefined
            ? `<li>3-month return is ${formatNumber(Math.abs(relMomentum), { decimals: 1, suffix: "pp" })} ${relMomentum >= 0 ? "above" : "below"} the average of its sector peers in this watchlist.</li>`
            : ""
        }
        ${
          volumeRatio !== null && volumeRatio !== undefined
            ? `<li>Recent volume is running at ${formatNumber(volumeRatio, { decimals: 2, suffix: "×" })} its own average.</li>`
            : ""
        }
      </ul>
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
      <p class="meta">A fast, deterministic filter — no AI, no news. Gates whether the qualitative/thesis layers below ran at all.</p>
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
      <p class="checklist-label">Management &amp; capital allocation</p>
      <p>${escapeHtml(qualitative.management_assessment)}</p>
      ${redFlags ? `<p class="checklist-label">Red flags from the filing</p><ul>${redFlags}</ul>` : `<p class="meta">No red flags called out in the excerpts.</p>`}
      <p class="meta">Grounded in this company's own 10-K text (extraction: ${escapeHtml(qualitative.extraction_confidence)}) —
      unlike the rest of this page, these claims are prompt-grounded, not code-verified against a fixed metric list.</p>
    </div>
  `;
}

function renderValuationSection(valuationData) {
  if (!valuationData) return "";
  const dcf = valuationData.dcf || {};
  const a = dcf.assumptions || {};
  const rel = valuationData.relative || {};
  return `
    <div class="layered-card">
      <h4>Valuation <span class="layered-gate ${gateClass(valuationData.margin_of_safety_pct !== null && valuationData.margin_of_safety_pct !== undefined ? valuationData.margin_of_safety_pct >= 15 : null)}">${
        dcf.margin_of_safety_pct === null || dcf.margin_of_safety_pct === undefined
          ? "Not evaluated"
          : formatNumber(dcf.margin_of_safety_pct, { decimals: 0, suffix: "% margin of safety" })
      }</span></h4>
      <p class="checklist-label">DCF (this pipeline's own, not FMP's)</p>
      <p class="meta">Growth ${formatNumber(a.growth_rate_pct, { decimals: 1, suffix: "%" })}/yr (${escapeHtml(a.growth_rate_source || "")}) for ${a.projection_years} years,
      then ${formatNumber(a.terminal_growth_rate_pct, { decimals: 1, suffix: "%" })} terminal growth, discounted at ${formatNumber(a.discount_rate_pct, { decimals: 1, suffix: "%" })}.</p>
      <p>Intrinsic value/share: ${dcf.intrinsic_value_per_share === null || dcf.intrinsic_value_per_share === undefined ? "—" : formatNumber(dcf.intrinsic_value_per_share, { decimals: 2, suffix: "" })}</p>
      <p class="meta">${escapeHtml(a.note || "")}</p>
      <p class="checklist-label">Relative multiples vs. sector median (this watchlist)</p>
      <p class="meta">P/E ${rel.pe_ttm === null || rel.pe_ttm === undefined ? "—" : formatNumber(rel.pe_ttm, { decimals: 1 })} vs. median ${rel.sector_median_pe_ttm === null || rel.sector_median_pe_ttm === undefined ? "—" : formatNumber(rel.sector_median_pe_ttm, { decimals: 1 })} ·
      EV/EBITDA ${rel.ev_ebitda === null || rel.ev_ebitda === undefined ? "—" : formatNumber(rel.ev_ebitda, { decimals: 1 })} vs. median ${rel.sector_median_ev_ebitda === null || rel.sector_median_ev_ebitda === undefined ? "—" : formatNumber(rel.sector_median_ev_ebitda, { decimals: 1 })}</p>
    </div>
  `;
}

function renderThesis(thesis) {
  if (!thesis) return "";
  const criteria = (thesis.falsification_criteria || []).map((c) => `<li>${escapeHtml(c)}</li>`).join("");
  return `
    <div class="thesis-block">
      <h4>Thesis</h4>
      <p>${escapeHtml(thesis.thesis)}</p>
      <h5>What would prove this wrong</h5>
      <ul>${criteria}</ul>
    </div>
  `;
}

function renderLayeredAnalysis(doc) {
  const layered = doc.layered_analysis;
  if (!layered && !doc.quant_score) return "";
  const flags = (layered?.flags || []).map((f) => `<li>${escapeHtml(f)}</li>`).join("");
  return `
    <section class="layered-analysis">
      <h3>Layered Analysis <span class="attribution">(quant screen, qualitative moat read, and valuation stay separate — never averaged into one number)</span></h3>
      ${layered ? `<p class="layered-overall">${escapeHtml(layered.overall)}</p>` : ""}
      ${flags ? `<ul class="layered-flags">${flags}</ul>` : ""}
      <div class="layered-columns">
        ${renderQuantScorecard(doc.quant_score)}
        ${renderQualitative(doc.qualitative)}
        ${renderValuationSection(doc.valuation)}
      </div>
      ${renderThesis(doc.thesis)}
    </section>
  `;
}

function renderSubscoreTable(label, score) {
  const rows = score.subscores
    .map(
      (sub) => `
    <tr>
      <td>${escapeHtml(sub.label)}</td>
      <td>${sub.weight_pct}%</td>
      <td>${formatNumber(sub.score, { decimals: 0 })}</td>
      <td>${sub.raw_metrics
        .map((m) => `${escapeHtml(m.metric)}: ${m.raw_value === null ? "—" : escapeHtml(m.raw_value)}`)
        .join(", ")}</td>
    </tr>`
    )
    .join("");
  return `
    <h4>${label}</h4>
    <table class="subscore-table">
      <thead><tr><th>Component</th><th>Weight</th><th>Score</th><th>Raw inputs</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

main();
