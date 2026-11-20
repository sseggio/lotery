import { useApp } from "../lib/app-context";
import { cx } from "./ui";

const PRESETS = [
  { value: 1, label: "Statistiques" },
  { value: 0.5, label: "Équilibre" },
  { value: 0, label: "Anti-partage" },
];

/** Weight between historical statistics (1) and anti-sharing (0). */
export function BalanceControl() {
  const { balance, setBalance } = useApp();
  return (
    <div className="flex w-full flex-col gap-2 sm:w-auto">
      <div role="radiogroup" aria-label="Priorité de génération" className="inline-flex rounded-xl border border-border bg-surface-2 p-1">
        {PRESETS.map((p) => (
          <button key={p.label} role="radio" aria-checked={Math.abs(balance - p.value) < 0.01}
            onClick={() => setBalance(p.value)}
            className={cx("min-h-[40px] flex-1 whitespace-nowrap rounded-lg px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
              Math.abs(balance - p.value) < 0.01 ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg")}>
            {p.label}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-3 text-xs text-muted">
        <span className="whitespace-nowrap tabular">Anti-partage {100 - Math.round(balance * 100)} %</span>
        <input type="range" min={0} max={100} step={5} value={Math.round(balance * 100)}
          onChange={(e) => setBalance(Number(e.target.value) / 100)}
          className="h-2 w-full cursor-pointer accent-[rgb(var(--accent))]"
          aria-label="Poids des statistiques historiques (en %)" />
        <span className="whitespace-nowrap tabular">{Math.round(balance * 100)} % Statistiques</span>
      </label>
    </div>
  );
}
