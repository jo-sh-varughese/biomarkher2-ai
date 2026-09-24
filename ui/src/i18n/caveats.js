/* The four caveat texts are the most safety-critical strings in the app, so
   where they come from matters more than for anything else on screen.

   With a real backend they are served by /api/context and travel with the
   analysis and the PDF report. That copy is authoritative and is shown
   verbatim, in whatever language the server sends -- translating it here
   would mean the screen and the exported report could disagree about what
   the tool claims, which is precisely the failure this app is built to
   avoid.

   In demo mode there is no server, so the strings in the table are the only
   copy there is, and they follow the chosen language. */

export const CAVEAT_KEYS = ["not_a_score", "denominator", "targets", "model_limitation"];

export function resolveCaveats(served, isDemo, t) {
  if (!isDemo) return served ?? {};
  return Object.fromEntries(CAVEAT_KEYS.map((key) => [key, t(`caveats.${key}`)]));
}
