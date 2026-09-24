import { useRef, type CSSProperties } from "react";
import { useMarquee } from "./motion";

export type MarqueeItem = { label: string; style: CSSProperties };

type Props = {
  items: MarqueeItem[];
  seconds: number;
  itemClassName: string;
  className?: string;
};

/* The list is rendered twice and the track is translated -50%, which puts the
   second copy exactly where the first started -- that is what makes the loop
   seamless rather than snapping back at the end. The duplicate carries
   aria-hidden so a screen reader hears the row once. */
export default function Marquee({ items, seconds, itemClassName, className }: Props) {
  const track = useRef<HTMLDivElement | null>(null);
  useMarquee(track, seconds);

  return (
    <div className={className}>
      <div className="halo-track" ref={track}>
        {[0, 1].map((copy) => (
          <div className="flex" key={copy} aria-hidden={copy === 1 || undefined}>
            {items.map((item) => (
              <span key={item.label} className={itemClassName} style={item.style}>
                {item.label}
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
