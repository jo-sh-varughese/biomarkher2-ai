import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import AppShell from "./components/AppShell.jsx";
import Login from "./pages/Login.jsx";
import Signup from "./pages/Signup.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Analysis from "./pages/Analysis.jsx";
import Cases from "./pages/Cases.jsx";
import ModelCard from "./pages/ModelCard.jsx";
import Method from "./pages/Method.jsx";
import Profile from "./pages/Profile.jsx";
import { useAuth } from "./state/AuthContext.jsx";
import { PortalProvider } from "./state/PortalContext.jsx";

/* The landing page pulls in three.js, gsap and lenis. Splitting it out keeps
   all of that off the critical path for a pathologist who signs in and goes
   straight to a case. */
const Landing = lazy(() => import("./pages/Landing.tsx"));

function Protected({ children }) {
  const { user, ready } = useAuth();
  const location = useLocation();

  // Until the stored session has been read, render nothing rather than
  // flashing the login screen at an already-signed-in user.
  if (!ready) return <div style={{ minHeight: "100dvh", background: "var(--bg)" }} />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <PortalProvider>{children}</PortalProvider>;
}

export default function App() {
  return (
    <Routes>
      {/* The landing page is public and stays at the root. The portal lives
          under its own paths, so a signed-in visitor can still reach the
          marketing page instead of being bounced away from it. */}
      <Route
        path="/"
        element={
          <Suspense fallback={<div style={{ minHeight: "100dvh", background: "#F5F5F5" }} />}>
            <Landing />
          </Suspense>
        }
      />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route
        element={
          <Protected>
            <AppShell />
          </Protected>
        }
      >
        <Route path="/overview" element={<Dashboard />} />
        <Route path="/analysis" element={<Analysis />} />
        <Route path="/cases" element={<Cases />} />
        <Route path="/model" element={<ModelCard />} />
        <Route path="/method" element={<Method />} />
        <Route path="/profile" element={<Profile />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
