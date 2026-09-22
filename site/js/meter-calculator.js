// A client-side mirror of the Investment Meter's real scoring chain, so
// the "what-if" calculator on the company page can recompute the score
// live as someone drags a metric - without a round trip to the server.
//
// This MUST be kept in sync by hand with the Python source of truth:
//   - Graham's 7-criterion checklist: pipeline/scoring/value_investing.py::graham_defensive_checklist
//   - Munger's 4-criterion checklist: pipeline/scoring/value_investing.py::munger_quality_checklist
//   - The multiplier chain + verdict bands: pipeline/scoring/aggregation.py::build_conviction_score,
//     pipeline/scoring/thresholds.py::verdict_for, and config/conviction_score.yaml's values.
// That's the known trade-off of computing this in the browser: a real
// change to those Python files needs the same change made here too.
//
// One deliberate simplification, clearly surfaced in the UI rather than
// silently dropped: Graham criterion 2 ("strong financial condition") is
// current_ratio >= 2 alone here. The real backend also requires
// total debt <= working capital, whose raw dollar components aren't part
// of the JSON this page already has - simulating that half would need data
// this calculator doesn't have access to.

const MUNGER_QUALITY_PASS_FRACTION = 0.5;
const REQUIRED_MARGIN_OF_SAFETY_PCT = 15.0;
const MARGIN_TREND_SCORE = { declining: 20, stable: 60, improving: 100 };

const MULTIPLIERS = {
  moat: { present: 1.05, absent: 0.7, notEvaluated: 1.0 },
  munger: { present: 1.1, absent: 0.75, notEvaluated: 1.0 },
  valuation: { pass: 1.0, fail: 0.55, notEvaluated: 1.0 },
};

const VERDICT_BANDS = [
  { min: 75, label: "Strong" },
  { min: 60, label: "Favorable" },
  { min: 40, label: "Neutral" },
  { min: 25, label: "Cautious" },
  { min: 0, label: "Weak" },
];

function verdictFor(score) {
  for (const band of VERDICT_BANDS) {
    if (score >= band.min) return band.label;
  }
  return VERDICT_BANDS[VERDICT_BANDS.length - 1].label;
}

function tally(criteria) {
  const evaluated = criteria.filter((c) => c.passed !== null);
  const passed = evaluated.filter((c) => c.passed === true);
  return { criteria, passed: passed.length, evaluated: evaluated.length };
}

export function grahamChecklist(inputs) {
  const grahamMultiple = inputs.peTtm != null && inputs.pbRatio != null ? inputs.peTtm * inputs.pbRatio : null;
  const criteria = [
    { criterion: "Adequate size (market cap >= $2B)", passed: inputs.marketCap == null ? null : inputs.marketCap >= 2_000_000_000 },
    {
      criterion: "Strong financial condition (current ratio >= 2, simplified)",
      passed: inputs.currentRatio == null ? null : inputs.currentRatio >= 2,
    },
    { criterion: "Earnings stability (positive net income every year)", passed: inputs.earningsStability },
    { criterion: "Currently pays a dividend", passed: inputs.dividendRecord },
    {
      criterion: "Earnings growth (>= ~2.9%/yr)",
      passed: inputs.epsGrowthCagr3yr == null ? null : inputs.epsGrowthCagr3yr >= 2.9,
    },
    { criterion: "Moderate P/E (<= 15)", passed: inputs.peTtm == null ? null : inputs.peTtm > 0 && inputs.peTtm <= 15 },
    { criterion: "Moderate P/E x P/B (<= 22.5)", passed: grahamMultiple == null ? null : grahamMultiple <= 22.5 },
  ];
  return { ...tally(criteria), grahamMultiple };
}

export function mungerChecklist(inputs) {
  const marginTrendScore = inputs.marginTrend ? MARGIN_TREND_SCORE[inputs.marginTrend] : null;
  const criteria = [
    { criterion: "Strong return on equity (>= 15%)", passed: inputs.roePct == null ? null : inputs.roePct >= 15 },
    { criterion: "Not overloaded with debt (debt/equity <= 1.0)", passed: inputs.debtToEquity == null ? null : inputs.debtToEquity <= 1.0 },
    { criterion: "Not diluting shareholders", passed: inputs.dilution },
    { criterion: "Margins stable or improving", passed: marginTrendScore == null ? null : marginTrendScore >= 60 },
  ];
  return tally(criteria);
}

function mungerQualityPass(munger) {
  if (!munger.evaluated) return null;
  return munger.passed / munger.evaluated >= MUNGER_QUALITY_PASS_FRACTION;
}

function multiplierFor(block, value) {
  if (value === true) return block.present ?? block.pass;
  if (value === false) return block.absent ?? block.fail;
  return block.notEvaluated;
}

/**
 * inputs: {marketCap, currentRatio, earningsStability, dividendRecord,
 * epsGrowthCagr3yr, peTtm, pbRatio, roePct, debtToEquity, dilution,
 * marginTrend, moatPresent, marginOfSafetyPct}. Booleans (earningsStability,
 * dividendRecord, dilution, moatPresent) are true/false/null - null means
 * "not evaluated," never a guessed pass or fail.
 *
 * Returns {score, verdict, breakdown, graham, munger, valuationGate} -
 * score/verdict are null when Graham's checklist has no evaluated data,
 * mirroring aggregation.py::build_conviction_score exactly.
 */
export function computeInvestmentMeter(inputs) {
  const graham = grahamChecklist(inputs);
  const munger = mungerChecklist(inputs);
  const mungerPass = mungerQualityPass(munger);
  const valuationGate = inputs.marginOfSafetyPct == null ? null : inputs.marginOfSafetyPct >= REQUIRED_MARGIN_OF_SAFETY_PCT;

  if (!graham.evaluated) {
    return { score: null, verdict: null, breakdown: null, graham, munger, mungerPass, valuationGate };
  }

  const baseScore = (graham.passed / graham.evaluated) * 100;
  const moatMultiplier = multiplierFor(MULTIPLIERS.moat, inputs.moatPresent);
  const mungerMultiplier = multiplierFor(MULTIPLIERS.munger, mungerPass);
  const valuationMultiplier = multiplierFor(MULTIPLIERS.valuation, valuationGate);

  const raw = baseScore * moatMultiplier * mungerMultiplier * valuationMultiplier;
  const score = Math.round(Math.max(0, Math.min(100, raw)) * 10) / 10;

  return {
    score,
    verdict: verdictFor(score),
    breakdown: {
      baseScore: Math.round(baseScore * 10) / 10,
      moatMultiplier,
      mungerMultiplier,
      valuationMultiplier,
    },
    graham,
    munger,
    mungerPass,
    valuationGate,
  };
}
