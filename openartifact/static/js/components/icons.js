/* The icons of the page. Their paths exist once, in templates/components/icons.html; base.html
 * renders every icon into <template id="icons">, and icon() clones one from there. */

/** @param {string} name an icon of icons.html @param {string} [className] extra classes */
export function icon(name, className = "") {
  const source = document.getElementById("icons")?.content.querySelector(`[data-icon="${name}"] > svg`);
  if (!source) throw new Error(`Unknown icon "${name}"`);
  const svg = source.cloneNode(true);
  if (className) svg.classList.add(...className.split(" "));
  return svg;
}
