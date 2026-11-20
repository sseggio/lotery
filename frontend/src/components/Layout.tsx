import { BarChart3, Database, FlaskConical, History, LayoutDashboard, Monitor, Moon, RefreshCw, Sun } from "lucide-react";
import { ReactNode, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useApp } from "../lib/app-context";
import { cx, Segmented } from "./ui";

const NAV = [
  { to: "/", label: "Tableau de bord", short: "Accueil", icon: LayoutDashboard },
  { to: "/statistiques", label: "Statistiques", short: "Stats", icon: BarChart3 },
  { to: "/algorithmes", label: "Algorithmes", short: "Algos", icon: FlaskConical },
  { to: "/historique", label: "Historique & favoris", short: "Historique", icon: History },
  { to: "/tirages", label: "Tirages officiels", short: "Tirages", icon: Database },
];

export function SyncButton({ compact = false, onDone }: { compact?: boolean; onDone?: () => void }) {
  const { game, bumpData } = useApp();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  async function run() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.sync(game);
      setMsg({ ok: true, text: r.new_draws ? (r.new_draws > 1 ? `${r.new_draws} nouveaux tirages ajoutés` : "1 nouveau tirage ajouté") : "Déjà à jour" });
      bumpData();
      onDone?.();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof ApiError ? e.message : "Échec de l'actualisation" });
    } finally {
      setBusy(false);
      setTimeout(() => setMsg(null), 6000);
    }
  }

  return (
    <div className="relative">
      <button className={compact ? "icon-btn" : "btn-ghost"} onClick={run} disabled={busy}
        aria-label="Actualiser les tirages" title="Actualiser les tirages">
        <RefreshCw className={cx("h-4 w-4", busy && "animate-spin")} aria-hidden />
        {!compact && <span>{busy ? "Actualisation…" : "Actualiser les tirages"}</span>}
      </button>
      <div aria-live="polite" className="absolute right-0 top-full z-30 mt-2">
        {msg && (
          <div className={cx("w-64 animate-fade rounded-xl border p-3 text-xs shadow-card",
            msg.ok ? "border-good/30 bg-surface text-fg" : "border-bad/30 bg-surface text-bad")}>
            {msg.text}
          </div>
        )}
      </div>
    </div>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useApp();
  const next = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
  const Icon = theme === "system" ? Monitor : theme === "light" ? Sun : Moon;
  const label = { system: "Thème : système", light: "Thème : clair", dark: "Thème : sombre" }[theme];
  return (
    <button className="icon-btn" onClick={() => setTheme(next)} aria-label={`${label} (changer)`} title={label}>
      <Icon className="h-4 w-4" aria-hidden />
    </button>
  );
}

function GameSwitch() {
  const { game, setGame } = useApp();
  return (
    <Segmented label="Jeu" size="sm" value={game} onChange={setGame}
      options={[{ value: "lotto", label: "Lotto" }, { value: "euromillions", label: "EuroMillions" }]} />
  );
}

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="relative inline-flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-fg" aria-hidden>
        <span className="absolute left-[7px] top-[8px] h-3.5 w-3.5 rounded-full bg-current opacity-95" />
        <span className="absolute bottom-[7px] right-[7px] h-2.5 w-2.5 rounded-full bg-current opacity-60" />
      </span>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-tight">Lotery</div>
        <div className="text-[11px] text-muted">Analytics</div>
      </div>
    </div>
  );
}

export function Layout({ children }: { children?: ReactNode }) {
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-surface focus:p-3">
        Aller au contenu
      </a>
      {/* Sidebar (desktop) */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col border-r border-border bg-surface/70 px-3 py-5 backdrop-blur lg:flex">
        <div className="px-2"><Logo /></div>
        <nav className="mt-8 flex flex-col gap-1" aria-label="Navigation principale">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => cx(
                "flex min-h-[40px] items-center gap-3 rounded-xl px-3 text-sm font-medium transition-colors",
                isActive ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface-2 hover:text-fg")}>
              <Icon className="h-4 w-4" aria-hidden />{label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto rounded-xl bg-surface-2 p-3 text-[11px] leading-relaxed text-muted">
          Outil d'analyse statistique indépendant. Aucune méthode ne modifie la probabilité de gagner.
          <br />Jouez avec modération.
        </div>
      </aside>

      <div className="lg:pl-60">
        {/* Top bar */}
        <header className="sticky top-0 z-10 border-b border-border bg-bg/80 backdrop-blur">
          <div className="mx-auto flex h-16 max-w-7xl items-center gap-3 px-4 sm:px-6">
            <div className="lg:hidden"><Logo /></div>
            <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
              <GameSwitch />
              <div className="hidden sm:block"><SyncButton /></div>
              <div className="sm:hidden"><SyncButton compact /></div>
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main id="main" className="mx-auto max-w-7xl px-4 pb-28 pt-6 sm:px-6 lg:pb-12">
          {children ?? <Outlet />}
        </main>
      </div>

      {/* Bottom navigation (mobile / tablet) */}
      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur lg:hidden" aria-label="Navigation principale">
        <div className="mx-auto grid max-w-xl grid-cols-5" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
          {NAV.map(({ to, short, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) => cx("flex min-h-[56px] flex-col items-center justify-center gap-1 text-[11px] font-medium",
                isActive ? "text-accent" : "text-muted")}>
              <Icon className="h-5 w-5" aria-hidden />{short}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
