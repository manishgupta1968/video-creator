import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ToastHost } from "./lib";
import "./styles.css";
import { TipProvider } from "./ui";

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <TipProvider>
        <ToastHost>
          <App />
        </ToastHost>
      </TipProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
