import { CheckCircle2, FlaskConical, Scale, ShieldCheck } from "lucide-react";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, ErrorBar, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { axisProps, useChartColors } from "../components/charts";
import { Balls, Card, cx, ErrorState, Notice, ScoreBar, SectionTitle, Segmented, Skeleton } from "../components/ui";
import { api, Backtest, GameInfo, PopularityInfo } from "../lib/api";
import { useApp } from "../lib/app-context";
import { fmtDate, fmtInt, fmtNum, fmtP, fmtPct, fmtShort } from "../lib/format";
import { useAsync } from "../lib/hooks";

const METHODS = [
  { name: "Analyse fréquentielle (pondérée)", what: "Compte les sorties de chaque numéro sur ~1 an et les compare à l'attendu (z-score).",
    pro: "Décrit fidèlement le passé ; détecterait une machine biaisée sur un très grand nombre de tirages.",
    con: "Sur 100 tirages, les écarts observés sont du même ordre que le bruit aléatoire (test du χ²).",
    use: "Grille 1 : oriente le choix vers les numéros sortis plus souvent." },
  { name: "Moyenne mobile & pondération des tirages récents", what: "Moyenne mobile exponentielle (demi-vie 12 tirages) : les tirages récents pèsent davantage.",
    pro: "Capte des « tendances » de court terme, visualisables dans les graphiques d'évolution.",
    con: "Sans mémoire physique dans les boules, une tendance passée ne se prolonge pas.",
    use: "Grille 2 : tendances récentes." },
  { name: "Analyse temporelle (retards)", what: "Nombre de tirages depuis la dernière apparition, écart moyen, régularité.",
    pro: "Utile pour décrire l'historique.", con: "Croire qu'un numéro « doit » sortir est l'erreur du joueur : la probabilité reste 6/45 à chaque tirage.",
    use: "Stratégie témoin « Numéros en retard » dans le backtest uniquement." },
  { name: "Corrélations entre numéros (paires, triplets)", what: "Co-occurrences comparées à l'attendu et au maximum attendu par hasard.",
    pro: "Repère d'éventuelles associations anormales.", con: "Avec 990 paires possibles, certaines sortent souvent par simple hasard (comparaisons multiples).",
    use: "Composante « paires » de l'indicateur combiné (grille 3)." },
  { name: "Modèles probabilistes", what: "Loi hypergéométrique (nombre de bons numéros), lissage bayésien des fréquences, test du χ².",
    pro: "Donne la référence exacte : 0,8 bon numéro en moyenne par grille au Lotto, quelle que soit la stratégie.",
    con: "Confirme qu'aucune combinaison n'est plus probable qu'une autre.", use: "Sert de base de comparaison à toutes les stratégies." },
  { name: "Simulation Monte-Carlo", what: "Des milliers de grilles candidates sont tirées puis notées ; des grilles aléatoires servent de référence pour les percentiles.",
    pro: "Explore efficacement l'espace des combinaisons et respecte toutes les contraintes (diversité, règles).",
    con: "Optimise des scores, pas la probabilité de gain.", use: "Moteur de génération des 4 grilles." },
  { name: "Modèle de popularité (anti-partage)", what: "Estime à quel point une combinaison est jouée, à partir du nombre réel de gagnants belges par rang.",
    pro: "Seule dimension où un choix peut changer l'espérance de gain : moins de co-gagnants = part plus grosse.",
    con: "Estimation indirecte : la Loterie ne publie pas les grilles jouées. Ne change pas la probabilité de gagner.",
    use: "Score anti-partage de toutes les grilles ; grilles 3 et 4." },
];

function BacktestSection({ game, info }: { game: string; info?: GameInfo }) {
  const c = useChartColors();
  const { balance } = useApp();
  const [n, setN] = useState("100");
  const [per, setPer] = useState("10");
  const bt = useAsync<Backtest>(() => api.backtest(game as "lotto", Number(n), Number(per), Math.round(balance * 4) / 4), [game, n, per, balance]);
  const d = bt.data;
  const others = d?.results.filter((r) => r.strategy !== "aleatoire") ?? [];
  const anySig = others.some((r) => r.significant_bonferroni);
  const random = d?.results.find((r) => r.strategy === "aleatoire");

  const chartData = d?.results.map((r) => ({ name: r.label.replace(/ \(.*\)/, ""), key: r.strategy, mean: r.mean_hits, err: [r.mean_hits - r.ci95[0], r.ci95[1] - r.mean_hits] }));
  const cum = d ? d.test_dates.map((date, i) => {
    const row: Record<string, number | string> = { date };
    d.results.forEach((r) => { row[r.strategy] = r.cumulative_mean[i]; });
    return row;
  }) : [];

  return (
    <section aria-labelledby="bt-title" className="space-y-4">
      <SectionTitle id="bt-title" title="Backtesting des stratégies"
        subtitle="Chaque stratégie est rejouée dans le passé : pour chaque tirage, seuls les tirages antérieurs sont utilisés."
        action={
          <div className="flex flex-wrap gap-2">
            <Segmented size="sm" label="Nombre de tirages testés" value={n} onChange={setN}
              options={[{ value: "50", label: "50 tirages" }, { value: "100", label: "100" }, { value: "200", label: "200" }, { value: "300", label: "300" }]} />
            <Segmented size="sm" label="Grilles par tirage" value={per} onChange={setPer}
              options={[{ value: "5", label: "5 grilles" }, { value: "10", label: "10" }, { value: "20", label: "20" }]} />
          </div>
        } />
      {bt.error && <ErrorState message={bt.error} onRetry={bt.reload} />}
      {bt.loading && (
        <Card className="p-6">
          <div className="flex items-center gap-3 text-sm text-muted"><FlaskConical className="h-4 w-4 animate-pulse" aria-hidden />Simulation en cours (jusqu'à une minute la première fois, ensuite en cache)…</div>
          <Skeleton className="mt-4 h-64" />
        </Card>
      )}
      {d && !bt.loading && (
        <>
          <Card className={cx("flex flex-col gap-3 p-5 sm:flex-row sm:items-center", anySig ? "border-warn/40" : "border-good/30")}>
            <span className={cx("inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", anySig ? "bg-warn/10 text-warn" : "bg-good/10 text-good")} aria-hidden>
              {anySig ? <Scale className="h-5 w-5" /> : <CheckCircle2 className="h-5 w-5" />}
            </span>
            <div className="text-sm leading-relaxed">
              <div className="font-semibold">
                {anySig ? "Un écart statistiquement significatif apparaît — probablement fortuit, à revérifier sur d'autres périodes."
                  : "Aucune stratégie ne fait significativement mieux (ni moins bien) que le hasard."}
              </div>
              <div className="text-muted">
                {fmtInt(d.n_test_draws)} tirages testés du {fmtDate(d.first_test_date)} au {fmtDate(d.last_test_date)}, {fmtInt(d.n_grids_per_strategy)} grilles par stratégie.
                Attendu théorique : {fmtNum(d.theoretical_mean_hits, 2)} bon numéro par grille. Hasard observé : {random ? fmtNum(random.mean_hits, 3) : "—"}.
              </div>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Bons numéros par grille (moyenne, IC 95 %)</h3>
              <p className="text-xs text-muted">Ligne pointillée : espérance théorique exacte</p>
              <div className="h-64" role="img" aria-label="Moyenne de bons numéros par stratégie avec intervalles de confiance">
                <ResponsiveContainer>
                  <BarChart data={chartData} margin={{ top: 12, right: 8, left: -14, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke={c.grid} />
                    <XAxis dataKey="name" {...axisProps(c)} interval={0} angle={-20} textAnchor="end" height={56} />
                    <YAxis {...axisProps(c)} domain={[0, "auto"]} tickFormatter={(v) => fmtNum(v, 2)} />
                    <Tooltip formatter={(v: number) => fmtNum(v, 3)} />
                    <ReferenceLine y={d.theoretical_mean_hits} stroke={c.fg} strokeDasharray="5 4" />
                    <Bar dataKey="mean" name="Moyenne" radius={[6, 6, 0, 0]} isAnimationActive={false}>
                      {chartData?.map((x, i) => <Cell key={x.key} fill={x.key === "aleatoire" ? c.muted : c.series[i % c.series.length]} />)}
                      <ErrorBar dataKey="err" width={6} stroke={c.fg} strokeWidth={1.2} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Moyenne cumulée au fil des tirages</h3>
              <p className="text-xs text-muted">Toutes les courbes convergent vers {fmtNum(d.theoretical_mean_hits, 2)}</p>
              <div className="h-64" role="img" aria-label="Évolution de la moyenne cumulée par stratégie">
                <ResponsiveContainer>
                  <LineChart data={cum} margin={{ top: 12, right: 8, left: -14, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke={c.grid} />
                    <XAxis dataKey="date" {...axisProps(c)} tickFormatter={fmtShort} minTickGap={40} />
                    <YAxis {...axisProps(c)} domain={["auto", "auto"]} tickFormatter={(v) => fmtNum(v, 2)} />
                    <Tooltip labelFormatter={(l) => fmtDate(String(l))} formatter={(v: number) => fmtNum(v, 3)} />
                    <ReferenceLine y={d.theoretical_mean_hits} stroke={c.fg} strokeDasharray="5 4" />
                    {d.results.map((r, i) => (
                      <Line key={r.strategy} dataKey={r.strategy} name={r.label.replace(/ \(.*\)/, "")} dot={false} isAnimationActive={false}
                        stroke={r.strategy === "aleatoire" ? c.muted : c.series[i % c.series.length]} strokeWidth={r.strategy === "aleatoire" ? 2.5 : 1.6} />
                    ))}
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <Card className="p-4 sm:p-5">
            <h3 className="text-sm font-semibold">Comparaison détaillée</h3>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm tabular">
                <caption className="sr-only">Résultats du backtest par stratégie</caption>
                <thead className="text-left text-xs text-muted">
                  <tr>
                    <th className="py-2 pr-3 font-medium">Stratégie</th><th className="pr-3 font-medium">Bons n°/grille</th>
                    <th className="pr-3 font-medium" title="Écart à l'espérance théorique">vs théorie</th><th className="pr-3 font-medium">IC 95 %</th>
                    <th className="pr-3 font-medium" title="p-value (inférence par tirage, robuste à la corrélation des grilles)">p</th>
                    <th className="pr-3 font-medium" title="Test apparié contre la stratégie aléatoire">p vs hasard</th>
                    <th className="pr-3 font-medium">≥ 3 bons</th>
                    <th className="pr-3 font-medium" title="Gains réels (montants officiels par rang) / mises">Retour réel</th>
                    <th className="pr-3 font-medium">Anti-partage</th>
                    <th className="pr-3 font-medium" title="Part moyenne du jackpot conservée en cas de gain (modèle)">Part jackpot</th>
                  </tr>
                </thead>
                <tbody>
                  {d.results.map((r) => (
                    <tr key={r.strategy} className={cx("border-t border-border", r.strategy === "aleatoire" && "bg-surface-2/60")}>
                      <td className="py-2 pr-3 font-medium">{r.label}</td>
                      <td className="pr-3">{fmtNum(r.mean_hits, 3)}</td>
                      <td className={cx("pr-3", r.delta_vs_theory_pct > 0 ? "text-good" : r.delta_vs_theory_pct < 0 ? "text-bad" : "")}>{r.delta_vs_theory_pct > 0 ? "+" : ""}{fmtNum(r.delta_vs_theory_pct, 1)} %</td>
                      <td className="pr-3 text-muted">[{fmtNum(r.ci95[0], 3)} ; {fmtNum(r.ci95[1], 3)}]</td>
                      <td className={cx("pr-3", r.significant && "font-semibold text-warn")}>{fmtP(r.p_value)}</td>
                      <td className="pr-3">{r.p_value_vs_random != null ? fmtP(r.p_value_vs_random) : "—"}</td>
                      <td className="pr-3">{fmtNum(r.at_least_3_pct, 2)} %</td>
                      <td className="pr-3">{fmtPct(r.return_pct, 0)}</td>
                      <td className="pr-3">{Math.round(r.mean_anti_score)}/100</td>
                      <td className="pr-3">{fmtPct(r.mean_expected_jackpot_share * 100, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-muted">
              {d.method} Les grilles d'un même tirage étant corrélées, les p-values sont calculées sur les moyennes par tirage.
              Correction de Bonferroni pour {others.length} comparaisons : seuil {fmtNum(0.05 / Math.max(1, others.length), 3)}.
              Le « retour réel » utilise les montants officiels publiés pour chaque rang ; il est dominé par la rareté des gros lots
              {info ? ` (probabilité du rang 1 : 1 sur ${fmtInt(info.n_combinations)})` : ""}.
            </p>
          </Card>
        </>
      )}
    </section>
  );
}

function PopularitySection({ game, info }: { game: string; info?: GameInfo }) {
  const c = useChartColors();
  const pop = useAsync<PopularityInfo>(() => api.popularity(game as "lotto"), [game]);
  const p = pop.data;
  const dg = p?.diagnostics;
  return (
    <section aria-labelledby="pop-title" className="space-y-4">
      <SectionTitle id="pop-title" title="Stratégie anti-partage"
        subtitle="Fréquence de sortie et popularité auprès des joueurs sont deux phénomènes indépendants." />
      <Notice>
        Les gros lots sont partagés entre gagnants. Jouer une combinaison peu populaire <strong>ne change pas la probabilité de gagner</strong>,
        mais augmente la part reçue <em>si</em> vous gagnez. La popularité est <strong>estimée</strong> : la Loterie ne publie pas les grilles jouées.
      </Notice>
      {pop.error && <ErrorState message={pop.error} onRetry={pop.reload} />}
      {!p ? <Skeleton className="h-72" /> : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card className="p-4 sm:p-5">
              <div className="label">Données de calibration</div>
              <div className="mt-2 text-2xl font-semibold tabular">{fmtInt(dg?.n_draws_used ?? 0)} tirages</div>
              <div className="text-xs text-muted">nombre réel de gagnants belges aux rangs intermédiaires, comparé à l'attendu sous un jeu uniforme</div>
            </Card>
            <Card className="p-4 sm:p-5">
              <div className="label">Qualité prédictive (hors échantillon)</div>
              <div className="mt-2 text-2xl font-semibold tabular">{dg?.oos_r2 != null ? `R² = ${fmtNum(dg.oos_r2, 2)}` : "—"}</div>
              <div className="text-xs text-muted">ajusté sur les 80 % premiers tirages, testé sur les 20 % suivants{dg?.oos_corr != null ? ` (corrélation ${fmtNum(dg.oos_corr, 2)})` : ""}</div>
            </Card>
            <Card className="p-4 sm:p-5">
              <div className="label">Écart de popularité entre tirages</div>
              <div className="mt-2 text-2xl font-semibold tabular">{dg?.ratio_spread ? `×${fmtNum(dg.ratio_spread[0])} → ×${fmtNum(dg.ratio_spread[2])}` : "—"}</div>
              <div className="text-xs text-muted">gagnants observés / attendus (5ᵉ–95ᵉ percentile){dg?.international_factor ? ` · volume européen ≈ ×${fmtNum(dg.international_factor, 1)} la Belgique` : ""}</div>
            </Card>
          </div>
          <Card className="p-4 sm:p-5">
            <h3 className="text-sm font-semibold">Popularité estimée de chaque numéro</h3>
            <p className="text-xs text-muted">1 = popularité moyenne · au-dessus : surjoué (dates, 7…), en dessous : délaissé</p>
            <div className="h-60" role="img" aria-label="Multiplicateur de popularité par numéro">
              <ResponsiveContainer>
                <BarChart data={p.numbers} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke={c.grid} />
                  <XAxis dataKey="number" {...axisProps(c)} interval={1} />
                  <YAxis {...axisProps(c)} domain={[0.7, 1.35]} tickFormatter={(v) => fmtNum(v, 1)} />
                  <Tooltip formatter={(v: number) => `×${fmtNum(v, 3)}`} labelFormatter={(l) => `Numéro ${l}`} />
                  <ReferenceLine y={1} stroke={c.muted} />
                  <ReferenceLine x={31.5} stroke={c.warn} strokeDasharray="4 4" label={{ value: "31", fill: c.warn, fontSize: 11, position: "top" }} />
                  <Bar dataKey="multiplier" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                    {p.numbers.map((x) => <Cell key={x.number} fill={x.multiplier >= 1 ? c.bad : c.good} fillOpacity={0.8} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Exemples</h3>
              <ul className="mt-3 divide-y divide-border">
                {p.examples.map((e) => (
                  <li key={e.numbers.join("-")} className="space-y-2 py-3">
                    <Balls numbers={e.numbers} extras={e.extras} size="sm" />
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
                      <span>Popularité <strong className="text-fg">×{e.relative_popularity >= 100 ? fmtInt(Math.round(e.relative_popularity)) : fmtNum(e.relative_popularity)}</strong></span>
                      <span>Anti-partage <strong className="text-fg">{Math.round(e.anti_score)}/100</strong></span>
                      <span>Part du jackpot si gain <strong className="text-fg">{fmtPct(e.expected_jackpot_share * 100, 1)}</strong></span>
                    </div>
                    {e.patterns.length > 0 && <div className="text-xs text-warn">{e.patterns.join(" · ")}</div>}
                  </li>
                ))}
              </ul>
            </Card>
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Hypothèses du modèle</h3>
              <p className="mt-1 text-xs text-muted">Partie <strong>estimée</strong> sur données officielles : préférence par numéro, effet « tous ≤ 31 » ({dg?.beta_all_le31 != null ? fmtNum(dg.beta_all_le31, 2) : "—"}), numéros consécutifs ({dg?.beta_consecutive != null ? fmtNum(dg.beta_consecutive, 2) : "—"}). Partie <strong>a priori</strong> (motifs jamais tirés, donc non estimables) — ordres de grandeur issus d'études publiées sur les choix des joueurs :</p>
              <ul className="mt-3 space-y-1.5 text-sm">
                {p.priors.map((x) => (
                  <li key={x.key} className="flex justify-between gap-3"><span className="text-muted">{x.label}</span><span className="tabular font-medium">×{fmtInt(Math.round(Math.exp(x.log_lift)))}</span></li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">
                Part du jackpot : autres gagnants ~ Poisson(λ), λ = {fmtInt(p.boards_typical)} grilles × popularité / {fmtInt(p.n_combinations)} combinaisons ;
                part espérée = (1 − e<sup>−λ</sup>)/λ.
              </p>
            </Card>
          </div>
          <ScoreMyGrid game={game} info={info} />
        </>
      )}
    </section>
  );
}

function ScoreMyGrid({ game, info }: { game: string; info?: GameInfo }) {
  const { balance } = useApp();
  const [sel, setSel] = useState<number[]>([]);
  const [stars, setStars] = useState<number[]>([]);
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.score>>>();
  const [err, setErr] = useState<string>();
  if (!info) return null;
  const k = info.main.picks;
  const ke = info.extra?.picks ?? 0;
  const ready = sel.length === k && stars.length === ke;
  const toggle = (arr: number[], set: (v: number[]) => void, n: number, max: number) => {
    setRes(undefined);
    set(arr.includes(n) ? arr.filter((x) => x !== n) : arr.length < max ? [...arr, n].sort((a, b) => a - b) : arr);
  };
  async function run() {
    setErr(undefined);
    try { setRes(await api.score(game as "lotto", sel, ke ? stars : null, balance)); } catch (e) { setErr((e as Error).message); }
  }
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-accent" aria-hidden /><h3 className="text-sm font-semibold">Analyser ma propre grille</h3></div>
      <p className="mt-1 text-xs text-muted">Choisissez {k} numéros{ke ? ` et ${ke} étoiles` : ""} pour obtenir les deux scores.</p>
      <div className="mt-3 grid grid-cols-9 gap-1.5 sm:grid-cols-[repeat(15,minmax(0,1fr))]" role="group" aria-label="Grille de sélection">
        {Array.from({ length: info.main.high }, (_, i) => i + 1).map((n) => (
          <button key={n} onClick={() => toggle(sel, setSel, n, k)} aria-pressed={sel.includes(n)}
            className={cx("aspect-square min-h-[34px] rounded-lg text-xs font-semibold tabular ring-1 ring-inset transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              sel.includes(n) ? "bg-accent text-accent-fg ring-accent" : "bg-surface-2 text-muted ring-border hover:text-fg")}>{n}</button>
        ))}
      </div>
      {info.extra && (
        <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Étoiles">
          {Array.from({ length: info.extra.high }, (_, i) => i + 1).map((n) => (
            <button key={n} onClick={() => toggle(stars, setStars, n, ke)} aria-pressed={stars.includes(n)}
              className={cx("h-9 w-9 rounded-full text-xs font-semibold ring-1 ring-inset focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                stars.includes(n) ? "bg-star/30 text-fg ring-star" : "bg-surface-2 text-muted ring-border")}>{n}</button>
          ))}
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={!ready} onClick={run}>Analyser</button>
        <button className="btn-ghost" onClick={() => { setSel([]); setStars([]); setRes(undefined); }}>Effacer</button>
        <span className="text-xs text-muted">{sel.length}/{k}{ke ? ` · ${stars.length}/${ke} étoiles` : ""}</span>
      </div>
      {err && <div className="mt-3"><ErrorState message={err} /></div>}
      {res && (
        <div className="mt-4 grid animate-fade gap-4 rounded-xl bg-surface-2 p-4 sm:grid-cols-[1fr_1.2fr]">
          <div className="grid grid-cols-3 gap-3">
            <ScoreBar label="Statistique" value={res.stat_score} />
            <ScoreBar label="Anti-partage" value={res.anti_score} tone="good" />
            <ScoreBar label="Global" value={res.global_score} tone="star" />
          </div>
          <ul className="space-y-1 text-sm">{res.details.reasons.map((r) => <li key={r}>• {r}</li>)}</ul>
        </div>
      )}
    </Card>
  );
}

export default function Algorithms() {
  const { game, info } = useApp();
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Algorithmes & preuves</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Comment les grilles sont construites, ce que chaque méthode peut — et ne peut pas — apporter, et leur performance mesurée sur des tirages réels jamais vus par le moteur.
        </p>
      </div>
      <BacktestSection game={game} info={info} />
      <section aria-labelledby="methods-title">
        <SectionTitle id="methods-title" title="Méthodes étudiées" subtitle="Intérêt, limites et rôle de chaque approche dans la génération." />
        <div className="grid gap-4 md:grid-cols-2">
          {METHODS.map((m) => (
            <Card key={m.name} className="p-4 sm:p-5">
              <h3 className="font-semibold tracking-tight">{m.name}</h3>
              <p className="mt-1 text-sm text-muted">{m.what}</p>
              <dl className="mt-3 space-y-2 text-sm">
                <div><dt className="label text-good">Intérêt</dt><dd>{m.pro}</dd></div>
                <div><dt className="label text-bad">Limites</dt><dd>{m.con}</dd></div>
                <div><dt className="label text-accent">Contribution</dt><dd>{m.use}</dd></div>
              </dl>
            </Card>
          ))}
        </div>
      </section>
      <PopularitySection game={game} info={info} />
    </div>
  );
}
