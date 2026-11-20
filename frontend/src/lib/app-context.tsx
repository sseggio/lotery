import { createContext, ReactNode, useContext, useEffect, useMemo } from "react";
import { api, GameInfo, GameKey, StrategyInfo } from "./api";
import { useAsync, useLocalStorage } from "./hooks";

type Theme = "system" | "light" | "dark";

interface AppCtx {
  game: GameKey;
  setGame: (g: GameKey) => void;
  info: GameInfo | undefined;
  games: GameInfo[];
  strategies: StrategyInfo[];
  balance: number;
  setBalance: (b: number) => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
  /** Incremented after a successful sync so pages refetch. */
  dataVersion: number;
  bumpData: () => void;
}

const Ctx = createContext<AppCtx | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [game, setGame] = useLocalStorage<GameKey>("lotery.game", "lotto");
  const [balance, setBalance] = useLocalStorage<number>("lotery.balance", 0.5);
  const [theme, setTheme] = useLocalStorage<Theme>("lotery.theme", "system");
  const [dataVersion, setDataVersion] = useLocalStorage<number>("lotery.v", 0);
  const meta = useAsync(() => api.games(), []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
  }, [theme]);

  const value = useMemo<AppCtx>(() => ({
    game: game === "euromillions" ? "euromillions" : "lotto",
    setGame,
    info: meta.data?.games.find((g) => g.key === game),
    games: meta.data?.games ?? [],
    strategies: meta.data?.strategies ?? [],
    balance: Math.min(1, Math.max(0, Number(balance) || 0.5)),
    setBalance,
    theme,
    setTheme,
    dataVersion,
    bumpData: () => setDataVersion(dataVersion + 1),
  }), [game, setGame, meta.data, balance, setBalance, theme, setTheme, dataVersion, setDataVersion]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp outside provider");
  return c;
}
