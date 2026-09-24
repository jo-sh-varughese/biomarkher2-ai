/* ============================================================================
   Authentication.

   There is no user table behind this portal, so everything here runs in the
   browser: the hardcoded demo account below, and any account created through
   the sign-up page, which is stored in this browser's localStorage.

   NONE OF THIS IS AUTHENTICATION. It gates nothing -- anyone can read the
   demo credentials out of the bundle, and anyone with the machine can read or
   edit the account store. It exists so the portal can be demonstrated end to
   end, and every screen that touches it says so in plain words. Before this
   goes near a real slide or a real patient, it must be replaced with a
   server-issued session.

   One thing is taken seriously despite that: passwords are never stored in
   plain text. People reuse passwords, so someone signing up here may well
   type one that also opens their hospital email. Salted PBKDF2 means a
   password typed into a demo does not end up sitting in devtools in the
   clear. That is harm reduction for the person, not security for the app --
   the distinction matters and is why the warning above still stands.
   ==========================================================================*/

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export const DEMO_ACCOUNT = {
  email: "pathologist@gmck.edu.in",
  password: "her2demo",
  name: "Dr. Anita Menon",
  // Job title and department are looked up at render so they follow the
  // language; the person's name is not translated.
  roleKey: "demo.role",
  deptKey: "demo.department",
  registration: "TC-MC-24817",
};

/* Avatar tints. A colour is the most personalisation this portal needs --
   an uploaded photo would mean storing an image for an account that has no
   server, and initials on a chosen colour identify a reviewer in a case log
   just as well. */
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

/** Roles offered at sign-up. Stored as keys so they follow the language. */
export const ROLE_KEYS = [
  "signup.roles.consultant",
  "signup.roles.seniorResident",
  "signup.roles.juniorResident",
  "signup.roles.technician",
];

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

/* --------------------------------------------------------------- provider --- */

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(SESSION_KEY);
      if (stored) setUser(JSON.parse(stored));
    } catch {
      /* Blocked site data just means no restored session. */
    }
    setReady(true);
  }, []);

  const startSession = useCallback((profile, remember) => {
    const session = { ...profile, signedInAt: new Date().toISOString() };
    try {
      const store = remember ? localStorage : sessionStorage;
      store.setItem(SESSION_KEY, JSON.stringify(session));
    } catch {
      /* Not fatal: the session simply does not survive a reload. */
    }
    setUser(session);
    return session;
  }, []);

  const signIn = useCallback(
    async ({ email, password, remember }) => {
      // A short pause so the button's busy state is legible rather than a flash.
      await new Promise((resolve) => setTimeout(resolve, 520));
      const address = email.trim().toLowerCase();

      if (address === DEMO_ACCOUNT.email && password === DEMO_ACCOUNT.password) {
        const { password: _pw, ...profile } = DEMO_ACCOUNT;
        // Flagged so the profile page can say plainly which parts of this
        // account it is able to change and which are fixed in the bundle.
        return startSession({ ...profile, demo: true }, remember);
      }

      // Accounts created through sign-up, on this browser.
      const account = readAccounts().find((a) => a.email === address);
      if (account) {
        const { hash } = await hashPassword(password, account.salt);
        if (safeEqual(hash, account.hash)) {
          const { hash: _h, salt: _s, ...profile } = account;
          return startSession(profile, remember);
        }
      }

      throw fail("login.badCredentials");
    },
    [startSession],
  );

  const signUp = useCallback(
    async ({ name, email, registration, roleKey, password }) => {
      await new Promise((resolve) => setTimeout(resolve, 620));
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
        hash,
        salt,
        createdAt: new Date().toISOString(),
      };

      if (!writeAccounts([...accounts, account])) throw fail("signup.storageBlocked");

      const { hash: _h, salt: _s, ...profile } = account;
      // Straight into the portal: making someone register and then immediately
      // type the same credentials again is friction with no purpose when there
      // is no email to verify.
      return startSession(profile, true);
    },
    [startSession],
  );

  /* Writes back to whichever store currently holds the session, so a "keep me
     signed in" choice made at login is not silently reversed by editing a
     profile field. */
  const persistSession = useCallback((session) => {
    try {
      const store = localStorage.getItem(SESSION_KEY) ? localStorage : sessionStorage;
      store.setItem(SESSION_KEY, JSON.stringify(session));
    } catch {
      /* ignore */
    }
  }, []);

  const updateProfile = useCallback(
    async (patch) => {
      await new Promise((resolve) => setTimeout(resolve, 380));
      let next = null;

      setUser((current) => {
        if (!current) return current;
        next = { ...current, ...patch };
        persistSession(next);

        // Registered accounts are the record; the demo account has none, so
        // its edits live only in the session and end at sign-out.
        if (!current.demo) {
          const accounts = readAccounts();
          const i = accounts.findIndex((a) => a.email === current.email);
          if (i !== -1) {
            const { demo: _d, signedInAt: _s, ...storable } = next;
            accounts[i] = { ...accounts[i], ...storable };
            writeAccounts(accounts);
          }
        }
        return next;
      });

      return next;
    },
    [persistSession],
  );

  const changePassword = useCallback(async ({ current, next }) => {
    await new Promise((resolve) => setTimeout(resolve, 520));

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
  }, []);

  const signOut = useCallback(() => {
    try {
      sessionStorage.removeItem(SESSION_KEY);
      localStorage.removeItem(SESSION_KEY);
    } catch {
      /* ignore */
    }
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, ready, signIn, signUp, signOut, updateProfile, changePassword }),
    [user, ready, signIn, signUp, signOut, updateProfile, changePassword],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/* ------------------------------------------------------------ validation --- */

/* Returns a map of field -> i18n key, empty when the form is good. Shared with
   the sign-up page so the rules live in one place. */
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
