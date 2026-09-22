// Every metric this tool scores on, in one place: what it is, why it
// matters economically, and how swings in it actually affect the business
// (not just the number). Shared by site/glossary.html (the full reference
// page) and site/js/company.js (the per-company "Key Metrics Reference"
// section) - written once so the two never drift apart.
//
// Keys match pipeline/scoring/fundamentals.py's `metrics` dict exactly.

export const METRIC_GLOSSARY = [
  {
    key: "pe_ttm",
    label: "P/E (Price / Earnings)",
    explanation:
      "Price divided by trailing twelve-month earnings per share - how many years of today's profit you're paying for at the current price.",
    significance:
      "The most widely used shorthand for whether a stock is cheap or expensive relative to what it actually earns. This tool's defensive checklist caps this at 15 as a plain check against overpaying.",
    volatilityImpact:
      "Can swing sharply even when the business hasn't changed at all - a falling stock price or a temporary earnings dip both push it up. A P/E that's high because earnings collapsed is a very different situation than one caused by investor optimism, so this number should never be read alone.",
  },
  {
    key: "pb_ratio",
    label: "P/B (Price / Book)",
    explanation:
      "Price divided by book value per share (shareholders' equity ÷ shares outstanding) - what you're paying relative to the accounting net worth already on the balance sheet.",
    significance:
      "A direct assets-vs-liabilities check: a P/B under 1 means the market is pricing the company below the value of what it owns after debts - historically a hallmark of deep-value investing.",
    volatilityImpact:
      "Book value itself is usually stable quarter to quarter, so P/B volatility mostly reflects the stock price moving, not the underlying business. A sudden asset write-down, though, can spike this ratio without any change in the stock price at all.",
  },
  {
    key: "graham_upside_pct",
    label: "Margin of Safety (vs. Fair-Value Estimate)",
    explanation:
      "The percentage gap between the fair-value estimate (combining EPS and book value) and the current price - this tool's definition of a margin of safety.",
    significance:
      "This tool's final valuation gate: even a wonderful, well-run business isn't a buy at any price. Positive means the price sits below the fair-value estimate; negative means it's trading above it.",
    volatilityImpact:
      "One of the most volatile numbers here since it's measured against the live stock price - it moves every trading day even when nothing about the company changed. A short-term price swing can flip the Investment Meter's valuation multiplier (1.0x to 0.55x) without a single thing being different about the business.",
  },
  {
    key: "graham_multiple",
    label: "P/E × P/B (Combined Multiple)",
    explanation:
      "Price-to-earnings multiplied by price-to-book - a combined ceiling test (kept at or below 22.5, roughly P/E ≤ 15 × P/B ≤ 1.5).",
    significance:
      "Catches a company that looks fine on one ratio but expensive on the other - e.g. a low-P/E stock actually trading at 5x book value. Multiplying the two forces both to be reasonable at once.",
    volatilityImpact:
      "Compounds the volatility of both inputs - since it's a product, a stock that's expensive on P/E and P/B at the same time moves faster here than on either ratio alone.",
  },
  {
    key: "ncav_margin_pct",
    label: "NCAV Margin (Net Current Asset Value)",
    explanation:
      "The strictest test here: (current assets − total liabilities) per share, compared against the stock price - do just the short-term assets alone, after paying off every liability, exceed what the whole company costs?",
    significance:
      "Almost always sharply negative for a normal, healthy large-cap - expected, since this test was designed for cheap small caps, not blue chips. A positive reading is rare and notable.",
    volatilityImpact:
      "Current assets (cash, receivables, inventory) turn over faster than the rest of the balance sheet, so this can move meaningfully quarter to quarter even for a stable business - a big inventory build or a receivables slowdown shows up here immediately.",
  },
  {
    key: "debt_to_equity",
    label: "Debt / Equity",
    explanation:
      "Total debt divided by shareholders' equity - how much of the company's financing comes from borrowing versus money shareholders have put in.",
    significance:
      "This tool's central leverage check (threshold: ≤1.0 to pass). Debt has to be repaid regardless of how business is going, so a highly levered company has far less room for error.",
    volatilityImpact:
      "Rising debt/equity means the same revenue shortfall hits equity harder, since interest and principal payments don't shrink when sales do. Crossing the 1.0 threshold flips the debt-discipline criterion from pass to fail, pulling that multiplier from 1.10x down to 0.75x.",
  },
  {
    key: "debt_to_ebitda",
    label: "Debt / EBITDA",
    explanation:
      "Total debt divided by EBITDA (earnings before interest, tax, depreciation, and amortization) - roughly, how many years of pre-cash-cost earnings it would take to pay off all debt.",
    significance:
      "A cash-flow-based leverage check, distinct from debt/equity's balance-sheet view - lower is safer.",
    volatilityImpact:
      "EBITDA reacts quickly to a revenue or margin shock, so this ratio can spike fast in a downturn even if debt itself hasn't changed - a company that looked safely levered in a good year can look overleveraged within a single bad one.",
  },
  {
    key: "current_ratio",
    label: "Current Ratio",
    explanation:
      "Current assets divided by current liabilities - can the company cover what it owes in the next year with what it can convert to cash in the next year?",
    significance:
      "The most basic short-term solvency check - used in this tool's defensive checklist (≥2.0, alongside a debt-vs-working-capital test). Below 1.0 means current liabilities exceed current assets outright.",
    volatilityImpact:
      "Working capital needs swing with the business cycle - inventory builds ahead of a busy season, or a slow collection period, can drag this down temporarily without signaling real distress. A persistent decline matters more than one quarter's dip.",
  },
  {
    key: "fcf_margin_pct",
    label: "FCF Margin (Free Cash Flow / Revenue)",
    explanation:
      "Free cash flow (operating cash flow minus capital expenditures) divided by revenue - what share of every sales dollar turns into cash the company actually gets to keep.",
    significance:
      "The tool's real cash-generation check, distinct from accounting profit, which can be flattered by non-cash items.",
    volatilityImpact:
      "Capital expenditure is lumpy - a single large plant or acquisition can push this negative for a quarter or year even in a fundamentally healthy, growing business, then rebound once the investment phase ends. Watch the trend, not one period.",
  },
  {
    key: "eps_growth_cagr_3yr_pct",
    label: "EPS Growth (3yr CAGR)",
    explanation: "The compound annual growth rate of diluted EPS over the most recent 3 years of annual statements.",
    significance:
      "This tool's growth check (≥ ~2.9%/yr average pace). A company whose earnings aren't growing struggles to compound shareholder wealth over time, even at a cheap price.",
    volatilityImpact:
      "A single unusually strong or weak base year can distort a 3-year CAGR significantly. Share buybacks also inflate EPS growth without any real increase in the underlying business - worth checking net income growth alongside this.",
  },
  {
    key: "margin_trend_score",
    label: "Margin Trend (declining / stable / improving)",
    explanation:
      "Classifies the company's gross margin trend over its most recent annual statements as declining, stable, or improving, scored 20 / 60 / 100 respectively.",
    significance:
      "Feeds the quality checklist directly (needs 'stable or improving' to pass) - eroding margins usually mean a weakening competitive position, exactly what that checklist is built to catch.",
    volatilityImpact:
      "Margins can move for reasons unrelated to competitive position - a one-off commodity input spike, a temporary promotion, a currency swing. A single 'declining' reading is worth less than a multi-year pattern, which is why this tool checks a 3-year window rather than one quarter.",
  },
  {
    key: "roe_pct",
    label: "ROE (Return on Equity)",
    explanation:
      "Net income divided by shareholders' equity - how much profit the company generates per dollar shareholders have actually invested in the business.",
    significance:
      "The central idea here, in basic arithmetic: a business that sustainably earns a high return on the capital it's given is worth far more than its statistical cheapness alone suggests. This tool's threshold is ≥15%.",
    volatilityImpact:
      "Can be inflated by leverage alone - a company that borrows heavily to shrink its equity base can show a high ROE without actually running the business better, which is exactly why this tool also separately checks debt/equity rather than trusting ROE in isolation.",
  },
  {
    key: "total_assets",
    label: "Total Assets",
    explanation: "Everything the company owns, per the latest balance sheet - cash, receivables, inventory, property, equipment, goodwill, and more.",
    significance:
      "One half of this whole tool's organizing question: does the company own more than it owes? The headline \"owns\" figure on every company page.",
    volatilityImpact:
      "Usually the most stable of all these numbers quarter to quarter for a mature company - it moves gradually with retained earnings and capital spending. A sudden large jump or drop (a big acquisition or write-down) is itself worth investigating.",
  },
  {
    key: "total_liabilities",
    label: "Total Liabilities",
    explanation: "Everything the company owes - debt, accounts payable, deferred taxes, pension obligations, and more, per the latest balance sheet.",
    significance:
      "The other half of the assets-vs-liabilities question. Combined with total assets, this determines shareholders' equity - the company's actual net worth.",
    volatilityImpact:
      "Tends to move more than total assets in the short term, since it includes operational items like accounts payable that shift with day-to-day business activity, not just long-term financing decisions.",
  },
  {
    key: "shareholders_equity",
    label: "Shareholders' Equity (net worth)",
    explanation: "Total assets minus total liabilities - what would be left over for shareholders if the company sold everything it owns and paid off everything it owes.",
    significance:
      "The company's actual net worth, and the denominator behind both ROE and debt/equity - the single number this whole tool is organized around explaining plainly.",
    volatilityImpact:
      "Grows steadily from retained profit, shrinks from dividends, buybacks, losses, or write-downs. A sudden drop despite a profitable year usually means a large buyback or a one-off impairment charge - worth checking which, since the two mean very different things.",
  },
  {
    key: "book_value_per_share",
    label: "Book Value per Share",
    explanation: "Shareholders' equity divided by shares outstanding - net worth on a per-share basis, directly comparable to the stock price.",
    significance:
      "Feeds both P/B and the fair-value estimate. Buying below book value per share means paying less than the accounting net worth of what you'd own.",
    volatilityImpact:
      "Share buybacks mechanically raise this per-share figure even if total equity doesn't grow, since fewer shares divide the same pie - so a rising book value per share can reflect capital return to shareholders just as much as the business getting bigger.",
  },
];

export function glossaryEntry(key) {
  return METRIC_GLOSSARY.find((m) => m.key === key);
}
