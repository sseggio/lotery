const dateFmt = new Intl.DateTimeFormat("fr-BE", { weekday: "short", day: "numeric", month: "long", year: "numeric" });
const shortFmt = new Intl.DateTimeFormat("fr-BE", { day: "numeric", month: "short" });
const dtFmt = new Intl.DateTimeFormat("fr-BE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export const fmtDate = (iso?: string | null) => (iso ? dateFmt.format(new Date(iso + (iso.length === 10 ? "T12:00:00" : ""))) : "—");
export const fmtShort = (iso?: string | null) => (iso ? shortFmt.format(new Date(iso + (iso.length === 10 ? "T12:00:00" : ""))) : "—");
export const fmtDateTime = (iso?: string | null) => (iso ? dtFmt.format(new Date(iso)) : "—");

export function fmtRelative(iso?: string | null): string {
  if (!iso) return "jamais";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "à l'instant";
  if (diff < 3600) return `il y a ${Math.round(diff / 60)} min`;
  if (diff < 86400) return `il y a ${Math.round(diff / 3600)} h`;
  return `il y a ${Math.round(diff / 86400)} j`;
}

export const fmtInt = (n: number) => new Intl.NumberFormat("fr-BE").format(n);
export const fmtEur = (n: number) => new Intl.NumberFormat("fr-BE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(n);
export const fmtPct = (n: number, d = 1) => `${n.toFixed(d).replace(".", ",")} %`;
export const fmtNum = (n: number, d = 2) => n.toFixed(d).replace(".", ",");
export const fmtP = (p: number) => (p < 0.001 ? "< 0,001" : p.toFixed(3).replace(".", ","));
