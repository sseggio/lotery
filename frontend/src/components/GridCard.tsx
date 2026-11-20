import { Check, ChevronDown, Copy, RefreshCw, Star } from "lucide-react";
import { useState } from "react";
import { Grid } from "../lib/api";
import { fmtNum, fmtPct } from "../lib/format";
import { Balls, Card, cx, ScoreBar } from "./ui";

const SLOT_TONES = ["from-indigo-500/15", "from-emerald-500/15", "from-amber-500/15", "from-rose-500/15"];

export function GridCard({ grid, onRegenerate, onFavorite, busy, compact = false }: {
  grid: Grid; onRegenerate?: () => void; onFavorite?: (fav: boolean) => void; busy?: boolean; compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const d = grid.details;
  const pop = d.popularity;

  async function copy() {
    const txt = grid.numbers.join(" - ") + (grid.extras ? `  ★ ${grid.extras.join(" - ")}` : "");
    try { await navigator.clipboard.writeText(txt); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* no clipboard */ }
  }

  return (
    <Card className={cx("relative flex flex-col overflow-hidden transition-opacity", busy && "opacity-60")}>
      <div className={cx("pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b to-transparent", SLOT_TONES[(grid.slot - 1) % 4])} aria-hidden />
      <div className="relative flex items-start justify-between gap-2 p-4 pb-2 sm:p-5 sm:pb-2">
        <div className="min-w-0">
          <div className="label">Grille {grid.slot}</div>
          <h3 className="mt-0.5 truncate text-base font-semibold tracking-tight">{d.strategy_label}</h3>
        </div>
        <div className="-mr-2 -mt-1 flex shrink-0">
          <button className="icon-btn" onClick={copy} aria-label="Copier les numéros" title="Copier">
            {copied ? <Check className="h-4 w-4 text-good" aria-hidden /> : <Copy className="h-4 w-4" aria-hidden />}
          </button>
          {onFavorite && (
            <button className="icon-btn" onClick={() => onFavorite(!grid.favorite)} aria-pressed={grid.favorite}
              aria-label={grid.favorite ? "Retirer des favoris" : "Ajouter aux favoris"} title="Favori">
              <Star className={cx("h-4 w-4", grid.favorite && "fill-star text-star")} aria-hidden />
            </button>
          )}
          {onRegenerate && (
            <button className="icon-btn" onClick={onRegenerate} disabled={busy} aria-label={`Régénérer la grille ${grid.slot}`} title="Régénérer cette grille">
              <RefreshCw className={cx("h-4 w-4", busy && "animate-spin")} aria-hidden />
            </button>
          )}
        </div>
      </div>

      <div className="relative px-4 sm:px-5">
        <Balls key={grid.id} numbers={grid.numbers} extras={grid.extras} size={compact ? "md" : "lg"} label={`Grille ${grid.slot}`} />
      </div>

      <div className="relative mt-4 grid grid-cols-3 gap-3 px-4 sm:gap-4 sm:px-5">
        <ScoreBar label="Statistique" value={grid.stat_score} hint="Adéquation aux tendances historiques (percentile vs grilles aléatoires). N'augmente pas la probabilité de gain." />
        <ScoreBar label="Anti-partage" value={grid.anti_score} tone="good" hint="Estimation : part des grilles aléatoires jugées plus populaires que celle-ci." />
        <ScoreBar label="Global" value={grid.global_score} tone="star" hint="Combinaison des deux scores selon votre réglage." />
      </div>

      <div className="relative mt-4 flex flex-wrap gap-1.5 px-4 sm:px-5">
        <span className="chip" title="Popularité estimée auprès des autres joueurs (1 = grille moyenne)">
          Popularité ×{fmtNum(pop.relative_popularity)}
        </span>
        <span className="chip" title="Part du jackpot conservée en moyenne si cette grille gagne (modèle), comparée à une grille moyenne">
          Gain si jackpot {pop.gain_vs_average_pct >= 0 ? "+" : ""}{fmtPct(pop.gain_vs_average_pct, 0)}
        </span>
        <span className="chip">Σ {d.structure.sum}</span>
        <span className="chip">{d.structure.odd} impairs · {d.structure.even} pairs</span>
      </div>

      <div className="relative mt-auto px-2 pb-2 pt-3">
        <button onClick={() => setOpen(!open)} aria-expanded={open}
          className="flex min-h-[44px] w-full items-center justify-between rounded-xl px-3 text-sm font-medium text-muted hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
          Pourquoi cette grille ?
          <ChevronDown className={cx("h-4 w-4 transition-transform", open && "rotate-180")} aria-hidden />
        </button>
        {open && (
          <div className="animate-fade space-y-3 px-3 pb-3 text-sm">
            <p className="text-muted">{d.strategy_description}</p>
            <ul className="space-y-1.5">
              {d.reasons.map((r) => (
                <li key={r} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden />{r}</li>
              ))}
            </ul>
            <div className="overflow-x-auto">
              <table className="w-full text-xs tabular">
                <caption className="sr-only">Détail par numéro</caption>
                <thead className="text-muted">
                  <tr><th className="py-1 text-left font-medium">N°</th><th className="text-right font-medium">Sorties*</th>
                    <th className="text-right font-medium">Rang fréq.</th><th className="text-right font-medium">Retard</th>
                    <th className="text-right font-medium">Popularité</th></tr>
                </thead>
                <tbody>
                  {d.numbers.map((n) => (
                    <tr key={n.number} className="border-t border-border">
                      <td className="py-1 font-semibold">{n.number}</td><td className="text-right">{n.count}</td>
                      <td className="text-right">{n.freq_rank}</td><td className="text-right">{n.gap}</td>
                      <td className="text-right">×{n.popularity != null ? fmtNum(n.popularity) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-[11px] text-muted">* sur les 104 derniers tirages · poids statistique {Math.round(d.alpha * 100)} % / anti-partage {Math.round((1 - d.alpha) * 100)} %</p>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}
