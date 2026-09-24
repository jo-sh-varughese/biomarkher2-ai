/* ============================================================================
   The hero visual.

   A single full-bleed quad with a fragment shader, not a scene full of
   geometry: the whole image is one draw call, which is what lets it sit
   behind a hero at 60fps on a laptop with integrated graphics.

   What it draws is the product's actual operation. A domain-warped noise
   field stands in for continuous stain optical density; `uClassify` bands
   that continuum into the four HER2 intensity classes using the portal's own
   palette. At rest the field is smooth and unclassified; as the hero scrolls
   the bands harden — raw tissue becoming a classified field. The pointer
   drags a soft lens across it, the way a reader moves over a slide.
   ==========================================================================*/

import { useEffect, useRef } from "react";
// Named imports, not `import * as THREE`: the namespace form defeats
// tree-shaking and drags the whole library (loaders, controls, every
// material) into a bundle that needs one shader-material quad.
import {
  Camera,
  Color,
  Mesh,
  PlaneGeometry,
  Scene,
  ShaderMaterial,
  Vector2,
  WebGLRenderer,
} from "three";

const VERT = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const FRAG = /* glsl */ `
  precision highp float;

  varying vec2 vUv;
  uniform float uTime;
  uniform float uClassify;   // 0 = continuous density, 1 = hard four-class map
  uniform vec2  uPointer;    // -1..1, eased
  uniform vec2  uAspect;
  uniform vec3  uC0, uC1, uC2, uC3;
  uniform vec3  uPaper;

  // Classic 2D value noise. Cheap, and at these scales indistinguishable
  // from anything more expensive once it is warped and banded.
  vec2 hash(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(dot(hash(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),
          dot(hash(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
      mix(dot(hash(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),
          dot(hash(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x),
      u.y);
  }

  float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) {
      v += a * noise(p);
      p *= 2.02;
      a *= 0.5;
    }
    return v;
  }

  void main() {
    vec2 uv = (vUv - 0.5) * uAspect;

    // Pointer lens: a local swell that pulls the field toward the cursor.
    vec2 toPointer = uv - uPointer * vec2(0.5, 0.35) * uAspect;
    float lens = exp(-dot(toPointer, toPointer) * 2.6);

    float t = uTime * 0.045;

    // Domain warping is what turns bland noise into something that reads as
    // tissue: the field is sampled through two other noise fields.
    vec2 q = vec2(fbm(uv * 1.6 + vec2(0.0, t)), fbm(uv * 1.6 + vec2(3.4, -t)));
    vec2 r = vec2(
      fbm(uv * 1.9 + 3.2 * q + vec2(1.7, 9.2) + t * 0.7),
      fbm(uv * 1.9 + 3.2 * q + vec2(8.3, 2.8) - t * 0.6)
    );
    float density = fbm(uv * 2.1 + 3.6 * r + lens * 0.45);

    // Remap to 0..1 and lift the middle so the interesting bands sit where
    // the composition wants them.
    density = smoothstep(-0.42, 0.46, density);

    // Tissue mask: outside it the paper is left unpainted, which is the same
    // rule the portal's own intensity map follows.
    float mask = smoothstep(0.18, 0.42, density + lens * 0.16);

    // --- classification -------------------------------------------------
    // uClassify sharpens the transition between bands. At 0 the classes
    // cross-fade into a continuum; at 1 the boundaries are crisp.
    float soft = mix(0.20, 0.012, uClassify);
    float d = density;

    // Each class is tinted well toward the paper. Full-strength palette is
    // right inside the portal where the map is the subject; behind a
    // headline it has to stay a wash.
    vec3 c0 = mix(uPaper, uC0, 0.30);
    vec3 c1 = mix(uPaper, uC1, 0.34);
    vec3 c2 = mix(uPaper, uC2, 0.34);
    vec3 c3 = mix(uPaper, uC3, 0.30);

    vec3 col = c0;
    col = mix(col, c1, smoothstep(0.42 - soft, 0.42 + soft, d));
    col = mix(col, c2, smoothstep(0.58 - soft, 0.58 + soft, d));
    col = mix(col, c3, smoothstep(0.74 - soft, 0.74 + soft, d));

    // Class boundaries drawn as faint contour lines once classified -- the
    // visual tell that a decision has been made about each pixel.
    float edges = 0.0;
    edges += smoothstep(0.012, 0.0, abs(d - 0.42));
    edges += smoothstep(0.012, 0.0, abs(d - 0.58));
    edges += smoothstep(0.012, 0.0, abs(d - 0.74));
    col = mix(col, vec3(1.0), edges * uClassify * 0.5);

    // Composite over paper, keeping the field light and print-like.
    vec3 outC = mix(uPaper, col, mask * mix(0.55, 0.85, uClassify));

    // Fade hard back to paper at the edges, and clear a soft column on the
    // left where the headline and copy sit, so type never fights the field.
    float vig = smoothstep(1.35, 0.35, length(uv * vec2(0.7, 1.0)));
    outC = mix(uPaper, outC, 0.25 + 0.75 * vig);

    float textSafe = smoothstep(-0.95, 0.15, uv.x);
    outC = mix(mix(uPaper, outC, 0.28), outC, textSafe);

    gl_FragColor = vec4(outC, 1.0);
  }
`;

export type FieldHandle = { setClassify: (v: number) => void };
type Props = { className?: string; onReady?: (api: FieldHandle) => void };

export default function HaloField({ className, onReady }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  /* Live values the render loop reads. Kept in a ref because they change
     every frame and every pointer move -- routing them through React state
     would re-render the tree sixty times a second for no benefit. */
  const live = useRef({ classify: 0, px: 0, py: 0, tx: 0, ty: 0 });

  // Held in a ref so the effect can call the latest callback without listing
  // it as a dependency and tearing down the WebGL context on every render.
  const readyRef = useRef(onReady);
  readyRef.current = onReady;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;

    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ antialias: false, alpha: false, powerPreference: "high-performance" });
    } catch {
      // No WebGL: the CSS gradient underneath the canvas stands in. Better a
      // plain hero than a black rectangle.
      return undefined;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.setSize(host.clientWidth, host.clientHeight, false);
    host.appendChild(renderer.domElement);
    renderer.domElement.style.cssText = "width:100%;height:100%;display:block;";

    const scene = new Scene();
    const camera = new Camera();

    const uniforms = {
      uTime: { value: 0 },
      uClassify: { value: 0 },
      uPointer: { value: new Vector2(0, 0) },
      uAspect: { value: new Vector2(1, 1) },
      // The portal's own class palette, so the hero and the product agree.
      uC0: { value: new Color("#94a3b8") },
      uC1: { value: new Color("#34d399") },
      uC2: { value: new Color("#3b82f6") },
      uC3: { value: new Color("#c026d3") },
      uPaper: { value: new Color("#f5f5f5") },
    };

    const quad = new Mesh(
      new PlaneGeometry(2, 2),
      new ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms }),
    );
    quad.frustumCulled = false;
    scene.add(quad);

    const resize = () => {
      const w = host.clientWidth;
      const h = host.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false);
      const a = w / h;
      uniforms.uAspect.value.set(a > 1 ? a : 1, a > 1 ? 1 : 1 / a);
    };
    resize();

    const ro = new ResizeObserver(resize);
    ro.observe(host);

    const onPointer = (event: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      live.current.tx = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
      live.current.ty = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    // Never render while off screen: this is a full-screen fragment shader
    // and it would otherwise keep a laptop fan running down the whole page.
    let visible = true;
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 });
    io.observe(host);

    let raf = 0;
    // performance.now() rather than THREE.Clock: Clock is deprecated in
    // current three, and elapsed seconds is all this needs.
    const t0 = performance.now();

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (!visible) return;

      const s = live.current;
      s.px += (s.tx - s.px) * 0.05;
      s.py += (s.ty - s.py) * 0.05;

      uniforms.uPointer.value.set(s.px, -s.py);
      uniforms.uClassify.value += (s.classify - uniforms.uClassify.value) * 0.08;
      if (!reduced) uniforms.uTime.value = (now - t0) / 1000;

      renderer.render(scene, camera);
    };

    if (reduced) {
      // One frame, held: the composition without the motion.
      uniforms.uClassify.value = 0.55;
      uniforms.uTime.value = 12;
      renderer.render(scene, camera);
    } else {
      raf = requestAnimationFrame(frame);
    }

    /* Handed upward so the page's ScrollTrigger can drive the classification
       pass by writing straight into the render loop's state -- no React
       re-render per scroll frame. */
    readyRef.current?.({
      setClassify: (v: number) => {
        live.current.classify = Math.max(0, Math.min(1, v));
      },
    });

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      window.removeEventListener("pointermove", onPointer);
      quad.geometry.dispose();
      (quad.material as ShaderMaterial).dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={hostRef} className={className} aria-hidden="true" />;
}
