/* While a run is going, bubbles flow along the edges it walked, like data packets: green on the way of a pass, red on a failing
 * branch (On Fail, Error, Else). They only show where the run went; the numbers and thick lines say the same without
 * motion. The phase follows the clock, so drawing an edge again (every update of a running flow) does not restart its
 * bubbles. Nothing moves for people who asked for less motion. */
import { FAILING_PORTS } from "../editor/node-types.js";

export { FAILING_PORTS };
const SPEED = 110; // pixels per second, the same on every edge
const SPACING = 160; // about one bubble per this many pixels
const MAX_BUBBLES = 6;
const SVG = "http://www.w3.org/2000/svg";

/** How the bubbles of an edge of this length move: `count`, `duration` of one trip (s), `delays` (s) between
 * them and `begins` (negative start times that put each at the phase of `clock` ms). */
export function bubbleSpec(length, clock = 0) {
  const duration = length / SPEED;
  const count = Math.min(MAX_BUBBLES, Math.max(1, Math.round(length / SPACING)));
  const delays = Array.from({ length: count }, (_, i) => (i * duration) / count);
  const begins = delays.map((delay) => -((clock / 1000 + delay) % duration));
  return { length, count, duration, delays, begins };
}

/** Put the bubbles on an edge's group: they follow the path of its line. */
export function addBubbles(group, line, failing, reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches) {
  if (reduceMotion) return;
  const length = line.getTotalLength();
  if (!(length > 4)) return;
  const spec = bubbleSpec(length, performance.now());
  const holder = document.createElementNS(SVG, "g");
  holder.setAttribute("class", `ef-bubbles ${failing ? "ef-bubbles--fail" : "ef-bubbles--pass"}`);
  holder.setAttribute("aria-hidden", "true");
  for (const begin of spec.begins) {
    const bubble = document.createElementNS(SVG, "circle");
    bubble.setAttribute("r", "3.5");
    const motion = document.createElementNS(SVG, "animateMotion");
    motion.setAttribute("path", line.getAttribute("d"));
    motion.setAttribute("dur", `${spec.duration}s`);
    motion.setAttribute("begin", `${begin}s`);
    motion.setAttribute("repeatCount", "indefinite");
    bubble.append(motion);
    holder.append(bubble);
  }
  group.append(holder);
}
