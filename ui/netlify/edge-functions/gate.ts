/* ============================================================================
   Site-wide HTTP Basic Auth, enforced at the edge.

   This is the real gate. The sign-in screen inside the app is a demo login
   that runs in the browser and protects nothing -- anyone could read its
   credentials out of the bundle, and the bundle was being served to everyone
   who asked. This function runs before any response is produced, so an
   unauthenticated visitor never receives the HTML, the JavaScript, or the
   demo data at all.

   Netlify's own password protection is a paid-plan feature; this is the
   free-tier equivalent and runs on every path, assets included.
   ==========================================================================*/

const REALM = "BioMarkHER2 portal";

/* Comparison that does not return early on the first differing byte. A string
   `===` leaks how much of a guess was correct through response timing; over
   many requests that is enough to recover a secret character by character. */
function safeEqual(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const left = enc.encode(a);
  const right = enc.encode(b);
  // Fold the length difference in rather than returning early on it.
  let diff = left.length ^ right.length;
  const max = Math.max(left.length, right.length);
  for (let i = 0; i < max; i += 1) {
    diff |= (left[i] ?? 0) ^ (right[i] ?? 0);
  }
  return diff === 0;
}

function challenge(body: string): Response {
  return new Response(body, {
    status: 401,
    headers: {
      "WWW-Authenticate": `Basic realm="${REALM}", charset="UTF-8"`,
      "Content-Type": "text/plain; charset=utf-8",
      // A cached 401 would keep showing the prompt after a correct sign-in,
      // and a cached 200 would hand protected content to the next visitor.
      "Cache-Control": "no-store, must-revalidate",
    },
  });
}

export default async (request: Request) => {
  const expected = Netlify.env.get("SITE_PASSWORD");
  const expectedUser = Netlify.env.get("SITE_USERNAME") ?? "gmck";

  /* Fail closed. If the secret is missing the site is misconfigured, and
     serving it wide open while appearing protected is the worse of the two
     failures -- silence here would look exactly like success. */
  if (!expected) {
    return new Response(
      "This site is password protected, but no password is configured. " +
        "Set the SITE_PASSWORD environment variable in Netlify.",
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  const header = request.headers.get("authorization") ?? "";
  if (!header.startsWith("Basic ")) return challenge("Authentication required.");

  let decoded: string;
  try {
    decoded = atob(header.slice(6).trim());
  } catch {
    return challenge("Malformed credentials.");
  }

  // Split on the FIRST colon only: a password may legitimately contain one,
  // a username may not.
  const split = decoded.indexOf(":");
  if (split === -1) return challenge("Malformed credentials.");
  const user = decoded.slice(0, split);
  const password = decoded.slice(split + 1);

  // Both checks always run, so a wrong username costs the same as a wrong
  // password and neither is distinguishable from the outside.
  const userOk = safeEqual(user, expectedUser);
  const passOk = safeEqual(password, expected);
  if (!(userOk && passOk)) return challenge("Incorrect username or password.");

  // Authenticated: fall through to the normal static response.
  return undefined;
};

export const config = { path: "/*" };
