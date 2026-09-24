import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { AuthProvider } from "./state/AuthContext.jsx";
import { ThemeProvider } from "./state/ThemeContext.jsx";
import { ToastProvider } from "./state/ToastContext.jsx";
import { I18nProvider } from "./i18n/I18nContext.jsx";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/app.css";
import "./styles/halo.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ThemeProvider>
      <I18nProvider>
        <ToastProvider>
          <AuthProvider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </AuthProvider>
        </ToastProvider>
      </I18nProvider>
    </ThemeProvider>
  </StrictMode>,
);
