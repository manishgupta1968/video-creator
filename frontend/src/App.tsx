import { useEffect, useState } from "react";
import Start from "./components/Start";
import Workspace from "./components/Workspace";
import { SpotlightHost } from "./ui";

function useHashRoute(): [string, (h: string) => void] {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const f = () => setHash(location.hash);
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return [hash, (h) => { location.hash = h; }];
}

export function useTheme(): [string, (t: string) => void] {
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem("vg-theme") || "system"; } catch { return "system"; } });
  useEffect(() => {
    const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("vg-theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return [theme, setTheme];
}

export default function App() {
  const [hash, go] = useHashRoute();
  useTheme();
  const m = hash.match(/^#\/p\/(.+)$/);
  return (
    <>
      {m ? <Workspace pid={decodeURIComponent(m[1])} onHome={() => go("")} /> : <Start onOpen={(id) => go(`#/p/${encodeURIComponent(id)}`)} />}
      <SpotlightHost />
    </>
  );
}
