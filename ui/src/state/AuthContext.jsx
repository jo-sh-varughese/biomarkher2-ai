/* ============================================================================
   Authentication.

   Two worlds, decided once at start-up by asking the backend for its auth
   configuration (lib/auth.js):

   - SERVER: the Python backend is running. Accounts, passwords, sessions,
     roles and the audit trail all live on the server (app/auth.py). The
     session is an HttpOnly cookie this code never sees; what it keeps is the
     signed-in user's profile and permissions, and the CSRF token that has to
     accompany every change. The server is the control -- anything hidden
     here for a role is also refused there.

   - DEMO: no backend (the static Netlify build). The original browser-only
     sign-in survives for exactly this case: a demo account compiled into the
     bundle, and "accounts" kept in this browser's localStorage. NONE OF THAT
     IS AUTHENTICATION -- it gates nothing, and every demo screen says so.
     Passwords typed into it are still salted and hashed (PBKDF2) before
     being stored, as harm reduction: people reuse passwords.
   ==========================================================================*/

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import * as authApi from "../lib/auth.js";
import { setCsrfToken } from "../lib/api.js";
import { DEMO_PERMISSIONS, resetDemoAdmin } from "../lib/adminApi.js";

export const DEMO_ACCOUNT = {
  email: "pathologist@gmck.edu.in",
  password: "her2demo",
  name: "Dr. Anita Menon",
  // Job title and department are looked up at render so they follow the
  // language; the person's name is not translated.
  roleKey: "demo.role",
  deptKey: "demo.department",
  registration: "TC-MC-24817",
  // An administrator in the demo so the admin console can be shown; on a
  // real server, roles come from the account database.
  role: "admin",
};

/* Avatar tints. A colour is the most personalisation this portal needs --
   initials on a chosen colour identify a reviewer in a case log as well as a
   photo would, without storing an image of anyone. */
export const AVATAR_COLORS = [
  { id: "violet", from: "#8a7cf1", to: "#4c37bf" },
  { id: "teal", from: "#2dd4bf", to: "#0f766e" },
  { id: "amber", from: "#fbbf24", to: "#b45309" },
  { id: "rose", from: "#fb7185", to: "#be123c" },
  { id: "sky", from: "#4cc9f0", to: "#1d4ed8" },
  { id: "lime", from: "#a3e635", to: "#4d7c0f" },
];

export const avatarStyle = (id) => {
  const c = AVATAR_COLORS.find((x) => x.id === id) ?? AVATAR_COLORS[0];
  return { background: `linear-gradient(145deg, ${c.from}, ${c.to})` };
};

/** Roles offered at demo sign-up. Stored as keys so they follow the language. */
export const ROLE_KEYS = [
  "signup.roles.consultant",
  "signup.roles.seniorResident",
  "signup.roles.juniorResident",
  "signup.roles.technician",
];

/** A person's job title as shown under their name: the free-text title a
    server account carries, or the translated demo title. */
export function jobTitle(user, t) {
  if (!user) return "";
  if (user.title) return user.title;
  if (user.roleKey) return t(user.roleKey);
  return user.role ? t(`roles.${user.role}`) : "";
}

const SESSION_KEY = "bmh2.session.v1";
const ACCOUNTS_KEY = "bmh2.accounts.v1";
const AuthContext = createContext(null);

/* ------------------------------------------------------------- hashing --- */

const PBKDF2_ITERATIONS = 150000;

const toHex = (buffer) =>
  [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");

/* crypto.subtle exists only in a secure context. localhost and the deployed
   HTTPS site both qualify; if it is somehow missing the sign-up is refused
   rather than silently downgraded to storing the password as typed. */
function assertCrypto() {
  if (!globalThis.crypto?.subtle) {
    const err = new Error("Secure hashing unavailable");
    err.i18nKey = "signup.noCrypto";
    throw err;
  }
}

async function hashPassword(password, saltHex) {
  assertCrypto();
  const salt = saltHex
    ? Uint8Array.from(saltHex.match(/.{2}/g).map((b) => parseInt(b, 16)))
    : crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"],
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    key,
    256,
  );
  return { hash: toHex(bits), salt: toHex(salt) };
}

/* Compares without returning early on the first differing byte. */
function safeEqual(a = "", b = "") {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

/* ------------------------------------------------------------- storage --- */

function readAccounts() {
  try {
    const stored = JSON.parse(localStorage.getItem(ACCOUNTS_KEY) || "[]");
    return Array.isArray(stored) ? stored : [];
  } catch {
    return [];
  }
}

function writeAccounts(accounts) {
  try {
    localStorage.setItem(ACCOUNTS_KEY, JSON.stringify(accounts));
    return true;
  } catch {
    return false;
  }
}

const fail = (key) => {
  const err = new Error(key);
  err.i18nKey = key;
  return err;
};

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/* A demo session gets the permissions its role would have on a server, so
   the portal's role-aware screens behave the same way in both worlds. */
function withDemoPermissions(profile) {
  const role = profile.role ?? "pathologist";
  return { ...profile, role, permissions: DEMO_PERMISSIONS[role] };
}

/* A server session, in the shape the rest of the portal reads. */
function fromServer(payload) {
  return {
    ...payload.user,
    server: true,
    demo: false,
    permissions: payload.permissions,
    signedInAt: payload.session?.created_at,
    sessionId: payload.session?.id,
  };
}

/* --------------------------------------------------------------- provider --- */

export function AuthProvider({ children }) {
  const [mode, setMode] = useState(null); // "server" | "demo"
  const [config, setConfig] = useState(null);
  const [user, setUser] = useState(null);
  const [extras, setExtras] = useState({ announcement: "", pendingRequests: 0 });
  const [ready, setReady] = useState(false);
  const [expired, setExpired] = useState(false);
  const modeRef = useRef(null);
  const userRef = useRef(null);
  userRef.current = user;

  const applyServer = useCallback((payload) => {
    setCsrfToken(payload.csrf);
    setUser(fromServer(payload));
    setExtras({ announcement: payload.announcement || "", pendingRequests: payload.pending_requests || 0 });
    setExpired(false);
    return payload;
  }, []);

  const clearServer = useCallback(() => {
    setCsrfToken(null);
    setUser(null);
    setExtras({ announcement: "", pendingRequests: 0 });
  }, []);

  /* ---------------------------------------------------------- start-up --- */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let cfg;
      try {
        cfg = await authApi.config();
      } catch {
        cfg = { mode: "demo" };
      }
      if (cancelled) return;
      modeRef.current = cfg.mode;
      setMode(cfg.mode);
      setConfig(cfg);
      if (cfg.mode === "server") {
        try {
          // {"user": null} means nobody is signed in on this browser.
          const payload = await authApi.me();
          if (!cancelled && payload.user) applyServer(payload);
        } catch {
          /* The server answered with an error; stay signed out. */
        }
      } else {
        try {
          const stored = sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(SESSION_KEY);
          if (stored) setUser(withDemoPermissions(JSON.parse(stored)));
        } catch {
          /* Blocked site data just means no restored session. */
        }
      }
      if (!cancelled) setReady(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [applyServer]);

  const refreshConfig = useCallback(async () => {
    const cfg = await authApi.config();
    setConfig(cfg);
    return cfg;
  }, []);

  /* A server session can end without this page doing anything: the idle
     timeout, an administrator disabling the account or ending its sessions.
     The first request that finds out raises an event; the page then drops
     back to sign-in and says why, instead of failing one call at a time. */
  useEffect(() => {
    const onGone = () => {
      if (modeRef.current !== "server") return;
      if (userRef.current) setExpired(true);
      setUser(null);
      setCsrfToken(null);
    };
    const onPasswordRequired = () =>
      setUser((current) => (current ? { ...current, must_change_password: true } : current));
    window.addEventListener("bmh2:unauthenticated", onGone);
    window.addEventListener("bmh2:password-change-required", onPasswordRequired);
    return () => {
      window.removeEventListener("bmh2:unauthenticated", onGone);
      window.removeEventListener("bmh2:password-change-required", onPasswordRequired);
    };
  }, []);

  /* Re-checks the session when the tab comes back into view and every few
     minutes while it is open, so an expired session is noticed before the
     pathologist types a long note into a form that can no longer be saved. */
  useEffect(() => {
    if (mode !== "server" || !user) return undefined;
    const check = () => {
      if (document.visibilityState !== "visible") return;
      authApi
        .me()
        .then((payload) => {
          if (payload.user) applyServer(payload);
          else window.dispatchEvent(new CustomEvent("bmh2:unauthenticated"));
        })
        .catch(() => {
          /* Unreachable for a moment; the next check will tell. */
        });
    };
    const timer = setInterval(check, 4 * 60 * 1000);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
    };
  }, [mode, user, applyServer]);

  /* ----------------------------------------------------------- demo --- */
  const startDemoSession = useCallback((profile, remember) => {
    const session = { ...profile, signedInAt: new Date().toISOString() };
    try {
      const store = remember ? localStorage : sessionStorage;
      store.setItem(SESSION_KEY, JSON.stringify(session));
    } catch {
      /* Not fatal: the session simply does not survive a reload. */
    }
    const next = withDemoPermissions(session);
    setUser(next);
    return next;
  }, []);

  const persistDemoSession = useCallback((session) => {
    try {
      const store = localStorage.getItem(SESSION_KEY) ? localStorage : sessionStorage;
      const { permissions: _p, ...storable } = session;
      store.setItem(SESSION_KEY, JSON.stringify(storable));
    } catch {
      /* ignore */
    }
  }, []);

  /* ------------------------------------------------------------ actions --- */
  const signIn = useCallback(
    async ({ email, password, remember }) => {
      if (modeRef.current === "server") {
        return fromServer(applyServer(await authApi.login({ email, password, remember })));
      }
      // A short pause so the button's busy state is legible rather than a flash.
      await pause(520);
      const address = email.trim().toLowerCase();
      if (address === DEMO_ACCOUNT.email && password === DEMO_ACCOUNT.password) {
        const { password: _pw, ...profile } = DEMO_ACCOUNT;
        // Flagged so the profile page can say plainly which parts of this
        // account it is able to change and which are fixed in the bundle.
        return startDemoSession({ ...profile, demo: true }, remember);
      }
      const account = readAccounts().find((a) => a.email === address);
      if (account) {
        const { hash } = await hashPassword(password, account.salt);
        if (safeEqual(hash, account.hash)) {
          const { hash: _h, salt: _s, ...profile } = account;
          return startDemoSession(profile, remember);
        }
      }
      throw fail("login.badCredentials");
    },
    [applyServer, startDemoSession],
  );

  const signUp = useCallback(
    async ({ name, email, registration, roleKey, password }) => {
      await pause(620);
      const address = email.trim().toLowerCase();
      if (address === DEMO_ACCOUNT.email) throw fail("signup.emailIsDemo");
      const accounts = readAccounts();
      if (accounts.some((a) => a.email === address)) throw fail("signup.emailTaken");
      const { hash, salt } = await hashPassword(password);
      const account = {
        email: address,
        name: name.trim(),
        registration: registration.trim().toUpperCase(),
        roleKey,
        deptKey: "demo.department",
        role: "pathologist",
        hash,
        salt,
        createdAt: new Date().toISOString(),
      };
      if (!writeAccounts([...accounts, account])) throw fail("signup.storageBlocked");
      const { hash: _h, salt: _s, ...profile } = account;
      // Straight into the portal: there is no email to verify.
      return startDemoSession(profile, true);
    },
    [startDemoSession],
  );

  const requestAccess = useCallback((form) => authApi.requestAccess(form), []);

  const completeSetup = useCallback(
    async (body) => {
      const payload = applyServer(await authApi.setup(body));
      refreshConfig().catch(() => {});
      return fromServer(payload);
    },
    [applyServer, refreshConfig],
  );

  const acceptLink = useCallback(
    async (token, password) => fromServer(applyServer(await authApi.acceptLink(token, password))),
    [applyServer],
  );

  const updateProfile = useCallback(
    async (patch) => {
      if (modeRef.current === "server") {
        const allowed = ["name", "registration", "title", "accent"];
        const body = Object.fromEntries(Object.entries(patch).filter(([k]) => allowed.includes(k)));
        return fromServer(applyServer(await authApi.updateProfile(body)));
      }
      await pause(380);
      let next = null;
      setUser((current) => {
        if (!current) return current;
        next = { ...current, ...patch };
        persistDemoSession(next);
        // Registered demo accounts are the record; the built-in demo account
        // has none, so its edits live only in the session.
        if (!current.demo) {
          const accounts = readAccounts();
          const i = accounts.findIndex((a) => a.email === current.email);
          if (i !== -1) {
            const { demo: _d, signedInAt: _s, permissions: _p, ...storable } = next;
            accounts[i] = { ...accounts[i], ...storable };
            writeAccounts(accounts);
          }
        }
        return next;
      });
      return next;
    },
    [applyServer, persistDemoSession],
  );

  const changePassword = useCallback(
    async ({ current, next }) => {
      if (modeRef.current === "server") {
        return fromServer(applyServer(await authApi.changePassword(current, next)));
      }
      await pause(520);
      const session = JSON.parse(
        localStorage.getItem(SESSION_KEY) || sessionStorage.getItem(SESSION_KEY) || "null",
      );
      if (!session) throw fail("login.badCredentials");
      if (session.demo) throw fail("profile.demoNoPassword");
      const accounts = readAccounts();
      const i = accounts.findIndex((a) => a.email === session.email);
      if (i === -1) throw fail("profile.noAccount");
      const check = await hashPassword(current, accounts[i].salt);
      if (!safeEqual(check.hash, accounts[i].hash)) throw fail("profile.wrongCurrent");
      const { hash, salt } = await hashPassword(next);
      accounts[i] = { ...accounts[i], hash, salt, passwordChangedAt: new Date().toISOString() };
      if (!writeAccounts(accounts)) throw fail("signup.storageBlocked");
      return true;
    },
    [applyServer],
  );

  const refresh = useCallback(async () => {
    if (modeRef.current !== "server") return null;
    try {
      const payload = await authApi.me();
      if (!payload.user) {
        window.dispatchEvent(new CustomEvent("bmh2:unauthenticated"));
        return null;
      }
      return fromServer(applyServer(payload));
    } catch {
      return null;
    }
  }, [applyServer]);

  const signOut = useCallback(async () => {
    if (modeRef.current === "server") {
      try {
        await authApi.logout();
      } catch {
        /* Already signed out on the server; finish here regardless. */
      }
      clearServer();
      setExpired(false);
      return;
    }
    try {
      sessionStorage.removeItem(SESSION_KEY);
      localStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
    resetDemoAdmin();
    setUser(null);
  }, [clearServer]);

  const can = useCallback((permission) => Boolean(user?.permissions?.includes(permission)), [user]);

  const value = useMemo(
    () => ({
      mode,
      isServer: mode === "server",
      config,
      user,
      ready,
      expired,
      can,
      announcement: extras.announcement,
      pendingRequests: extras.pendingRequests,
      signIn,
      signUp,
      signOut,
      requestAccess,
      completeSetup,
      acceptLink,
      updateProfile,
      changePassword,
      refresh,
      refreshConfig,
      clearExpired: () => setExpired(false),
    }),
    [mode, config, user, ready, expired, can, extras, signIn, signUp, signOut, requestAccess,
      completeSetup, acceptLink, updateProfile, changePassword, refresh, refreshConfig],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/* ------------------------------------------------------------ validation --- */

/* Returns a map of field -> i18n key, empty when the form is good. Used by the
   demo sign-up page; a server account's rules come from the server. */
export function validateSignup({ name, email, registration, password, confirm, accepted }) {
  const errors = {};
  if (name.trim().length < 3) errors.name = "signup.errName";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email.trim())) errors.email = "signup.errEmail";
  if (registration.trim().length < 4) errors.registration = "signup.errRegistration";
  if (password.length < 8 || !/[a-zA-Z]/.test(password) || !/\d/.test(password)) {
    errors.password = "signup.errPassword";
  }
  if (confirm !== password) errors.confirm = "signup.errConfirm";
  if (!accepted) errors.accepted = "signup.errTerms";
  return errors;
}

/** 0-4, for the strength meter. Length first, then variety. */
export function passwordStrength(password) {
  if (!password) return 0;
  let score = 0;
  if (password.length >= 8) score += 1;
  if (password.length >= 12) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password) && /[^\w\s]/.test(password)) score += 1;
  return Math.min(4, score);
}

/** A random passphrase-strength password for an administrator to hand out:
    no ambiguous characters (0/O, 1/l/I), readable over the phone. */
export function generatePassword(length = 16) {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";
  // Rejection sampling: bytes above the largest multiple of the alphabet
  // size are dropped, so no character is likelier than another.
  const limit = 256 - (256 % alphabet.length);
  const chars = [];
  while (chars.length < length) {
    for (const byte of crypto.getRandomValues(new Uint8Array(length * 2))) {
      if (byte < limit) chars.push(alphabet[byte % alphabet.length]);
      if (chars.length === length) break;
    }
  }
  // Groups of four with dashes: easier to read aloud and to type.
  return chars.join("").match(/.{1,4}/g).join("-");
}
