/* ============================================================================
   Landing page.

   Composition follows a premium fintech layout — full-bleed hero card, tight
   negative tracking, semibold as the heaviest weight, bento cards, typographic
   marquees. What it is selling is a HER2 IHC measurement tool, so the one
   thing that does not get borrowed from that genre is the tone: no growth
   claims, and the section on what the tool cannot do sits above the final
   call to action rather than beneath it.

   Motion: Lenis drives the scroll, GSAP/ScrollTrigger drives everything keyed
   to it, and the hero is a WebGL shader that performs the product's own
   operation — a continuous density field hardening into four classes as you
   scroll. All three stand down under prefers-reduced-motion.
   ==========================================================================*/

import { useLayoutEffect, useMemo, useRef, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import LogoIcon from "../components/halo/LogoIcon";
import HaloField, { type FieldHandle } from "../components/halo/HaloField";
import Marquee, { type MarqueeItem } from "../components/halo/Marquee";
import { gsap, prefersReduced, useLenis, useReveals } from "../components/halo/motion";
import LangToggle from "../components/LangToggle.jsx";
import { useAuth } from "../state/AuthContext.jsx";
import { useT } from "../i18n/I18nContext.jsx";
import { demoAnalysis } from "../lib/demo.js";

/* The deliberately mismatched type in each marquee is the point of the
   device: a row of wordmarks, each set as its owner would set it. */
const CAP_STYLES: CSSProperties[] = [
  { fontFamily: "Georgia, serif", fontWeight: 700, letterSpacing: "-0.02em", fontSize: 15 },
  { fontFamily: "Arial, sans-serif", fontWeight: 900, letterSpacing: "0.08em", fontSize: 13, textTransform: "uppercase" },
  { fontFamily: "'Trebuchet MS', sans-serif", fontWeight: 600, letterSpacing: "0.01em", fontSize: 15, fontStyle: "italic" },
  { fontFamily: "'Courier New', monospace", fontWeight: 700, letterSpacing: "0.12em", fontSize: 13, textTransform: "uppercase" },
  { fontFamily: "Palatino, 'Book Antiqua', serif", fontWeight: 400, letterSpacing: "-0.01em", fontSize: 16 },
  { fontFamily: "Impact, 'Arial Narrow', sans-serif", fontWeight: 400, letterSpacing: "0.04em", fontSize: 14 },
  { fontFamily: "Verdana, sans-serif", fontWeight: 700, letterSpacing: "-0.03em", fontSize: 13 },
];

const REF_STYLES: CSSProperties[] = [
  { fontFamily: "'Times New Roman', serif", fontWeight: 400, letterSpacing: "0.02em", fontSize: 14 },
  { fontFamily: "'Arial Black', sans-serif", fontWeight: 900, letterSpacing: "0.08em", fontSize: 16 },
  { fontFamily: "Impact, sans-serif", fontWeight: 700, letterSpacing: "0.05em", fontSize: 18 },
  { fontFamily: "Georgia, serif", fontWeight: 600, letterSpacing: "-0.02em", fontSize: 17 },
  { fontFamily: "Helvetica, sans-serif", fontWeight: 700, letterSpacing: "-0.01em", fontSize: 15 },
  { fontFamily: "Verdana, sans-serif", fontWeight: 700, letterSpacing: "0.06em", fontSize: 14, textTransform: "uppercase" },
  { fontFamily: "'Courier New', monospace", fontWeight: 700, letterSpacing: "0.18em", fontSize: 14 },
  { fontFamily: "Palatino, serif", fontWeight: 500, letterSpacing: "0.03em", fontSize: 15 },
];

const INK = "#2B2644";

export default function Landing() {
  const t = useT() as (k: string) => string;
  const { user } = useAuth() as { user: { name?: string } | null };

  const page = useRef<HTMLDivElement | null>(null);
  const heroCard = useRef<HTMLDivElement | null>(null);
  const fieldApi = useRef<FieldHandle | null>(null);
  const wipeRef = useRef<HTMLDivElement | null>(null);

  useLenis();
  useReveals(page);

  /* The same deterministic field the portal renders in demo mode, so the
     imagery on this page is the product's real output rather than a mock-up
     that can drift away from it. */
  const field = useMemo(() => demoAnalysis("GMCK-0688-C2") as { images: Record<string, string> }, []);

  useLayoutEffect(() => {
    if (prefersReduced()) return undefined;

    const ctx = gsap.context(() => {
      /* Hero headline: each line is masked and slides up from below. This is
         the only entrance not tied to scroll — it plays on load. */
      gsap.set(".halo-line > span", { yPercent: 115 });
      gsap
        .timeline({ defaults: { ease: "expo.out" } })
        .to(".halo-line > span", { yPercent: 0, duration: 1.25, stagger: 0.09 }, 0.15)
        .fromTo(".hero-fade", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 1, stagger: 0.1 }, 0.5);

      /* Scroll drives the shader's classification pass: the field starts as
         continuous density and hardens into four classes as the hero leaves. */
      gsap.to(
        {},
        {
          scrollTrigger: {
            trigger: heroCard.current,
            start: "top top",
            end: "bottom top",
            scrub: true,
            onUpdate: (self) => fieldApi.current?.setClassify(self.progress),
          },
        },
      );

      /* The compare card: a scrubbed wipe between the original field and the
         model's intensity map -- the portal's own compare control, played by
         the scrollbar. */
      gsap.fromTo(
        wipeRef.current,
        { clipPath: "inset(0 100% 0 0)" },
        {
          clipPath: "inset(0 0% 0 0)",
          ease: "none",
          scrollTrigger: {
            trigger: wipeRef.current,
            start: "top 80%",
            end: "bottom 45%",
            scrub: 0.6,
          },
        },
      );
    }, page);

    return () => ctx.revert();
  }, []);

  const portalHref = user ? "/overview" : "/login";
  const caps: MarqueeItem[] = CAP_STYLES.map((style, i) => ({
    label: t(`landing.m${i + 1}`),
    style,
  }));
  const refs: MarqueeItem[] = REF_STYLES.map((style, i) => ({
    label: t(`landing.r${i + 1}`),
    style,
  }));

  const pill =
    "inline-flex items-center gap-3 bg-black text-white font-medium pl-8 pr-2 py-2 rounded-full hover:bg-gray-800 transition-colors duration-200";
  const arrow = (
    <span className="bg-white rounded-full p-2">
      <ArrowRight className="w-5 h-5 text-black" />
    </span>
  );

  return (
    <div className="halo flex flex-col bg-[#F5F5F5]" ref={page}>
      {/* ============================================ hero + navbar ======= */}
      <div className="h-screen flex flex-col overflow-hidden">
        <nav className="absolute top-0 left-0 right-0 z-20 px-6 py-5">
          <div className="max-w-[88rem] mx-auto flex items-center justify-between">
            <Link to="/" className="flex items-center gap-2.5">
              <LogoIcon className="w-7 h-7 text-black" />
              {/* The wordmark stands down on the narrowest screens so the
                  language toggle and the call to action still fit -- the mark
                  alone carries the brand there. */}
              <span className="hidden sm:inline text-2xl font-medium tracking-tight text-black">
                BioMarkHER2
              </span>
            </Link>

            <div className="hidden md:flex items-center gap-8">
              {[
                ["#method", "landing.nav.method"],
                ["#compare", "landing.nav.compare"],
                ["#limits", "landing.nav.limits"],
              ].map(([href, key]) => (
                <a
                  key={href}
                  href={href}
                  className="text-base text-gray-700 hover:text-black font-medium transition-colors duration-200"
                >
                  {t(key)}
                </a>
              ))}
              <Link
                to="/model"
                className="text-base text-gray-700 hover:text-black font-medium transition-colors duration-200"
              >
                {t("landing.nav.model")}
              </Link>
            </div>

            <div className="flex items-center gap-3">
              <LangToggle />
              <Link
                to={portalHref}
                className="bg-black text-white text-sm md:text-base font-medium px-5 md:px-7 py-2 md:py-2.5 rounded-full hover:bg-gray-800 transition-colors duration-200 whitespace-nowrap"
              >
                {t("landing.nav.cta")}
              </Link>
            </div>
          </div>
        </nav>

        <section className="flex-1 px-6 pt-20 pb-6 flex items-end">
          <div
            ref={heroCard}
            className="relative w-full rounded-2xl overflow-hidden bg-[#F5F5F5]"
            style={{ height: "calc(100vh - 96px)" }}
          >
            {/* WebGL field. A CSS wash sits underneath so a machine with no
                WebGL still gets a composed hero rather than a blank card. */}
            <div
              className="absolute inset-0"
              style={{
                background:
                  "radial-gradient(70% 60% at 30% 40%, #dfe6f5 0%, transparent 60%), radial-gradient(60% 55% at 75% 65%, #e6dcf0 0%, transparent 62%), #F5F5F5",
              }}
            />
            <HaloField
              className="absolute inset-0 w-full h-full"
              onReady={(api) => {
                fieldApi.current = api;
              }}
            />
            <span className="halo-grain" />

            <div className="relative z-10 flex flex-col items-start justify-start h-full p-8 md:p-12 pt-28 md:pt-36">
              <h1
                className="text-black text-5xl md:text-6xl font-medium leading-tight max-w-xl mb-4"
                style={{ letterSpacing: "-0.04em" }}
              >
                <span className="halo-line">
                  <span>{t("landing.hero.line1")}</span>
                </span>
                <span className="halo-line">
                  <span>{t("landing.hero.line2")}</span>
                </span>
              </h1>

              <p
                className="hero-fade text-black/70 text-base md:text-lg max-w-md mb-8 leading-relaxed"
                style={{ fontFamily: "'Inter', ui-sans-serif, system-ui, sans-serif" }}
              >
                {t("landing.hero.sub")}
              </p>

              <Link to={portalHref} className={`hero-fade ${pill} text-base md:text-lg`}>
                {t("landing.hero.cta")}
                {arrow}
              </Link>

              <Marquee
                items={caps}
                seconds={22}
                className="hero-fade mt-16 md:mt-24 w-full max-w-md overflow-hidden"
                itemClassName="mx-7 shrink-0 text-black/60 whitespace-nowrap"
              />
            </div>
          </div>
        </section>
      </div>

      {/* ================================================== info ========== */}
      <section id="method" className="bg-[#F5F5F5] px-6 py-24">
        <div className="max-w-[88rem] mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-12 mb-16 items-start">
            <div>
              <h2
                className="text-black text-4xl md:text-5xl font-medium leading-tight mb-8"
                style={{ letterSpacing: "-0.03em" }}
                data-anim
              >
                {t("landing.info.title")}
              </h2>
              <Link to="/method" className={`${pill} text-base`} data-anim data-anim-delay="80">
                {t("landing.info.cta")}
                {arrow}
              </Link>
            </div>
            <p className="text-black/70 text-2xl md:text-3xl leading-relaxed" data-anim data-anim-delay="60">
              {t("landing.info.body")}
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <article
              className="lg:col-span-2 rounded-2xl overflow-hidden p-7 min-h-80 flex flex-col justify-between"
              style={{
                // Quoted deliberately: the field images are SVG data URIs and
                // the SVG carries rotate(...) transforms. encodeURIComponent
                // leaves parentheses alone, so an unquoted url() terminates at
                // the first one and the background silently never loads.
                backgroundImage: `url("${field.images.model}")`,
                backgroundSize: "cover",
                backgroundPosition: "center",
              }}
              data-anim
            >
              <h3
                className="text-black text-2xl font-medium leading-snug"
                style={{ letterSpacing: "-0.02em" }}
              >
                {t("landing.info.c1t")}
              </h3>
              <p className="text-black/70 text-base max-w-xs bg-[#F5F5F5]/70 rounded-lg px-3 py-2 backdrop-blur-sm">
                {t("landing.info.c1b")}
              </p>
            </article>

            {(["c2", "c3"] as const).map((k, i) => (
              <article
                key={k}
                className="rounded-2xl p-7 min-h-80 flex flex-col justify-between"
                style={{ background: INK }}
                data-anim
                data-anim-delay={String(80 + i * 80)}
              >
                <h3
                  className="text-white text-2xl font-medium leading-snug"
                  style={{ letterSpacing: "-0.02em" }}
                >
                  {t(`landing.info.${k}t`)
                    .split("\n")
                    .map((line, j) => (
                      <span key={j} className="block">
                        {line}
                      </span>
                    ))}
                </h3>
                <p className="text-white/60 text-base">{t(`landing.info.${k}b`)}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* ============================================== grounded in ======= */}
      <section className="bg-[#F5F5F5] px-6 py-10">
        <div className="max-w-[88rem] mx-auto grid grid-cols-1 md:grid-cols-4 gap-8 items-center">
          <p className="text-black/70 text-base leading-relaxed whitespace-pre-line" data-anim>
            {t("landing.grounded.lead")}
          </p>
          <Marquee
            items={refs}
            seconds={30}
            className="md:col-span-3 overflow-hidden"
            itemClassName="mx-10 shrink-0 text-black/50 whitespace-nowrap"
          />
        </div>
      </section>

      {/* ================================================ use modes ======= */}
      <section id="compare" className="bg-[#F5F5F5] px-6 py-24">
        <div className="max-w-[88rem] mx-auto grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
          <div className="md:pr-12 md:pt-2">
            <p className="text-black/60 text-sm mb-2" data-anim>
              {t("landing.use.eyebrow")}
            </p>
            <h2
              className="text-black text-5xl md:text-6xl font-medium leading-none mb-6"
              style={{ letterSpacing: "-0.04em" }}
              data-anim
              data-anim-delay="60"
            >
              {t("landing.use.title")}
            </h2>
            <p className="text-black/60 text-base leading-relaxed max-w-sm" data-anim data-anim-delay="120">
              {t("landing.use.body")}
            </p>
          </div>

          <div className="relative rounded-3xl overflow-hidden min-h-[560px] md:min-h-[720px] bg-white">
            {/* Scroll scrubs the model's map across the original field: the
                portal's compare wipe, driven by the scrollbar. */}
            <img
              src={field.images.original}
              alt=""
              className="absolute inset-0 w-full h-full object-cover"
            />
            <div ref={wipeRef} className="absolute inset-0">
              <img
                src={field.images.model}
                alt=""
                className="absolute inset-0 w-full h-full object-cover"
              />
            </div>
            <div className="absolute inset-0 bg-gradient-to-t from-white via-white/70 to-transparent" />

            <div className="relative z-10 p-8 md:p-12 h-full flex flex-col justify-end">
              <h3
                className="text-black text-4xl md:text-5xl font-medium leading-tight mb-5"
                style={{ letterSpacing: "-0.03em" }}
                data-anim
              >
                {t("landing.use.h3")}
              </h3>
              <p className="text-black/70 text-base max-w-md mb-8" data-anim data-anim-delay="70">
                {t("landing.use.p")}
              </p>
              <Link to="/analysis" className="group inline-flex items-center gap-3 text-black font-medium" data-anim data-anim-delay="140">
                <span className="w-9 h-9 rounded-full bg-white/80 backdrop-blur flex items-center justify-center group-hover:bg-white transition-colors">
                  <ArrowRight className="w-4 h-4 text-black" />
                </span>
                {t("landing.use.link")}
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ================================================== limits ======== */}
      <section id="limits" className="bg-[#F5F5F5] px-6 py-24">
        <div className="max-w-[88rem] mx-auto">
          <div className="max-w-2xl mb-14">
            <p className="text-black/60 text-sm mb-2" data-anim>
              {t("landing.limits.eyebrow")}
            </p>
            <h2
              className="text-black text-4xl md:text-5xl font-medium leading-tight mb-6"
              style={{ letterSpacing: "-0.03em" }}
              data-anim
              data-anim-delay="60"
            >
              {t("landing.limits.title")}
            </h2>
            <p className="text-black/60 text-base leading-relaxed" data-anim data-anim-delay="120">
              {t("landing.limits.body")}
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {(["l1", "l2", "l3", "l4"] as const).map((k, i) => (
              <article
                key={k}
                className="rounded-2xl bg-white p-7 flex gap-5"
                data-anim
                data-anim-delay={String(i * 70)}
              >
                <span className="text-black/25 text-sm font-medium pt-1 tabular-nums">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div>
                  <h3 className="text-black text-lg font-medium mb-2" style={{ letterSpacing: "-0.02em" }}>
                    {t(`landing.${k}`)}
                  </h3>
                  <p className="text-black/60 text-base leading-relaxed">{t(`landing.${k}b`)}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* =================================================== final ======== */}
      <section className="bg-[#F5F5F5] px-6 pb-24">
        <div className="max-w-[88rem] mx-auto">
          <div
            className="relative rounded-3xl overflow-hidden px-8 md:px-16 py-20 md:py-28 text-center"
            style={{ background: INK }}
            data-anim
          >
            <span className="halo-grain" />
            <h2
              className="relative z-10 text-white text-4xl md:text-6xl font-medium leading-tight mb-5 max-w-3xl mx-auto"
              style={{ letterSpacing: "-0.04em" }}
            >
              {t("landing.final.title")}
            </h2>
            <p className="relative z-10 text-white/60 text-base md:text-lg max-w-lg mx-auto mb-9">
              {t("landing.final.body")}
            </p>
            <div className="relative z-10 flex flex-wrap gap-3 justify-center">
              <Link
                to={portalHref}
                className="inline-flex items-center gap-3 bg-white text-black text-base md:text-lg font-medium pl-8 pr-2 py-2 rounded-full hover:bg-white/90 transition-colors duration-200"
              >
                {t("landing.final.cta")}
                <span className="bg-black rounded-full p-2">
                  <ArrowRight className="w-5 h-5 text-white" />
                </span>
              </Link>
              {!user ? (
                <Link
                  to="/signup"
                  className="inline-flex items-center bg-white/10 text-white text-base md:text-lg font-medium px-8 py-4 rounded-full hover:bg-white/20 transition-colors duration-200"
                >
                  {t("login.createAccount")}
                </Link>
              ) : null}
            </div>
          </div>

          <footer className="max-w-[88rem] mx-auto pt-10 flex flex-col md:flex-row gap-4 md:items-center justify-between">
            <div className="flex items-center gap-2.5">
              <LogoIcon className="w-5 h-5 text-black/60" />
              <span className="text-black/60 text-sm font-medium">BioMarkHER2</span>
            </div>
            <p className="text-black/45 text-xs leading-relaxed max-w-2xl">{t("landing.footer")}</p>
          </footer>
        </div>
      </section>
    </div>
  );
}
