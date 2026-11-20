import { Star } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { GridCard } from "../components/GridCard";
import { Balls, Card, ErrorState, SectionTitle, Segmented, Skeleton } from "../components/ui";
import { api, Generation, Grid } from "../lib/api";
import { useApp } from "../lib/app-context";
import { fmtDate, fmtDateTime } from "../lib/format";
import { useAsync } from "../lib/hooks";

const BAL_LABEL = (b: number) => (b >= 0.75 ? "Priorité statistiques" : b <= 0.25 ? "Priorité anti-partage" : "Équilibre");

export default function History() {
  const { game } = useApp();
  const [tab, setTab] = useState<"fav" | "hist">("fav");
  const [limit, setLimit] = useState(10);
  const favs = useAsync(() => api.favorites(game), [game, tab]);
  const hist = useAsync(() => api.generations(game, limit), [game, limit, tab]);

  // Open on the history when there is no favourite yet (once).
  const switched = useRef(false);
  useEffect(() => {
    if (!switched.current && favs.data && favs.data.length === 0) { switched.current = true; setTab("hist"); }
  }, [favs.data]);

  async function toggle(g: Grid, fav: boolean) {
    await api.favorite(g.id, fav);
    if (favs.data) favs.setData(fav ? favs.data : favs.data.filter((x) => x.id !== g.id));
    if (hist.data) hist.setData(hist.data.map((gen: Generation) => ({ ...gen, grids: gen.grids.map((x) => (x.id === g.id ? { ...x, favorite: fav } : x)) })));
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Historique & favoris</h1>
          <p className="mt-1 text-sm text-muted">Toutes les grilles générées sont conservées. Marquez vos préférées d'une étoile.</p>
        </div>
        <Segmented label="Affichage" value={tab} onChange={setTab}
          options={[{ value: "fav", label: `Favoris${favs.data ? ` (${favs.data.length})` : ""}` }, { value: "hist", label: "Historique" }]} />
      </div>

      {tab === "fav" && (
        <>
          {favs.error && <ErrorState message={favs.error} onRetry={favs.reload} />}
          {favs.loading && !favs.data && <Skeleton className="h-64" />}
          {favs.data?.length === 0 && (
            <Card className="flex flex-col items-center gap-3 p-10 text-center">
              <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-star/10 text-star"><Star className="h-5 w-5" aria-hidden /></span>
              <div className="font-semibold">Aucun favori pour l'instant</div>
              <p className="max-w-sm text-sm text-muted">Sur le tableau de bord, cliquez sur l'étoile d'une grille pour la retrouver ici.</p>
              <Link to="/" className="btn-primary">Voir mes grilles</Link>
            </Card>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {favs.data?.map((g) => <GridCard key={g.id} grid={g} compact onFavorite={(f) => toggle(g, f)} />)}
          </div>
        </>
      )}

      {tab === "hist" && (
        <>
          {hist.error && <ErrorState message={hist.error} onRetry={hist.reload} />}
          {hist.loading && !hist.data && <Skeleton className="h-64" />}
          {hist.data?.length === 0 && <Card className="p-10 text-center text-sm text-muted">Aucune grille générée pour ce jeu.</Card>}
          <div className="space-y-4">
            {hist.data?.map((gen) => (
              <Card key={gen.id} className="p-4 sm:p-5">
                <SectionTitle title={`Génération du ${fmtDateTime(gen.created_at)}`}
                  subtitle={<>{BAL_LABEL(gen.balance)} · données jusqu'au {fmtDate(gen.last_draw_date)} ({gen.n_draws_used} tirages)</>} />
                <ul className="divide-y divide-border">
                  {gen.grids.map((g) => (
                    <li key={g.id} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <div className="text-xs text-muted">Grille {g.slot} · {g.details.strategy_label}</div>
                        <div className="mt-1.5"><Balls numbers={g.numbers} extras={g.extras} size="sm" /></div>
                      </div>
                      <div className="flex items-center gap-4 text-xs tabular text-muted">
                        <span>Stat <strong className="text-fg">{Math.round(g.stat_score)}</strong></span>
                        <span>Anti <strong className="text-fg">{Math.round(g.anti_score)}</strong></span>
                        <span>Global <strong className="text-fg">{Math.round(g.global_score)}</strong></span>
                        <button className="icon-btn" onClick={() => toggle(g, !g.favorite)} aria-pressed={g.favorite}
                          aria-label={g.favorite ? "Retirer des favoris" : "Ajouter aux favoris"}>
                          <Star className={g.favorite ? "h-4 w-4 fill-star text-star" : "h-4 w-4"} aria-hidden />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
          </div>
          {hist.data && hist.data.length >= limit && limit < 50 && (
            <div className="flex justify-center"><button className="btn-ghost" onClick={() => setLimit(limit + 10)}>Afficher plus</button></div>
          )}
        </>
      )}
    </div>
  );
}
