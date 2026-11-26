import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { getApiBaseUrl } from "./config";
import AuthProvider from "./context/AuthProvider";
// Self-hosted fonts (bundled by Vite, no third-party font requests): Archivo Black headings, Work Sans UI/body.
import "@fontsource/archivo-black/400.css";
import "@fontsource-variable/work-sans/index.css";
import "./index.css";
import { routes } from "./routes";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Missing #root element in index.html.");
}

try {
  // Fail loudly at startup when the build is misconfigured (e.g. production without VITE_API_BASE_URL),
  // instead of failing on the first request with a confusing network error.
  getApiBaseUrl();
} catch (error) {
  const message = error instanceof Error ? error.message : "The application is misconfigured.";
  const alert = document.createElement("p");
  alert.setAttribute("role", "alert");
  alert.textContent = `FindMyThing cannot start: ${message}`; // textContent: never parsed as HTML
  container.replaceChildren(alert);
  throw error;
}

createRoot(container).render(
  <StrictMode>
    <AuthProvider>
      <RouterProvider router={createBrowserRouter(routes)} />
    </AuthProvider>
  </StrictMode>,
);
