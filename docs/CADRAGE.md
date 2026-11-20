# Project scoping — Smart grid generator, Belgian National Lottery

> Reference document: rules, architecture, data sources, statistical methods,
> evaluation, UX. The figures cited come from real runs on official data
> (sync of 20/11/2026).

---

## 1. Games covered and official rules

The Loterie Nationale operates 9 draw games (seen on its API: Lotto, Extra Lotto,
EuroMillions, EuroDreams, Viking Lotto, Joker+, Keno, Pick3, Flash 5). Version 1 covers
the two games where grid choice and jackpot sharing matter most:

| | **Lotto** | **EuroMillions** |
|---|---|---|
| Player choice | 6 distinct numbers out of 45 | 5 numbers out of 50 + 2 stars out of 12 |
| Draw | 6 numbers + **1 bonus number** drawn from the **same drum** | 5 numbers + 2 stars |
| Bonus | not chosen by the player; it upgrades certain ranks | — |
| Ranks | 6, 5+1, 5, 4+1, 4, 3+1, 3, 2+1, 1+1 | 13 ranks, from 5+2 to 2+0 |
| Draws | Wednesday and Saturday evening | Tuesday and Friday evening (9 countries) |
| Board price | €1.50 | €2.50 |
| Combinations | 8,145,060 | 139,838,160 |

These rules are encoded in `backend/app/games.py`. At every sync they are checked against the
`gameRuleSet` returned by the official API: if the range changes (e.g. 45 → 49), the draw is
**rejected** rather than stored inconsistently. The exact probabilities of each rank are computed
(hypergeometric law) and tested (`P(6) = 1/8,145,060`, `P(5+1) = 6/8,145,060`).

Add-on games (Joker+, Lucky Lotto, My Bonus) are ignored.

## 2. Data sources

**No public API is documented.** Two official sources were identified and verified:

1. **Results API used by the official site**
   `https://apim.prd.natlot.be/api/v4/draw-games/draws?status=PAYABLE&game-names=Lotto&date-from=…&date-to=…`
   - final results (`PAYABLE`), numbers, bonus/stars;
   - **number of Belgian winners and amount per rank**, plus all-country winners for EuroMillions;
   - sales of each draw (available since mid-2022);
   - history available at least since 2012.
2. **Official statistics file** (xlsx, updated monthly) at
   `loterie-nationale.be/nos-jeux/lotto/resultats-tirage/statistiques`, "Résultats" sheet: every draw since 1978.

**Reliability strategy**
- The API is the primary source (real time, ranks and winners).
- Every Lotto draw is **cross-checked** against the xlsx file. Result: **1,131 draws confirmed, 0 discrepancies**.
  The most recent draws remain "API only" until the next monthly publication.
- The raw JSON of each response is kept (`draws.raw`) for audit. Derived data can be rebuilt
  without a new network call (`repair_tiers_from_raw`).
- **Nothing is ever invented.** A draw that does not follow the rules (count, range, duplicates,
  bonus among the numbers, non-final status) is rejected and logged.

**Synchronisation**
- Initial backfill from `HISTORY_START_YEAR` (2016 by default, about 1,100 draws per game).
- Then incremental sync from the last known draw, with a 2-day safety margin.
  Duplicates are impossible thanks to the `(game, draw_id)` primary key.
- Automatic schedule: about 1 h and 3 h after each draw, plus a daily catch-up.
- "Actualiser les tirages" button, limited to one call per minute so the official server is not hammered.
- Every attempt is logged (`sync_log`). Errors (source unavailable, HTTP code, invalid JSON) are shown
  in the UI without deleting existing data.

## 3. Technical architecture

```
                ┌──────────────────────── Docker container (non-root, read-only) ──────────────┐
 loterie-       │  ingest/            engine/                      services.py      main.py     │
 nationale.be ──┼─► natlot.py   ─►  data.py  stats.py           (use cases,  ─►  FastAPI /api ─┼─► React SPA
 (API + xlsx)   │   xlsx_verify      strategies.py popularity.py   engine cache)    + static     │   (Vite, Tailwind,
                │   sync.py          generator.py  backtest.py                                    │    Recharts)
                │        │                                                                       │
                │        └──────► db.py (SQLite, /data volume) ◄──────────────────────────────── │
                └──────────────────────────────────────────────────────────────────────────────┘
```

- **Backend**: Python 3.12, FastAPI, NumPy/SciPy (vectorised computation: tens of thousands of
  combinations are scored in a few milliseconds), SQLite (a single file, enough for a few thousand
  draws, backed up by copying the volume), APScheduler.
- **Frontend**: React 18 + TypeScript, Tailwind (light/dark tokens), Recharts, React Router.
- **Strict separation**: retrieval (`ingest/`) → storage (`db.py`) → statistics engine
  (`engine/`, pure functions with no I/O, unit-tested) → use cases (`services.py`) → HTTP (`main.py`).
- **Deployment**: a single image (multi-stage build), `docker compose up -d`, port bound to
  `127.0.0.1` behind a reverse proxy with HTTPS. Optional Basic auth.

## 4. Statistical methods

> **Founding principle.** The draws are independent and (as far as one can test) uniform. No
> method can make one combination more likely than another. The engine therefore separates two
> objectives:
> - **A. Describing the past** (score "statistique"): agreement with historical trends.
> - **B. Increasing the expected gain _if you win_** (score "anti-partage"), by avoiding
>   combinations that other players play a lot. This is the only lever that changes the expected value.

Each statistic is shown **next to its theoretical value under perfect randomness**.

| Method | Implementation | Value | Limits | Role in generation |
|---|---|---|---|---|
| Weighted frequency analysis | counts over 104 draws, z-score vs binomial, Bayesian smoothing | faithful description; would detect a biased machine over a very long period | on 100 draws the gaps are of the same order as the noise (χ² test) | Grid 1 |
| Moving average / weighting of recent draws | exponential moving average, half-life of 12 draws | visualises short-term "trends" | the balls have no memory: a trend does not continue | Grid 2 |
| Temporal analysis | current gap, mean gap, max gap, regularity (CV of gaps), rolling-30 frequency (high and low periods) | describes the history | "a number is due" = gambler's fallacy: the probability stays 6/45 | **control** strategy in the backtest |
| Combinations | pairs/triplets observed vs expected **and vs the maximum expected by chance** (Poisson approximation), parity, small/large, sum, tens, consecutive numbers, repeats | spots anomalies | multiple comparisons: with 990 pairs, some come out often by chance | "paires" component of the combined indicator |
| Probabilistic models | hypergeometric law, χ² uniformity test, exact probabilities per rank | gives the **exact** reference (0.8 correct numbers per grid at Lotto) | confirms that every combination is equal | reference for every comparison |
| Monte-Carlo simulation | 4,000 candidates per grid (Gumbel top-k sampling with no duplicates), 20,000 random grids as the reference for percentiles | explores the space while respecting the constraints | optimises scores, not the probability | generation engine |
| Correlations between numbers | standardised co-occurrence matrix | detects associations | noise dominates | combined indicator |
| **Popularity model** | see § 4.1 | the only dimension that can change the expected value | indirect estimate | anti-sharing score |

### 4.1 Popularity model (objective B)

**Data used.** For every draw since mid-2022 (458 draws), the API gives the number of Belgian
winners at ranks 3 and 4 (thousands per draw) and the sales. Under uniform play, the expected
number of winners = boards × P(rank). The ratio *observed / expected* varies from **×0.80 to ×1.24**
(5th–95th percentile) depending on the numbers drawn. For example, the draw 5-32-39-41-44-45 had
×0.75, while 3-8-11-20-23-31 had ×1.37. This is direct evidence of number popularity.

**Model.** A weighted ridge regression of `log(observed/expected)` on the numbers drawn, with
causal correction of the level drift (median of the previous 20 draws). The coefficients are
rescaled by k/m because a rank-m winner shares only m of the k numbers.

**Measured quality, out of sample** (fitted on the first 80% of draws, tested on the last 20%):
- **R² = 0.76 for Lotto** (correlation 0.90);
- **R² = 0.81 for EuroMillions** (correlation 0.93).

**Findings.**
- **Lotto**: 7 is the most played number (×1.23), followed by 8, 9, 3, 17, 13. The least played are
  45, 43, 44, 36, 35 (×0.84–0.87).
- **EuroMillions**: 7, 23, 19, 13, 17 are overplayed; 46, 47, 41 are underplayed. The stars show
  almost no preference.
- The **birthday** bias (numbers ≤ 31) is clearly visible in the per-number coefficients.

**A priori part.** Some patterns are never drawn and therefore cannot be estimated: sequences,
arithmetic progressions, alignments on the slip, same units digit, multiples of 5, replay of the
last draw. Their weights are conservative orders of magnitude taken from published studies of
player choices (for example, thousands of players for 1-2-3-4-5-6 in the large lotteries). They are
capped at ×5,000 and **shown as hypotheses** in the UI.

**Expected jackpot share.** The number of other winners is modelled as K ~ Poisson(λ), with
λ = boards × relative popularity / number of combinations. The expected share is then
E[1/(1+K)] = (1 − e^{−λ})/λ. For EuroMillions, Belgian volumes are scaled up to European volumes
using the ratio of all-country winners to Belgian winners on the low ranks.

**Limits.**
- The operator does not publish the grids played. The model infers popularity from the winners,
  which is only an indirect proxy.
- Quick picks (random grids) dilute every preference.
- The patterns are weighted by literature priors, not by Belgian data.
- **The probability of winning is unchanged.** Only the expected amount *if you win* changes.

### 4.2 Generating the 4 grids

| Grid | Strategy | Statistical weight α (balanced setting) |
|---|---|---|
| 1 | Historical frequencies | 0.9 |
| 2 | Recent trends | 0.9 |
| 3 | Hybrid (frequency + trend + pairs) **+ anti-sharing** | 0.5 |
| 4 | Anti-sharing first | 0.1 |

Each grid is generated in four steps:

1. Draw Monte-Carlo candidates.
2. Compute each candidate's objective as α·statistical percentile + (1−α)·anti-sharing score − 6 × the number of numbers shared with the grids already chosen.
3. Reject any candidate sharing more than **2 numbers** with another grid.
4. Draw the final grid at random from the top 1% (soft-max). Regenerating therefore gives a different grid of the same quality.

The user setting (Statistiques / Équilibre / Anti-partage, or a 0–100% slider) shifts every α by
±0.4 and recomputes the 4 grids. Each grid shows three scores: **statistique** (combined
indicator, percentile against random grids), **anti-partage** (share of random grids judged more
popular) and **global** (weighted by the setting). It also shows the detailed criteria: ranks and
gaps of each number, popularity, structure, patterns detected, overlap with the other grids.

## 5. Evaluating the algorithms (backtest)

**Walk-forward protocol with no leakage.**
1. For each test draw *t*, the engine is **rebuilt** from `History.before(t)`, i.e. only the strictly
   earlier draws. An assertion checks that the last date used is before *t*.
2. The popularity model is refitted every 10 draws on that truncated history.
3. A unit test modifies **future** draws and checks that the grids generated for earlier dates do not change.

**Metrics.**
- Mean number of correct numbers vs the theoretical expectation (Lotto 0.8, EuroMillions 0.5) and vs the random strategy.
- 95% confidence interval and p-value. The G grids of one draw are correlated, so inference uses the
  per-draw means (cluster-robust standard error) plus a paired test against random.
- Bonferroni correction for the comparisons.
- Distribution of correct numbers vs the hypergeometric law, ranks reached.
- **Real return** computed with the official amounts per rank of each draw.
- Mean anti-sharing score and expected jackpot share.

**Results (200 Lotto draws, Dec 2024 → Nov 2026, 2,000 grids per strategy):**

| Strategy | Correct numbers / grid | p vs theory | Expected jackpot share |
|---|---|---|---|
| Uniform random | 0.800 | 0.98 | 83.8% |
| Frequencies | 0.828 | 0.44 | 88.6% |
| Trends | 0.810 | 0.77 | 88.3% |
| Hybrid | 0.842 | 0.21 | 89.4% |
| Anti-sharing | 0.841 | 0.23 | **90.2%** |
| Overdue numbers (control) | 0.742 | 0.14 | 83.4% |

**Conclusion.** No strategy does significantly better than chance on the number of correct numbers,
as theory predicts. The gaps are the same size as the confidence intervals. On the other hand, the
anti-sharing strategy increases the share of the jackpot kept if you win (+7.6% relative to random
at Lotto, according to the model). This is the only measurable lever, and it remains an estimate.

> A methodological note learned during development: a naive test that treats the grids of one draw as
> independent produced "significant" p-values (0.006). They disappear with the correct inference.
> This is exactly the kind of trap the tool aims to avoid.

## 6. Pages and art direction

| Page | Content |
|---|---|
| **Dashboard** `/` | last official draw (with "verified ×2" badge), sync, analysed draws, χ² test; **the 4 grids** with "Générer 4 nouvelles grilles", per-grid regeneration, favourites, copy, priority setting; most/least frequent numbers, absent numbers, recent draws |
| **Statistiques** `/statistiques` | windows Année / 30 / 60 / 90 / Tout; frequency histogram (or gap / weighted) with expected value; rolling-30 evolution curves; monthly heatmap; sortable table; pairs/triplets vs the chance maximum; parity, small/large, sums, tens, consecutive numbers, repeats; stars |
| **Algorithmes** `/algorithmes` | configurable backtest (50–300 draws, 5–20 grids); CI chart, cumulative means, detailed table; method sheets (value / limits / contribution); anti-sharing model: diagnostics, per-number popularity, examples, hypotheses, "Analyser ma grille" |
| **Historique** `/historique` | favourites and all saved generations |
| **Tirages** `/tirages` | official list, source and per-draw verification status |

**Art direction.** A modern SaaS dashboard (in the spirit of Linear or Vercel):
- Inter typeface, neutral palette with an indigo accent, light and dark themes driven by tokens;
- cards with 16 px radius, tabular figures, discreet and fast animations (< 300 ms, disabled with `prefers-reduced-motion`);
- numbers shown as balls, stars in amber, bonus with a dashed outline;
- desktop sidebar, mobile bottom bar, 44 px touch targets.

There is deliberately no "lottery" iconography: the tool presents itself as data analysis, with the
honesty messages built into the UI.

## 7. Quality

- 37 tests (`backend/tests`):
  - official rules and exact probabilities;
  - parser (valid draws, rejected cases, the API's padded `drawType`);
  - no duplicates on sync;
  - sync behaviour when the source is down;
  - throttling;
  - rule compliance of 180 generated batches (count, range, no duplicates, extras, 4 different grids, overlap ≤ 2);
  - single-slot regeneration;
  - popularity model (planted preferences recovered);
  - **no look-ahead** in the backtest;
  - API: validation, security headers, Basic auth.
- Security:
  - parameterised SQL;
  - bounded parameters;
  - outbound URLs built from constants;
  - responses and xlsx files size-limited (zip-bomb guard);
  - CSP and security headers;
  - generic errors returned to the client;
  - non-root, read-only container.
- Review agents (`.claude/agents/`): `security-auditor` and `ui-challenger`.
