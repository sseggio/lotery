import { ArrowRight, CalendarDays, Flame, Sigma, Sparkles, Snowflake, Timer } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BalanceControl } from "../components/BalanceControl";
import { GridCard } from "../components/GridCard";
import { SyncButton } from "../components/Layout";
import { Ball, Balls, Card, ErrorState, Kpi, Notice, SectionTitle, Skeleton, useNow } from "../components/ui";
import { api, FreqRow, Generation } from "../lib/api";
import { useApp } from "../lib/app-context";
import { fmtDate, fmtDateTime, fmtInt, fmtNum, fmtP, fmtRelative } from "../lib/format";
import { useAsync } from "../lib/hooks";

function NumberList({ title, rows, icon, value }: { title: string; rows?: FreqRow[]; icon: React.ReactNode; value: (r: FreqRow) => string }) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold">{icon}{title}</div>
      {!rows ? <Skeleton className="h-24" /> : (
        <ul className="grid grid-cols-4 gap-x-2 gap-y-3">
          {rows.slice(0, 8).map((r) => (
            <li key={r.number} className="flex flex-col items-center gap-1">
              <Ball n={r.number} size="sm" />
              <span className="text-[11px] text-muted tabular">{value(r)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function Home() {
  useNow();
  const { game, info, balance, dataVersion } = useApp();
  const summary = useAsync(() => api.summary(game), [game, dataVersion]);
  const latest = useAsync(() => api.latest(game), [game]);
  const bt = useAsync(() => api.backtest(game, 100, 10, 0.5), [game]);
  const [gen, setGen] = useState<Generation | null>(null);
  const [busy, setBusy] = useState<number | "all" | null>(null);
  const [err, setErr] = useState<string>();
  const firstBalance = useRef(true);

  useEffect(() => { setGen(latest.data ?? null); }, [latest.data]);

  async function generateAll(b = balance) {
    setBusy("all");
    setErr(undefined);
    try { setGen(await api.generate(game, b)); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }

  async function regenerate(slot: number) {
    if (!gen) return;
    setBusy(slot);
    setErr(undefined);
    try { setGen(await api.regenerate(game, gen.id, slot, balance)); } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }

  async function toggleFav(id: number, fav: boolean) {
    if (!gen) return;
    try {
      await api.favorite(id, fav);
      setGen({ ...gen, grids: gen.grids.map((g) => (g.id === id ? { ...g, favorite: fav } : g)) });
    } catch (e) { setErr((e as Error).message); }
  }

  // First visit: generate automatically once data is there.
  useEffect(() => {
    if (!latest.loading && !latest.error && latest.data === null && (summary.data?.total_draws ?? 0) >= 30 && busy === null && !gen) {
      generateAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latest.loading, latest.data, summary.data]);

  // The balance setting recomputes the 4 grids (debounced).
  useEffect(() => {
    if (firstBalance.current) { firstBalance.current = false; return; }
    if (!gen || Math.abs(gen.balance - balance) < 0.001) return;
    const t = setTimeout(() => generateAll(balance), 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [balance]);

  const s = summary.data;
  const proof = (() => {
    const r = bt.data?.results;
    if (!r) return null;
    const rnd = r.find((x) => x.strategy === "aleatoire");
    const ours = r.filter((x) => ["frequence", "tendance", "hybride", "anti_partage"].includes(x.strategy));
    const anti = r.find((x) => x.strategy === "anti_partage");
    if (!rnd || !ours.length || !anti) return null;
    return {
      n: bt.data!.n_test_draws, random: rnd.mean_hits, theory: bt.data!.theoretical_mean_hits,
      ours: ours.reduce((a, x) => a + x.mean_hits, 0) / ours.length,
      share: (anti.mean_expected_jackpot_share / rnd.mean_expected_jackpot_share - 1) * 100,
    };
  })();
  const newerDraws = gen && s?.last_draw && s.last_draw.draw_id > gen.last_draw_id;
  const odds = info ? fmtInt(info.n_combinations) : "…";

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{info?.label ?? "…"} · Tableau de bord</h1>
      </div>

      {summary.error && <ErrorState message={summary.error} onRetry={summary.reload} />}
      {s?.sync.last_attempt?.status === "error" && (
        <Notice tone="warn">
          La dernière actualisation a échoué ({s.sync.last_attempt.message}). Les données affichées restent celles du
          {" "}{fmtDate(s.last_draw?.date)}, la source officielle sera réinterrogée automatiquement.
        </Notice>
      )}
      {s && s.total_draws < 30 && (
        <Card className="flex flex-col items-start gap-4 p-6">
          <h2 className="text-lg font-semibold">Récupération des tirages officiels…</h2>
          <p className="text-sm text-muted">La première synchronisation télécharge l'historique depuis la Loterie Nationale. Cela prend quelques secondes.</p>
          <SyncButton onDone={() => { summary.reload(); latest.reload(); }} />
        </Card>
      )}

      {/* Last draw: compact banner */}
      <Card className="relative overflow-hidden p-4 sm:p-5">
        <div className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-accent/10 blur-3xl" aria-hidden />
        {!s ? <Skeleton className="h-12" /> : s.last_draw && (
          <div className="relative flex flex-col gap-3 md:flex-row md:items-center md:gap-6">
            <div className="shrink-0 md:w-56">
              <div className="label">Dernier tirage pris en compte</div>
              <div className="mt-1 text-sm font-medium">{fmtDate(s.last_draw.date)}</div>
              <div className="text-xs text-muted">tirage n° {s.last_draw.draw_id}</div>
            </div>
            <div className="flex-1"><Balls numbers={s.last_draw.numbers} extras={s.last_draw.extras} bonus={s.last_draw.bonus} size="md" label="Dernier tirage" /></div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted md:flex-col md:items-end">
              {s.last_draw.verified
                ? <span className="chip border-good/30 text-good">Vérifié par 2 sources officielles</span>
                : <span className="chip">Source : API officielle</span>}
              <span className="inline-flex items-center gap-1.5"><Timer className="h-3.5 w-3.5" aria-hidden />Synchronisé {fmtRelative(s.sync.last_success_at)}</span>
            </div>
          </div>
        )}
      </Card>

      {/* Grids */}
      <section aria-labelledby="grids-title">
        <SectionTitle id="grids-title" title="Vos 4 grilles"
          subtitle={gen ? <>Calculées le {fmtDateTime(gen.created_at)} sur {fmtInt(gen.n_draws_used)} tirages (jusqu'au {fmtDate(gen.last_draw_date)})</> : "Générées par le moteur statistique"}
          action={
            <button className="btn-primary w-full sm:w-auto" onClick={() => generateAll()} disabled={busy !== null || !s || s.total_draws < 30}>
              <Sparkles className={busy === "all" ? "h-4 w-4 animate-pulse" : "h-4 w-4"} aria-hidden />
              {busy === "all" ? "Calcul en cours…" : "Générer 4 nouvelles grilles"}
            </button>
          } />
        <div className="mb-4 flex flex-col gap-3 rounded-2xl border border-border bg-surface p-3 sm:flex-row sm:items-center sm:justify-between sm:p-4">
          <div className="text-sm">
            <div className="font-medium">Priorité de génération</div>
            <div className="text-xs text-muted">Recalcule les 4 grilles : statistiques historiques ↔ réduction du risque de partage.</div>
          </div>
          <BalanceControl />
        </div>
        {newerDraws && (
          <div className="mb-4"><Notice>De nouveaux tirages sont disponibles depuis le calcul de ces grilles. <button className="font-medium text-accent underline underline-offset-2" onClick={() => generateAll()}>Recalculer maintenant</button></Notice></div>
        )}
        {err && <div className="mb-4"><ErrorState message={err} /></div>}
        <p className="mb-3 text-xs leading-relaxed text-muted">
          Scores = rang face à des milliers de grilles aléatoires (<strong className="font-medium text-fg">50 = grille moyenne</strong>, repère central des barres).
          Ils ne changent pas la probabilité de gain : 1 chance sur {odds} pour le rang 1, pour toutes les grilles.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {(gen?.grids ?? []).map((g) => (
            <GridCard key={g.slot} grid={g} busy={busy === g.slot || busy === "all"}
              onRegenerate={() => regenerate(g.slot)} onFavorite={(f) => toggleFav(g.id, f)} />
          ))}
          {!gen && [1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-72" />)}
        </div>
        {proof && (
          <Link to="/algorithmes" className="mt-4 flex flex-col gap-2 rounded-2xl border border-border bg-surface-2/70 p-4 text-sm transition-colors hover:bg-surface-2 sm:flex-row sm:items-center sm:justify-between">
            <span>
              <strong className="font-semibold">Preuve sur {proof.n} tirages passés</strong>
              <span className="text-muted"> — bons numéros par grille : nos stratégies {fmtNum(proof.ours, 2)} · hasard {fmtNum(proof.random, 2)} · théorie {fmtNum(proof.theory, 2)}.
                Seul gain mesurable : ≈ +{fmtNum(proof.share, 0)} % de jackpot conservé en cas de gain (estimation).</span>
            </span>
            <span className="inline-flex shrink-0 items-center gap-1 font-medium text-accent">Voir les preuves <ArrowRight className="h-4 w-4" aria-hidden /></span>
          </Link>
        )}
      </section>

      {/* Quick stats */}
      <section aria-labelledby="quick-title">
        <SectionTitle id="quick-title" title="En bref" subtitle={s?.year_from ? `Depuis le ${fmtDate(s.year_from)}` : undefined}
          action={<Link to="/statistiques" className="btn-ghost">Statistiques détaillées <ArrowRight className="h-4 w-4" aria-hidden /></Link>} />
        <div className="mb-4 grid grid-cols-2 gap-4">
          <Kpi label="Tirages analysés" icon={<CalendarDays className="h-4 w-4" />}
            value={s?.year_draws != null ? fmtInt(s.year_draws) : "—"}
            sub={s?.history_draws ? <>année en cours · {fmtInt(s.history_draws)} en historique</> : "année en cours"} />
          <Kpi label="Hasard des fréquences (χ²)" icon={<Sigma className="h-4 w-4" />}
            value={s?.chi_square ? `p = ${fmtP(s.chi_square.p_value)}` : "—"}
            sub={s?.chi_square ? (s.chi_square.p_value > 0.01
              ? "Écarts du même ordre que le hasard pur"
              : "Écart marqué : à confirmer sur d'autres périodes") : " "} />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <NumberList title="Les plus fréquents" rows={s?.most_frequent} icon={<Flame className="h-4 w-4 text-warn" aria-hidden />} value={(r) => `${r.count}×`} />
          <NumberList title="Les moins fréquents" rows={s?.least_frequent} icon={<Snowflake className="h-4 w-4 text-accent" aria-hidden />} value={(r) => `${r.count}×`} />
          <NumberList title="Absents depuis longtemps" rows={s?.overdue} icon={<Timer className="h-4 w-4 text-muted" aria-hidden />} value={(r) => `${r.gap} tir.`} />
        </div>
        <Card className="mt-4 p-4 sm:p-5">
          <div className="mb-3 text-sm font-semibold">Numéros récemment sortis</div>
          {!s?.recent_draws ? <Skeleton className="h-32" /> : (
            <ul className="divide-y divide-border">
              {s.recent_draws.map((d) => (
                <li key={d.date} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-6">
                  <span className="w-40 shrink-0 text-sm text-muted">{fmtDate(d.date)}</span>
                  <Balls numbers={d.numbers} extras={d.extras} bonus={d.bonus} size="sm" />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>
    </div>
  );
}
