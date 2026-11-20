import "@fontsource-variable/inter";
import "./index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AppProvider } from "./lib/app-context";
import Algorithms from "./pages/Algorithms";
import Draws from "./pages/Draws";
import History from "./pages/History";
import Home from "./pages/Home";
import Stats from "./pages/Stats";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="statistiques" element={<Stats />} />
            <Route path="algorithmes" element={<Algorithms />} />
            <Route path="historique" element={<History />} />
            <Route path="tirages" element={<Draws />} />
            <Route path="*" element={<Home />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProvider>
  </StrictMode>,
);
