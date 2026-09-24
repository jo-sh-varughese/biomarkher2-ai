/* ============================================================================
   Motion plumbing: Lenis for the scroll, GSAP for everything driven by it.

   The two have to share one clock. Lenis runs its own RAF and interpolates
   scrollTop; if ScrollTrigger keeps listening to the native scroll event it
   samples a position Lenis has already moved past, and every pinned or
   scrubbed animation lags a frame or two behind the content. Driving Lenis
   from gsap.ticker and pushing its updates into ScrollTrigger keeps both on
   the same frame.
   ==========================================================================*/

import { useEffect, useLayoutEffect, useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";

gsap.registerPlugin(ScrollTrigger);

export const prefersReduced = () =>
  typeof window !== "undefined" &&
  (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);

/** Smooth scroll for the lifetime of the component that calls it. */
export function useLenis() {
  useEffect(() => {
    // Smooth scrolling hijacks the wheel. For someone who has asked the
    // operating system to reduce motion, that is exactly the kind of thing
    // they asked to be spared -- so native scrolling stands.
    if (prefersReduced()) return undefined;

    const lenis = new Lenis({
      duration: 1.05,
      // Expo-out: quick to respond, long to settle. The default is springier
      // than this composition wants.
      easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      wheelMultiplier: 1,
      touchMultiplier: 1.6,
      // Touch devices already have momentum scrolling in hardware; adding a
      // second interpolation on top feels laggy rather than smooth.
      smoothWheel: true,
    });

    lenis.on("scroll", ScrollTrigger.update);

    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);

    // In-page anchors have to go through Lenis or they jump while it glides.
    const onClick = (event: MouseEvent) => {
      const link = (event.target as HTMLElement | null)?.closest?.('a[href^="#"]');
      if (!link) return;
      const id = link.getAttribute("href");
      if (!id || id === "#") return;
      const target = document.querySelector(id);
      if (!target) return;
      event.preventDefault();
      lenis.scrollTo(target as HTMLElement, { offset: -12 });
    };
    document.addEventListener("click", onClick);

    return () => {
      document.removeEventListener("click", onClick);
      gsap.ticker.remove(tick);
      lenis.destroy();
    };
  }, []);
}

/**
 * Reveals every [data-anim] inside `scope` as it arrives, and returns the
 * gsap context so the caller can add more to the same scope.
 *
 * useLayoutEffect, not useEffect: the from-state is set in CSS and cleared
 * here, and doing that after paint lets the unanimated frame show through.
 */
export function useReveals(scope: React.RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const root = scope.current;
    if (!root) return undefined;

    const ctx = gsap.context(() => {
      if (prefersReduced()) {
        gsap.set("[data-anim]", { opacity: 1, y: 0, clearProps: "all" });
        return;
      }

      gsap.utils.toArray<HTMLElement>("[data-anim]").forEach((el) => {
        const delay = Number(el.dataset.animDelay ?? 0) / 1000;
        gsap.fromTo(
          el,
          { opacity: 0, y: 26 },
          {
            opacity: 1,
            y: 0,
            duration: 1.0,
            delay,
            ease: "expo.out",
            scrollTrigger: {
              trigger: el,
              // Slightly before the element is fully in view, so the motion
              // has resolved by the time the eye lands on it.
              start: "top 88%",
              once: true,
            },
          },
        );
      });
    }, root);

    // A late web font changes every text metric on the page; without this the
    // triggers keep firing against stale positions.
    document.fonts?.ready?.then(() => ScrollTrigger.refresh());

    return () => ctx.revert();
  }, [scope]);
}

/**
 * A seamless marquee. GSAP rather than a CSS keyframe so it shares the Lenis
 * ticker, eases on hover instead of snapping, and can be paused when the
 * strip is off screen.
 */
export function useMarquee(ref: React.RefObject<HTMLElement | null>, seconds: number) {
  const tweenRef = useRef<gsap.core.Tween | null>(null);

  useEffect(() => {
    const track = ref.current;
    if (!track) return undefined;
    if (prefersReduced()) return undefined;

    // The list is rendered twice; -50% lands exactly on the second copy's
    // start, so the wrap is invisible.
    const tween = gsap.to(track, {
      xPercent: -50,
      duration: seconds,
      ease: "none",
      repeat: -1,
    });
    tweenRef.current = tween;

    const slow = () => gsap.to(tween, { timeScale: 0.15, duration: 0.6, ease: "power2.out" });
    const resume = () => gsap.to(tween, { timeScale: 1, duration: 0.8, ease: "power2.out" });
    track.addEventListener("pointerenter", slow);
    track.addEventListener("pointerleave", resume);

    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) tween.play();
      else tween.pause();
    });
    io.observe(track);

    return () => {
      track.removeEventListener("pointerenter", slow);
      track.removeEventListener("pointerleave", resume);
      io.disconnect();
      tween.kill();
    };
  }, [ref, seconds]);
}

export { gsap, ScrollTrigger };
