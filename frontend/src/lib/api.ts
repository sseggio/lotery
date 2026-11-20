/** Typed client for the backend API. */

export type GameKey = "lotto" | "euromillions";

export interface Pool { name: string; low: number; high: number; picks: number }
export interface GameInfo {
  key: GameKey; label: string; main: Pool; extra: Pool | null; has_bonus: boolean;
  price_eur: number; tiers: string[]; n_combinations: number; jackpot_probability: number;
}
export interface StrategyInfo { key: string; label: string; description: string; slot: number | null }

export interface Draw { draw_id: number; date: string; numbers: number[]; extras: number[] | null; bonus: number | null; verified: boolean | null }

export interface SyncInfo {
  last_attempt: { at: string; status: string; message: string; new_draws: number } | null;
  last_success_at: string | null;
  xlsx_check: { at: string; status: string; message: string } | null;
}

export interface FreqRow {
  number: number; count: number; expected: number; z: number; pct: number; count_30: number; count_60: number;
  count_90: number; gap: number; mean_gap: number | null; max_gap: number; regularity_cv: number | null;
  ewma: number; last_date: string | null; rolling30_max: number | null; rolling30_min: number | null;
}

export interface ChiSquare { statistic: number; df: number; p_value: number }

export interface Summary {
  game: GameKey; total_draws: number; last_draw: Draw | null; sync: SyncInfo;
  year_draws?: number; year_from?: string; most_frequent?: FreqRow[]; least_frequent?: FreqRow[]; overdue?: FreqRow[];
  recent_draws?: { date: string; numbers: number[]; extras: number[] | null; bonus: number | null }[];
  chi_square?: ChiSquare; sum_mean?: number; sum_mean_theoretical?: number; odd_mean?: number;
  verified_draws?: number; mismatched_draws?: number; history_draws?: number; history_from?: string;
}

export interface GridDetails {
  strategy_label: string; strategy_description: string; alpha: number;
  scores: Record<string, number>;
  numbers: { number: number; count: number; freq_rank: number; recent_rank: number; gap: number; popularity: number | null }[];
  structure: { sum: number; odd: number; even: number; low: number; high: number; decades: Record<string, number>; max_run: number; le31: number };
  popularity: { relative_popularity: number; anti_score: number; expected_jackpot_share: number; average_jackpot_share: number; gain_vs_average_pct: number; patterns: string[] };
  reasons: string[];
}
export interface Grid {
  id: number; slot: number; strategy: string; numbers: number[]; extras: number[] | null; stat_score: number;
  anti_score: number; global_score: number; details: GridDetails; favorite: boolean; created_at: string;
}
export interface Generation {
  id: number; game: GameKey; created_at: string; balance: number; last_draw_id: number; last_draw_date: string | null;
  n_draws_used: number; grids: Grid[];
}

export interface Tuple { numbers: number[]; count: number; expected: number; expected_max_by_chance: number }
export interface DistRow { value: number; observed: number; observed_pct: number; theoretical_pct: number }
export interface Stats {
  window: string; n_draws: number; from: string; to: string; frequencies: FreqRow[]; chi_square: ChiSquare;
  evolution: { span: number; dates: string[]; series: Record<string, number[]>; expected: number };
  heatmap: { months: string[]; draws: number[]; matrix: number[][] };
  pairs: Tuple[]; triplets: Tuple[];
  distributions: {
    odd_even: DistRow[]; low_high: DistRow[]; low_threshold: number;
    sum_histogram: { from: number; to: number; observed_pct: number; theoretical_pct: number }[];
    sum_mean_observed: number; sum_mean_theoretical: number; sum_central_80: [number, number];
    decades: { label: string; observed: number; expected: number }[];
    consecutive_pct_observed: number; consecutive_pct_theoretical: number; max_run_observed: number;
  };
  recurring: { exact_repeats: { numbers: number[]; count: number }[]; carry_over: { shared: number; observed_pct: number; theoretical_pct: number }[] };
  extra_frequencies?: FreqRow[]; extra_chi_square?: ChiSquare;
}

export interface BacktestRow {
  strategy: string; label: string; mean_hits: number; ci95: [number, number]; delta_vs_theory_pct: number; z: number;
  p_value: number; p_value_vs_random: number | null; significant: boolean; significant_bonferroni: boolean;
  mean_extra_hits: number | null; distribution: { hits: number; count: number; pct: number; theoretical_pct: number }[];
  at_least_3_pct: number; tiers: Record<string, number>; won_eur: number; cost_eur: number; return_pct: number;
  mean_anti_score: number; mean_expected_jackpot_share: number; cumulative_mean: number[];
}
export interface Backtest {
  game: GameKey; n_test_draws: number; grids_per_draw: number; n_grids_per_strategy: number; balance: number;
  first_test_date: string; last_test_date: string; test_dates: string[]; theoretical_mean_hits: number;
  theoretical_distribution: number[]; results: BacktestRow[]; duration_s: number; method: string; computed_at: string;
}

export interface PopularityInfo {
  diagnostics: { n_draws_used: number; estimated: boolean; oos_r2?: number; oos_corr?: number; ratio_spread?: number[]; beta_all_le31?: number; beta_consecutive?: number; international_factor?: number; boards_typical?: number };
  numbers: { number: number; multiplier: number }[];
  extras: { number: number; multiplier: number }[] | null;
  priors: { key: string; label: string; log_lift: number }[];
  share_curve: { relative_popularity: number; expected_share: number }[];
  examples: ({ numbers: number[]; extras: number[] | null } & GridDetails["popularity"])[];
  boards_typical: number; n_combinations: number;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  } catch {
    throw new ApiError("Serveur injoignable. Vérifiez votre connexion.", 0);
  }
  if (!res.ok) {
    let msg = `Erreur ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
      else if (Array.isArray(body.detail)) msg = "Paramètres invalides";
    } catch { /* not JSON */ }
    throw new ApiError(msg, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  games: () => request<{ games: GameInfo[]; strategies: StrategyInfo[] }>("/api/games"),
  summary: (g: GameKey) => request<Summary>(`/api/${g}/summary`),
  stats: (g: GameKey, window: string) => request<Stats>(`/api/${g}/stats?window=${encodeURIComponent(window)}`),
  draws: (g: GameKey, limit: number, offset: number) =>
    request<{ total: number; draws: Draw[] }>(`/api/${g}/draws?limit=${limit}&offset=${offset}`),
  sync: (g: GameKey) => request<{ status: string; new_draws: number; message: string; sync: SyncInfo }>(`/api/${g}/sync`, { method: "POST" }),
  latest: (g: GameKey) => request<Generation | null>(`/api/${g}/generations/latest`),
  generations: (g: GameKey, limit = 20, offset = 0) => request<Generation[]>(`/api/${g}/generations?limit=${limit}&offset=${offset}`),
  generate: (g: GameKey, balance: number) =>
    request<Generation>(`/api/${g}/generate`, { method: "POST", body: JSON.stringify({ balance }) }),
  regenerate: (g: GameKey, generationId: number, slot: number, balance: number) =>
    request<Generation>(`/api/${g}/generate`, { method: "POST", body: JSON.stringify({ balance, generation_id: generationId, slot }) }),
  favorite: (id: number, favorite: boolean) =>
    request<{ id: number; favorite: boolean }>(`/api/grids/${id}/favorite`, { method: "POST", body: JSON.stringify({ favorite }) }),
  favorites: (g: GameKey) => request<Grid[]>(`/api/${g}/favorites`),
  backtest: (g: GameKey, n: number, perDraw: number, balance: number) =>
    request<Backtest>(`/api/${g}/backtest?n_draws=${n}&grids_per_draw=${perDraw}&balance=${balance}`),
  popularity: (g: GameKey) => request<PopularityInfo>(`/api/${g}/popularity`),
  score: (g: GameKey, numbers: number[], extras: number[] | null, balance: number) =>
    request<Omit<Grid, "id" | "slot" | "favorite" | "created_at">>(`/api/${g}/score`, {
      method: "POST", body: JSON.stringify({ numbers, extras, balance }),
    }),
};
