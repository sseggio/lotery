import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { axisProps, useChartColors } from "../components/charts";
import { Ball, Card, cx, ErrorState, Notice, SectionTitle, Segmented, Skeleton } from "../components/ui";
import { api, FreqRow, Stats as StatsT } from "../lib/api";
import { useApp } from "../lib/app-context";
import { fmtDate, fmtNum, fmtP, fmtShort } from "../lib/format";
import { useAsync } from "../lib/hooks";

const WINDOWS = [
  { value: "year", label: "Année" }, { value: "30", label: "30 tirages" }, { value: "60", label: "60" },
  { value: "90", label: "90" }, { value: "all", label: "Tout" },
];

type Metric = "count" | "gap" | "ewma";

function FrequencyChart({ rows, expected, metric, label }: { rows: FreqRow[]; expected: number; metric: Metric; label: string }) {
  const c = useChartColors();
  const data = rows.map((r) => ({ n: r.number, v: metric === "count" ? r.count : metric === "gap" ? r.gap : r.ewma, z: r.z }));
  const ref = metric === "count" ? expected : undefined;
  return (
    <div className="h-64 w-full sm:h-72" role="img" aria-label={label}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={c.grid} />
          <XAxis dataKey="n" {...axisProps(c)} ticks={data.length > 15 ? data.map((d) => d.n).filter((n) => n === 1 || n % 5 === 0) : undefined} interval={0} />
          <YAxis {...axisProps(c)} allowDecimals={false} />
          <Tooltip cursor={{ fill: c.grid, opacity: 0.4 }}
            formatter={(v: number) => [metric === "ewma" ? `${fmtNum(v)} %` : v, metric === "count" ? "Sorties" : metric === "gap" ? "Tirages d'absence" : "Taux pondéré"]}
            labelFormatter={(l) => `Numéro ${l}`} />
          {ref !== undefined && <ReferenceLine y={ref} stroke={c.muted} strokeDasharray="4 4" label={{ value: "attendu", fill: c.muted, fontSize: 11, position: "insideTopRight" }} />}
          <Bar dataKey="v" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {data.map((d) => (
              <Cell key={d.n} fill={metric !== "count" ? c.accent : d.z > 1 ? c.accent : d.z < -1 ? c.muted : c.accent}
                fillOpacity={metric !== "count" ? 0.85 : d.z > 1 ? 1 : d.z < -1 ? 0.45 : 0.7} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Evolution({ st }: { st: StatsT }) {
  const c = useChartColors();
  const ranked = [...st.frequencies].sort((a, b) => b.count - a.count);
  const [picked, setPicked] = useState<number[]>(() => [ranked[0].number, ranked[1].number, ranked[ranked.length - 1].number]);
  const data = st.evolution.dates.map((d, i) => {
    const row: Record<string, number | string> = { d };
    picked.forEach((n) => { row[String(n)] = st.evolution.series[String(n)][i]; });
    return row;
  });
  const toggle = (n: number) =>
    setPicked(picked.includes(n) ? picked.filter((x) => x !== n) : picked.length >= 5 ? [...picked.slice(1), n] : [...picked, n]);
  return (
    <Card className="p-4 sm:p-5">
      <SectionTitle title="Évolution des fréquences"
        subtitle={`Nombre de sorties sur une fenêtre glissante de ${st.evolution.span} tirages (attendu : ${fmtNum(st.evolution.expected, 1)})`} />
      <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Numéros affichés (5 maximum)">
        {st.frequencies.map((r) => {
          const idx = picked.indexOf(r.number);
          return (
            <button key={r.number} onClick={() => toggle(r.number)} aria-pressed={idx >= 0}
              className={cx("h-9 w-9 rounded-full text-xs font-semibold tabular ring-1 ring-inset transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
                idx >= 0 ? "text-white ring-transparent" : "bg-surface-2 text-muted ring-border hover:text-fg")}
              style={idx >= 0 ? { background: c.series[idx % c.series.length], color: c.dark ? "#0b0d12" : "#fff" } : undefined}>
              {r.number}
            </button>
          );
        })}
      </div>
      <div className="h-64 sm:h-72" role="img" aria-label="Courbes d'évolution des numéros sélectionnés">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={c.grid} />
            <XAxis dataKey="d" {...axisProps(c)} tickFormatter={fmtShort} minTickGap={40} />
            <YAxis {...axisProps(c)} allowDecimals={false} />
            <Tooltip labelFormatter={(l) => fmtDate(String(l))} />
            <ReferenceLine y={st.evolution.expected} stroke={c.muted} strokeDasharray="4 4" />
            {picked.map((n, i) => (
              <Line key={n} dataKey={String(n)} name={`N° ${n}`} stroke={c.series[i % c.series.length]} strokeWidth={2} dot={false} isAnimationActive={false} />
            ))}
            <Legend wrapperStyle={{ fontSize: 12 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function Heatmap({ st }: { st: StatsT }) {
  const { months, matrix, draws } = st.heatmap;
  if (months.length < 2) return null;
  const max = Math.max(1, ...matrix.flat());
  const n = st.frequencies.length;
  return (
    <Card className="p-4 sm:p-5">
      <SectionTitle title="Carte de chaleur mensuelle" subtitle="Sorties par numéro et par mois — les périodes de forte et faible fréquence apparaissent en relief." />
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-[3px] text-[10px] tabular">
          <caption className="sr-only">Nombre de sorties par numéro (colonnes) et par mois (lignes)</caption>
          <thead>
            <tr><th className="sticky left-0 bg-surface pr-2 text-left font-medium text-muted">Mois</th>
              {Array.from({ length: n }, (_, i) => <th key={i} className="w-5 font-medium text-muted">{i + 1}</th>)}</tr>
          </thead>
          <tbody>
            {months.map((m, r) => (
              <tr key={m}>
                <th className="sticky left-0 whitespace-nowrap bg-surface pr-2 text-left font-medium text-muted">{m} <span className="opacity-60">({draws[r]})</span></th>
                {matrix[r].map((v, j) => (
                  <td key={j} title={`N° ${j + 1} · ${m} : ${v} sortie(s)`}
                    className="h-5 w-5 rounded-[4px] text-center align-middle"
                    style={{ background: v ? `rgb(var(--accent) / ${0.12 + 0.88 * (v / max)})` : "rgb(var(--surface-2))", color: v / max > 0.55 ? "rgb(var(--accent-fg))" : "rgb(var(--muted))" }}>
                    {v || ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

type SortKey = keyof Pick<FreqRow, "number" | "count" | "z" | "count_30" | "count_60" | "count_90" | "gap" | "mean_gap" | "max_gap" | "ewma">;

function FreqTable({ rows }: { rows: FreqRow[] }) {
  const [sort, setSort] = useState<{ k: SortKey; dir: 1 | -1 }>({ k: "count", dir: -1 });
  const sorted = useMemo(() => [...rows].sort((a, b) => ((a[sort.k] ?? 0) as number) > ((b[sort.k] ?? 0) as number) ? sort.dir : -sort.dir), [rows, sort]);
  const cols: { k: SortKey; label: string; title?: string }[] = [
    { k: "number", label: "N°" }, { k: "count", label: "Sorties" }, { k: "z", label: "Écart (z)", title: "Écart à l'attendu en écarts-types. |z| < 2 : variation normale du hasard." },
    { k: "count_30", label: "30 der." }, { k: "count_60", label: "60 der." }, { k: "count_90", label: "90 der." },
    { k: "gap", label: "Retard" }, { k: "mean_gap", label: "Écart moyen" }, { k: "max_gap", label: "Retard max" },
    { k: "ewma", label: "Pondéré %", title: "Moyenne mobile exponentielle (demi-vie 12 tirages)" },
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm tabular">
        <caption className="sr-only">Statistiques par numéro, triables</caption>
        <thead>
          <tr className="text-left text-xs text-muted">
            {cols.map((c) => (
              <th key={c.k} className={cx("py-2 pr-3 font-medium", c.k === "number" && "sticky left-0 z-[1] bg-surface")} aria-sort={sort.k === c.k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                <button className="inline-flex min-h-[32px] items-center gap-1 hover:text-fg" title={c.title}
                  onClick={() => setSort({ k: c.k, dir: sort.k === c.k ? (sort.dir === 1 ? -1 : 1) : -1 })}>
                  {c.label}{sort.k === c.k && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" aria-hidden /> : <ArrowDown className="h-3 w-3" aria-hidden />)}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.number} className="border-t border-border">
              <td className="sticky left-0 z-[1] bg-surface py-1.5 pr-3"><Ball n={r.number} size="sm" /></td>
              <td className="pr-3 font-medium">{r.count}</td>
              <td className={cx("pr-3", Math.abs(r.z) >= 2 ? "font-semibold text-warn" : "text-muted")}>{r.z > 0 ? "+" : ""}{fmtNum(r.z)}</td>
              <td className="pr-3">{r.count_30}</td><td className="pr-3">{r.count_60}</td><td className="pr-3">{r.count_90}</td>
              <td className="pr-3">{r.gap}</td><td className="pr-3">{r.mean_gap != null ? fmtNum(r.mean_gap, 1) : "—"}</td>
              <td className="pr-3">{r.max_gap}</td><td className="pr-3">{fmtNum(r.ewma, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ObsTheoryChart({ data, xKey, label }: { data: Record<string, number | string>[]; xKey: string; label: string }) {
  const c = useChartColors();
  return (
    <div className="h-56" role="img" aria-label={label}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 4, left: -22, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={c.grid} />
          <XAxis dataKey={xKey} {...axisProps(c)} />
          <YAxis {...axisProps(c)} unit="%" />
          <Tooltip formatter={(v: number) => `${fmtNum(v, 1)} %`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="observed_pct" name="Observé" fill={c.accent} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="theoretical_pct" name="Théorique" fill={c.muted} fillOpacity={0.45} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function TupleList({ title, rows }: { title: string; rows: StatsT["pairs"] }) {
  return (
    <Card className="p-4 sm:p-5">
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-0.5 text-xs text-muted">Attendu par combinaison : {fmtNum(rows[0]?.expected ?? 0)} · maximum attendu par simple hasard ≈ {rows[0]?.expected_max_by_chance}</p>
      <ul className="mt-3 divide-y divide-border">
        {rows.map((t) => (
          <li key={t.numbers.join("-")} className="flex items-center justify-between gap-3 py-2">
            <div className="flex gap-1.5">{t.numbers.map((n) => <Ball key={n} n={n} size="sm" />)}</div>
            <span className={cx("text-sm font-semibold tabular", t.count > t.expected_max_by_chance ? "text-warn" : "")}>{t.count}×</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function Stats() {
  const { game, info, dataVersion } = useApp();
  const [win, setWin] = useState("year");
  const [metric, setMetric] = useState<Metric>("count");
  const st = useAsync(() => api.stats(game, win), [game, win, dataVersion]);
  const c = useChartColors();
  const d = st.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Statistiques détaillées</h1>
          <p className="mt-1 text-sm text-muted">{d ? <>{d.n_draws} tirages · du {fmtDate(d.from)} au {fmtDate(d.to)}</> : "Chargement…"}</p>
        </div>
        <Segmented label="Période analysée" value={win} onChange={setWin} options={WINDOWS} />
      </div>

      <Notice>
        Les tirages sont indépendants : un numéro « en retard » n'a pas plus de chances de sortir, un numéro « chaud » pas plus de chances de ressortir.
        Chaque statistique est comparée à sa valeur <strong>théorique sous un hasard parfait</strong> pour distinguer tendance réelle et bruit.
      </Notice>

      {st.error && <ErrorState message={st.error} onRetry={st.reload} />}
      {!d ? <div className="space-y-4"><Skeleton className="h-80" /><Skeleton className="h-80" /></div> : (
        <>
          <Card className="p-4 sm:p-5">
            <SectionTitle title="Fréquence des numéros"
              subtitle={<>Test du χ² d'uniformité : χ² = {fmtNum(d.chi_square.statistic, 1)} (ddl {d.chi_square.df}), p = {fmtP(d.chi_square.p_value)} — {d.chi_square.p_value > 0.05 ? "aucun écart significatif au hasard." : "écart significatif, à interpréter avec prudence."}</>}
              action={<Segmented size="sm" label="Indicateur" value={metric} onChange={setMetric}
                options={[{ value: "count", label: "Sorties" }, { value: "gap", label: "Retard" }, { value: "ewma", label: "Pondéré" }]} />} />
            <FrequencyChart rows={d.frequencies} expected={d.frequencies[0].expected} metric={metric} label="Histogramme des fréquences par numéro" />
            {metric === "count" && <p className="mt-2 text-xs text-muted">Barres foncées : au-dessus de l'attendu de plus d'un écart-type · claires : en dessous. Un écart inférieur à 2 écarts-types (|z| &lt; 2) est une variation normale du hasard.</p>}
          </Card>

          <Evolution key={`${game}-${win}`} st={d} />
          <Heatmap st={d} />

          <Card className="p-4 sm:p-5">
            <SectionTitle title="Tableau complet" subtitle="Cliquez sur un en-tête pour trier. Retard = tirages depuis la dernière sortie." />
            <FreqTable rows={d.frequencies} />
          </Card>

          {d.extra_frequencies && (
            <Card className="p-4 sm:p-5">
              <SectionTitle title="Étoiles" subtitle={d.extra_chi_square ? `χ² p = ${fmtP(d.extra_chi_square.p_value)}` : undefined} />
              <FrequencyChart rows={d.extra_frequencies} expected={d.extra_frequencies[0].expected} metric="count" label="Fréquence des étoiles" />
            </Card>
          )}

          <div>
            <SectionTitle title="Analyse des combinaisons" subtitle="Paires et triplets les plus fréquents comparés au maximum que le hasard produit naturellement." />
            <div className="grid gap-4 lg:grid-cols-2">
              <TupleList title="Paires les plus fréquentes" rows={d.pairs} />
              <TupleList title="Triplets les plus fréquents" rows={d.triplets} />
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Pairs / impairs</h3>
              <p className="text-xs text-muted">Nombre de numéros impairs par tirage</p>
              <ObsTheoryChart data={d.distributions.odd_even.map((x) => ({ ...x, label: `${x.value} imp.` }))} xKey="label" label="Répartition pairs impairs" />
            </Card>
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Petits / grands numéros</h3>
              <p className="text-xs text-muted">Nombre de numéros ≤ {d.distributions.low_threshold} par tirage</p>
              <ObsTheoryChart data={d.distributions.low_high.map((x) => ({ ...x, label: `${x.value} pet.` }))} xKey="label" label="Répartition petits grands" />
            </Card>
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Somme des numéros</h3>
              <p className="text-xs text-muted">Moyenne observée {fmtNum(d.distributions.sum_mean_observed, 1)} · théorique {fmtNum(d.distributions.sum_mean_theoretical, 1)} · 80 % des tirages entre {d.distributions.sum_central_80[0]} et {d.distributions.sum_central_80[1]}</p>
              <ObsTheoryChart data={d.distributions.sum_histogram.map((x) => ({ ...x, label: `${x.from}` }))} xKey="label" label="Histogramme des sommes" />
            </Card>
            <Card className="p-4 sm:p-5">
              <h3 className="text-sm font-semibold">Répartition par dizaines</h3>
              <p className="text-xs text-muted">Sorties observées et attendues</p>
              <div className="h-56" role="img" aria-label="Répartition par dizaines">
                <ResponsiveContainer>
                  <BarChart data={d.distributions.decades} margin={{ top: 8, right: 4, left: -18, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke={c.grid} />
                    <XAxis dataKey="label" {...axisProps(c)} />
                    <YAxis {...axisProps(c)} />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="observed" name="Observé" fill={c.accent} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    <Bar dataKey="expected" name="Attendu" fill={c.muted} fillOpacity={0.45} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Card className="p-4 sm:p-5">
              <div className="label">Tirages avec ≥ 2 consécutifs</div>
              <div className="mt-2 text-2xl font-semibold tabular">{fmtNum(d.distributions.consecutive_pct_observed, 1)} %</div>
              <div className="text-xs text-muted">théorique {fmtNum(d.distributions.consecutive_pct_theoretical, 1)} % · plus longue suite : {d.distributions.max_run_observed}</div>
            </Card>
            <Card className="p-4 sm:p-5">
              <div className="label">Reprise du tirage précédent</div>
              <ul className="mt-2 space-y-1 text-sm tabular">
                {d.recurring.carry_over.map((x) => (
                  <li key={x.shared} className="flex justify-between"><span className="text-muted">{x.shared} numéro(s) commun(s)</span><span>{fmtNum(x.observed_pct, 1)} % <span className="text-muted">/ {fmtNum(x.theoretical_pct, 1)} %</span></span></li>
                ))}
              </ul>
            </Card>
            <Card className="p-4 sm:p-5">
              <div className="label">Combinaisons répétées</div>
              <div className="mt-2 text-2xl font-semibold tabular">{d.recurring.exact_repeats.length}</div>
              <div className="text-xs text-muted">tirage(s) identique(s) sur la période — avec {info ? info.n_combinations.toLocaleString("fr-BE") : "…"} combinaisons possibles, une répétition est extrêmement rare.</div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
