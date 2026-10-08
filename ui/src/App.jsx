import { Suspense, lazy } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import AppShell from "./components/AppShell.jsx";
import Login from "./pages/Login.jsx";
import Signup from "./pages/Signup.jsx";
import Setup from "./pages/Setup.jsx";
import ResetPassword from "./pages/ResetPassword.jsx";
import ChangePassword from "./pages/ChangePassword.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Analysis from "./pages/Analysis.jsx";
import Slides from "./pages/Slides.jsx";
import Cases from "./pages/Cases.jsx";
import Review from "./pages/Review.jsx";
import ModelCard from "./pages/ModelCard.jsx";
import Method from "./pages/Method.jsx";
import Profile from "./pages/Profile.jsx";
import { useAuth } from "./state/AuthContext.jsx";
import { PortalProvider } from "./state/PortalContext.jsx";

/* The landing page pulls in three.js, gsap and lenis. Splitting it out keeps
   all of that off the critical path for a pathologist who signs in and goes
   straight to a case. */
const Landing = lazy(() => import("./pages/Landing.tsx"));

/* The admin console is only ever opened by administrators, so it is its own
   chunk too: nobody else downloads it. */
const AdminLayout = lazy(() => import("./pages/admin/AdminLayout.jsx"));
const AdminOverview = lazy(() => import("./pages/admin/Overview.jsx"));
const AdminUsers = lazy(() => import("./pages/admin/Users.jsx"));
const AdminSessions = lazy(() => import("./pages/admin/Sessions.jsx"));
const AdminAudit = lazy(() => import("./pages/admin/Audit.jsx"));
const AdminSettings = lazy(() => import("./pages/admin/Settings.jsx"));
const AdminSystem = lazy(() => import("./pages/admin/System.jsx"));
const AdminLearning = lazy(() => import("./pages/admin/Learning.jsx"));

const blank = <div style={{ minHeight: "100dvh", background: "var(--bg)" }} />;

function Protected({ children }) {
  const { user, ready } = useAuth();
  const location = useLocation();

  // Until the session has been checked, render nothing rather than flashing
  // the login screen at an already-signed-in user.
  if (!ready) return blank;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  // The server refuses everything else until a temporary password has been
  // replaced; sending the person to the one screen that works is kinder
  // than letting every page fail.
  if (user.must_change_password) {
    return <Navigate to="/change-password" replace state={{ from: location.pathname + location.search }} />;
  }
  return <PortalProvider>{children}</PortalProvider>;
}

function AdminPage({ children }) {
  return (
    <Suspense fallback={<div className="skeleton" style={{ height: 420, borderRadius: "var(--r-lg)" }} />}>
      {children}
    </Suspense>
  );
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
      <Route path="/setup" element={<Setup />} />
      <Route path="/reset" element={<ResetPassword />} />
      <Route path="/change-password" element={<ChangePassword />} />
      <Route
        element={
          <Protected>
            <AppShell />
          </Protected>
        }
      >
        <Route path="/overview" element={<Dashboard />} />
        <Route path="/analysis" element={<Analysis />} />
        <Route path="/slides" element={<Slides />} />
        <Route path="/review" element={<Review />} />
        <Route path="/cases" element={<Cases />} />
        <Route path="/model" element={<ModelCard />} />
        <Route path="/method" element={<Method />} />
        <Route path="/profile" element={<Profile />} />
        <Route
          path="/admin"
          element={
            <AdminPage>
              <AdminLayout />
            </AdminPage>
          }
        >
          <Route index element={<AdminPage><AdminOverview /></AdminPage>} />
          <Route path="users" element={<AdminPage><AdminUsers /></AdminPage>} />
          <Route path="users/:userId" element={<AdminPage><AdminUsers /></AdminPage>} />
          <Route path="sessions" element={<AdminPage><AdminSessions /></AdminPage>} />
          <Route path="audit" element={<AdminPage><AdminAudit /></AdminPage>} />
          <Route path="settings" element={<AdminPage><AdminSettings /></AdminPage>} />
          <Route path="system" element={<AdminPage><AdminSystem /></AdminPage>} />
          <Route path="learning" element={<AdminPage><AdminLearning /></AdminPage>} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
