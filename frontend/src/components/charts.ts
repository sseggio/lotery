import { useEffect, useState } from "react";

export interface ChartColors {
  accent: string; muted: string; grid: string; fg: string; good: string; bad: string; warn: string; star: string; surface: string;
  series: string[];
}

function read(): ChartColors {
  const s = getComputedStyle(document.documentElement);
  const v = (name: string) => `rgb(${s.getPropertyValue(name).trim().split(/\s+/).join(",")})`;
  const dark = s.getPropertyValue("color-scheme").includes("dark");
  return {
    accent: v("--accent"), muted: v("--muted"), grid: v("--chart-grid"), fg: v("--fg"), good: v("--good"),
    bad: v("--bad"), warn: v("--warn"), star: v("--star"), surface: v("--surface"),
    // Categorical palette, distinguishable in both themes.
    series: dark
      ? ["#8b8bff", "#4fd1a5", "#f5b950", "#ff7c9c", "#5cc8ff", "#b89bff"]
      : ["#5b5bd6", "#12a37a", "#c98a0a", "#d6406f", "#1d8fd1", "#8a5cd6"],
  };
}

/** Theme-aware colors for Recharts (SVG attributes cannot use CSS variables). */
export function useChartColors(): ChartColors {
  const [c, setC] = useState<ChartColors>(read);
  useEffect(() => {
    const update = () => setC(read());
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => { mo.disconnect(); mq.removeEventListener("change", update); };
  }, []);
  return c;
}

export const axisProps = (c: ChartColors) => ({
  stroke: c.muted, tick: { fill: c.muted, fontSize: 11 }, tickLine: false, axisLine: { stroke: c.grid },
});
