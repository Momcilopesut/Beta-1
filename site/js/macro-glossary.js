// Every macro series this tool tracks, in one place: what it is, why it
// matters economically, and how swings in it actually affect the broader
// economy - not just the number. Mirrors site/js/metrics-glossary.js's
// pattern for the per-company metrics, written once so site/js/macro.js
// never has to duplicate this content.
//
// Keys match each series entry's "series_id" in data/macro.json (the same
// FRED series IDs configured in config/macro_series.yaml).

export const MACRO_GLOSSARY = [
  {
    key: "DGS1MO",
    label: "1-Month Treasury Yield",
    explanation:
      "The interest rate the U.S. Treasury pays on debt maturing in one month - about as close to a \"risk-free overnight rate\" as a market-priced yield gets.",
    significance:
      "Tracks Federal Reserve policy almost in real time, since money-market funds and short-term borrowing costs move with it directly.",
    volatilityImpact:
      "Swings almost entirely with Fed policy expectations rather than economic surprises - a rate decision or a shift in forward guidance can move it within days, well before anything shows up elsewhere in the economy.",
  },
  {
    key: "DGS3MO",
    label: "3-Month Treasury Yield",
    explanation:
      "Yield on 3-month Treasury bills - the classic \"risk-free rate\" used across finance as a baseline in nearly every discounting and hurdle-rate calculation.",
    significance:
      "What it costs the U.S. government to borrow for 90 days, and the anchor most other short-term rates (savings accounts, CDs, commercial paper) are priced off of.",
    volatilityImpact:
      "Moves mainly with Fed policy expectations like the 1-month yield; a sudden spike here relative to the Fed funds rate can also flag stress in short-term funding markets.",
  },
  {
    key: "DGS2",
    label: "2-Year Treasury Yield",
    explanation:
      "Yield on the 2-year Treasury note - the market's best real-time read on where investors expect the Fed funds rate to average over the next two years.",
    significance:
      "A cleaner gauge of \"where markets think policy is headed\" than any single Fed statement - a sharp drop here means markets are pricing in rate cuts, regardless of what officials are currently saying.",
    volatilityImpact:
      "Reprices quickly on economic data surprises (jobs reports, inflation prints) since each one shifts the expected Fed path - one of the more reactive points on the whole yield curve.",
  },
  {
    key: "DGS10",
    label: "10-Year Treasury Yield",
    explanation:
      "Yield on the 10-year Treasury note - the single most widely watched interest rate in the world, and the benchmark most mortgage rates and corporate borrowing costs are priced against.",
    significance:
      "Reflects long-run growth and inflation expectations, not just near-term Fed policy - a rising 10-year makes mortgages, auto loans, and corporate debt more expensive across the entire economy.",
    volatilityImpact:
      "A sustained move of even half a percentage point ripples into mortgage rates and corporate financing costs within weeks, slowing - or accelerating - housing activity and business investment.",
  },
  {
    key: "DGS30",
    label: "30-Year Treasury Yield",
    explanation: "Yield on the 30-year Treasury bond - the longest-dated, most inflation-sensitive point on the yield curve.",
    significance:
      "Long-horizon investors like pension funds and insurers use it to price decades-long liabilities; it also serves as a barometer of long-run inflation and fiscal-sustainability concerns.",
    volatilityImpact:
      "Least reactive to short-term Fed moves but most reactive to a genuine shift in long-run inflation expectations or concerns about government debt sustainability.",
  },
  {
    key: "T10Y2Y",
    label: "10Y-2Y Treasury Spread",
    explanation: "The 10-year Treasury yield minus the 2-year - a measure of how steep, flat, or inverted the yield curve currently is.",
    significance:
      "One of the most reliable recession-warning signals in modern economic history - when short-term yields exceed long-term yields (a negative spread), it has preceded every U.S. recession since the 1970s, though the lag before a downturn has varied from months to over a year.",
    volatilityImpact:
      "This tool treats a move from positive to negative - an inversion - as a structural warning sign on its own, overriding the ordinary \"how much did it move\" reading, since the historical signal comes from the sign flipping, not the size of the move.",
  },
  {
    key: "CPIAUCSL",
    label: "CPI (All Urban Consumers)",
    explanation:
      "The Consumer Price Index for All Urban Consumers - the government's headline measure of what a typical household's basket of goods and services costs, updated monthly.",
    significance:
      "The most widely cited inflation gauge - cost-of-living adjustments, wage negotiations, and most of the public conversation about \"inflation\" reference this number directly.",
    volatilityImpact:
      "Food and energy prices can swing it sharply month to month for reasons that have nothing to do with the broader economy - a war, a bad harvest, a hurricane - which is part of why the Fed leans more on PCEPI for actual policy decisions.",
  },
  {
    key: "PCEPI",
    label: "PCE Price Index (Fed's preferred inflation gauge)",
    explanation: "The Personal Consumption Expenditures Price Index - a broader, differently-weighted measure of consumer prices than CPI.",
    significance:
      "The Federal Reserve's explicitly stated preferred inflation gauge, and the basis for its 2% target - when the Fed talks about hitting \"2% inflation,\" this is the number it means, not CPI.",
    volatilityImpact:
      "Generally smoother than CPI, since its methodology adjusts for consumers substituting cheaper goods when prices rise - a sustained move here carries more weight with policymakers than an equivalent CPI move.",
  },
  {
    key: "UNRATE",
    label: "Unemployment Rate",
    explanation: "The share of the labor force that is unemployed and actively looking for work.",
    significance:
      "One half of the Fed's dual mandate alongside inflation - a rising unemployment rate is the clearest sign the economy is weakening, and historically the trigger for rate cuts.",
    volatilityImpact:
      "A rise of even half a percentage point over a few months has historically been a strong recession signal (the basis of the well-known \"Sahm Rule\") - unemployment tends to rise sharply once it starts rising at all, rather than drifting up gradually.",
  },
  {
    key: "FEDFUNDS",
    label: "Effective Federal Funds Rate",
    explanation:
      "The interest rate banks charge each other for overnight loans - the Federal Reserve's primary lever for tightening or loosening financial conditions across the entire economy.",
    significance:
      "Every other interest rate in the economy - mortgages, credit cards, business loans - is priced with this rate as a starting reference point.",
    volatilityImpact:
      "Doesn't move on its own between scheduled Fed meetings, but the pace of change matters: a series of large hikes or cuts in a short window signals how urgently the Fed sees a problem, not just a routine policy adjustment.",
  },
  {
    key: "PAYEMS",
    label: "Nonfarm Payrolls",
    explanation:
      "The total number of paid U.S. workers outside of farms, private households, and a few other categories, released monthly and among the most closely watched data releases of any kind.",
    significance:
      "The most direct, real-time read on whether the economy is creating or shedding jobs - a single strong or weak jobs report routinely moves stock and bond markets within minutes of release.",
    volatilityImpact:
      "Subject to significant revisions in the months after its initial release, so a single month's figure - especially right around a turning point - can be a noisier signal than the multi-month trend.",
  },
  {
    key: "ICSA",
    label: "Initial Jobless Claims",
    explanation:
      "The number of new unemployment insurance claims filed each week - one of the freshest, most frequently updated labor-market indicators available.",
    significance:
      "A genuine leading indicator - claims tend to start rising before the unemployment rate itself does, since layoffs happen before workers show up in unemployment statistics.",
    volatilityImpact:
      "Noisy week to week (holidays, weather, one-off layoff announcements all cause blips), so a single week's jump matters far less than a sustained multi-week uptrend.",
  },
  {
    key: "INDPRO",
    label: "Industrial Production Index",
    explanation: "A measure of real output from U.S. factories, mines, and utilities.",
    significance:
      "A direct read on the goods-producing side of the economy, historically more cyclical and more sensitive to interest rates than the services sector.",
    volatilityImpact:
      "Reacts faster to a slowdown than most consumer-facing data - manufacturers cut production quickly when orders soften, often well before that shows up in broader GDP figures.",
  },
  {
    key: "UMCSENT",
    label: "Consumer Sentiment (U. of Michigan)",
    explanation: "A monthly survey asking households how they feel about their own finances and the broader economy.",
    significance:
      "Consumer spending drives roughly two-thirds of U.S. GDP, so how confident households feel about spending it matters almost as much as the hard economic data.",
    volatilityImpact:
      "Reacts fast, and sometimes overreacts, to headlines like gas prices, political news, or market swings - a sharp one-month move is often partly reversed the following month, so a sustained trend matters more than any single reading.",
  },
  {
    key: "M2SL",
    label: "M2 Money Supply",
    explanation:
      "Cash, checking deposits, savings accounts, and money-market funds combined - a broad measure of the money circulating in, or readily available to, the economy.",
    significance:
      "Historically linked to inflation over long horizons, since more money chasing the same goods can push prices up - though the strength of that relationship has proven far looser and more debated in recent decades than simple textbook versions suggest.",
    volatilityImpact:
      "An unusually sharp expansion (like the 2020-21 pandemic stimulus period) or an outright contraction (like 2022-23) are both historically rare and have each preceded notable shifts in inflation or financial conditions - which is why this tool flags either direction as notable, rather than assuming \"more money\" is simply good news.",
  },
  {
    key: "GDPC1",
    label: "Real GDP",
    explanation: "The total value of everything the U.S. economy produces, adjusted for inflation, released quarterly.",
    significance:
      "The single broadest scorecard of economic growth that exists - two consecutive quarters of decline is the informal rule-of-thumb definition of a recession, though the official call rests with the NBER on a broader set of indicators.",
    volatilityImpact:
      "Released with a lag and subject to substantial revision as more complete data comes in - the first (\"advance\") estimate for a quarter can differ meaningfully from the final, revised figure released months later.",
  },
];

export function macroGlossaryEntry(key) {
  return MACRO_GLOSSARY.find((m) => m.key === key);
}
