import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
// Fonts are bundled from npm (@fontsource): nothing loads from the network.
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-sans-condensed/500.css";
import "@fontsource/ibm-plex-sans-condensed/600.css";
import "./index.css";
import App from "./App";
import Tablet from "./tablet/Tablet";

// ?view=tablet: the live-simulation view for the tablet (3D twin + anomaly injection)
const TABLET = new URLSearchParams(window.location.search).get("view") === "tablet";

const client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      {TABLET ? <Tablet /> : <App />}
    </QueryClientProvider>
  </StrictMode>,
);
