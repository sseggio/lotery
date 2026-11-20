import { AlertTriangle, Info, RefreshCw } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

export function Card({ children, className, ...rest }: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("card", className)} {...rest}>{children}</div>;
}

export function SectionTitle({ title, subtitle, action, id }: { title: string; subtitle?: ReactNode; action?: ReactNode; id?: string }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 id={id} className="text-lg font-semibold tracking-tight">{title}</h2>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Ball({ n, kind = "main", size = "md", delay = 0, highlight = false }: {
  n: number; kind?: "main" | "star" | "bonus"; size?: "sm" | "md" | "lg"; delay?: number; highlight?: boolean;
}) {
  const dims = { sm: "h-8 w-8 text-[13px]", md: "h-10 w-10 text-[15px] sm:h-11 sm:w-11", lg: "h-12 w-12 text-lg sm:h-14 sm:w-14 sm:text-xl" }[size];
  const style = {
    main: "bg-gradient-to-b from-surface to-surface-2 text-fg ring-1 ring-inset ring-border shadow-[inset_0_-2px_0_rgb(0_0_0/0.06),0_1px_2px_rgb(0_0_0/0.08)]",
    star: "bg-star/15 text-fg ring-1 ring-inset ring-star/50",
    bonus: "bg-transparent text-muted ring-2 ring-dashed ring-border border-2 border-dashed border-border",
  }[kind];
  return (
    <span
      className={cx("inline-flex shrink-0 select-all items-center justify-center rounded-full font-semibold tabular animate-pop",
        dims, style, highlight && "ring-2 ring-accent")}
      style={{ animationDelay: `${delay}ms` }}
    >
      {n}
    </span>
  );
}

export function Balls({ numbers, extras, bonus, size = "md", label }: {
  numbers: number[]; extras?: number[] | null; bonus?: number | null; size?: "sm" | "md" | "lg"; label?: string;
}) {
  const aria = `${label ? label + " : " : ""}${numbers.join(", ")}${extras?.length ? " ; étoiles " + extras.join(", ") : ""}${bonus ? " ; bonus " + bonus : ""}`;
  return (
    <div className="flex flex-wrap items-center gap-1.5 sm:gap-2" role="group" aria-label={aria}>
      {numbers.map((n, i) => <Ball key={`m${n}`} n={n} size={size} delay={i * 35} />)}
      {extras && extras.length > 0 && <span className="mx-0.5 h-6 w-px bg-border" aria-hidden />}
      {extras?.map((n, i) => <Ball key={`e${n}`} n={n} kind="star" size={size} delay={(numbers.length + i) * 35} />)}
      {bonus != null && (
        <>
          <span className="ml-1 text-xs text-muted" aria-hidden>bonus</span>
          <Ball n={bonus} kind="bonus" size={size} delay={numbers.length * 35} />
        </>
      )}
    </div>
  );
}

export function ScoreBar({ label, value, tone = "accent", hint }: { label: string; value: number; tone?: "accent" | "good" | "star"; hint?: string }) {
  const bar = { accent: "bg-accent", good: "bg-good", star: "bg-star" }[tone];
  return (
    <div title={hint}>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className="font-semibold tabular">{Math.round(value)}<span className="font-normal text-muted">/100</span></span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-2" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)} aria-label={label}>
        <div className={cx("h-full rounded-full transition-[width] duration-500", bar)} style={{ width: `${Math.max(2, value)}%` }} />
      </div>
    </div>
  );
}

export function Kpi({ label, value, sub, icon }: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode }) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <span className="label">{label}</span>
        {icon && <span className="text-muted" aria-hidden>{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-xl bg-surface-2", className)} aria-hidden />;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-2xl border border-bad/30 bg-bad/5 p-4 text-sm sm:flex-row sm:items-center">
      <AlertTriangle className="h-5 w-5 shrink-0 text-bad" aria-hidden />
      <p className="flex-1">{message}</p>
      {onRetry && <button className="btn-ghost" onClick={onRetry}><RefreshCw className="h-4 w-4" aria-hidden />Réessayer</button>}
    </div>
  );
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" }) {
  return (
    <div className={cx("flex gap-3 rounded-2xl border p-4 text-sm leading-relaxed",
      tone === "info" ? "border-accent/25 bg-accent/5" : "border-warn/30 bg-warn/5")}>
      <Info className={cx("mt-0.5 h-4 w-4 shrink-0", tone === "info" ? "text-accent" : "text-warn")} aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange, label, size = "md" }: {
  options: { value: T; label: string }[]; value: T; onChange: (v: T) => void; label: string; size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-xl border border-border bg-surface-2 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "whitespace-nowrap rounded-lg font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
            size === "sm" ? "min-h-[36px] px-3 text-xs" : "min-h-[40px] px-3.5 text-sm",
            value === o.value ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Delta({ value, suffix = "" }: { value: number; suffix?: string }) {
  const c = value > 0 ? "text-good" : value < 0 ? "text-bad" : "text-muted";
  return <span className={cx("tabular font-medium", c)}>{value > 0 ? "+" : ""}{value.toFixed(1).replace(".", ",")}{suffix}</span>;
}

/** Re-render periodically so relative times stay fresh. */
export function useNow(ms = 30000) {
  const [, set] = useState(0);
  useEffect(() => { const t = setInterval(() => set((x) => x + 1), ms); return () => clearInterval(t); }, [ms]);
}
