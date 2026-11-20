import { CheckCircle2, CircleDashed, ExternalLink, XCircle } from "lucide-react";
import { useState } from "react";
import { Balls, Card, ErrorState, Notice, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { useApp } from "../lib/app-context";
import { fmtDate, fmtDateTime, fmtInt } from "../lib/format";
import { useAsync } from "../lib/hooks";

const PAGE = 25;

export default function Draws() {
  const { game, info, dataVersion } = useApp();
  const [page, setPage] = useState(0);
  const draws = useAsync(() => api.draws(game, PAGE, page * PAGE), [game, page, dataVersion]);
  const sum = useAsync(() => api.summary(game), [game, dataVersion]);
  const pages = draws.data ? Math.ceil(draws.data.total / PAGE) : 0;
  const s = sum.data;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Tirages officiels</h1>
        <p className="mt-1 text-sm text-muted">{draws.data ? `${fmtInt(draws.data.total)} tirages ${info?.label ?? ""} enregistrés` : "Chargement…"}</p>
      </div>

      <Notice>
        <p><strong>Sources :</strong> API de résultats utilisée par le site officiel de la Loterie Nationale (résultats définitifs, gagnants et montants par rang).
          {game === "lotto" && <> Chaque tirage Lotto est en outre comparé au fichier de statistiques publié mensuellement sur{" "}
            <a className="inline-flex items-center gap-1 font-medium text-accent underline underline-offset-2" href="https://www.loterie-nationale.be/nos-jeux/lotto/resultats-tirage/statistiques" target="_blank" rel="noopener noreferrer">
              loterie-nationale.be<ExternalLink className="h-3 w-3" aria-hidden /></a>.</>}
          {" "}Aucun résultat n'est saisi ou estimé manuellement.</p>
        {s?.sync.xlsx_check && <p className="mt-1 text-muted">Dernière vérification croisée : {fmtDateTime(s.sync.xlsx_check.at)} — {s.sync.xlsx_check.message}</p>}
        {s?.sync.last_attempt && <p className="mt-1 text-muted">Dernière synchronisation : {fmtDateTime(s.sync.last_attempt.at)} — {s.sync.last_attempt.message}</p>}
      </Notice>

      {draws.error && <ErrorState message={draws.error} onRetry={draws.reload} />}
      <Card className="overflow-hidden">
        {!draws.data ? <div className="p-5"><Skeleton className="h-96" /></div> : (
          <ul className="divide-y divide-border">
            {draws.data.draws.map((d) => (
              <li key={d.draw_id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-6 sm:px-5">
                <div className="w-48 shrink-0">
                  <div className="text-sm font-medium">{fmtDate(d.date)}</div>
                  <div className="text-xs text-muted">Tirage n° {d.draw_id}</div>
                </div>
                <div className="flex-1"><Balls numbers={d.numbers} extras={d.extras} bonus={d.bonus} size="sm" /></div>
                <div className="text-xs">
                  {d.verified === true && <span className="inline-flex items-center gap-1 text-good"><CheckCircle2 className="h-4 w-4" aria-hidden />Vérifié (2 sources)</span>}
                  {d.verified === false && <span className="inline-flex items-center gap-1 text-bad"><XCircle className="h-4 w-4" aria-hidden />Divergence</span>}
                  {d.verified == null && <span className="inline-flex items-center gap-1 text-muted"><CircleDashed className="h-4 w-4" aria-hidden />API officielle</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {pages > 1 && (
        <nav className="flex items-center justify-center gap-3" aria-label="Pagination">
          <button className="btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>Précédent</button>
          <span className="text-sm text-muted tabular">Page {page + 1} / {pages}</span>
          <button className="btn-ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Suivant</button>
        </nav>
      )}
    </div>
  );
}
