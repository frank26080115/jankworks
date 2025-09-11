/**
 * Update the label width (tape length).
 *
 * @param {string} value - A CSS length with explicit units (e.g. "3in", "75mm").
 *                         Do NOT pass a plain number; always include units.
 *
 * Example:
 *   setLabelWidth("2.5in");
 *   setLabelWidth("65mm");
 */
function setLabelWidth(value) {
  // Update the width
  document.documentElement.style.setProperty("--label-w", value);
  // Recalculate half width automatically
  document.documentElement.style.setProperty("--half-w", `calc(${value} / 2)`);
}

/**
 * Update the label height (tape height).
 *
 * @param {string} value - A CSS length with explicit units (e.g. "0.94in", "24mm").
 *                         Do NOT pass a plain number; always include units.
 *
 * Example:
 *   setLabelHeight("0.47in"); // 12 mm tape
 *   setLabelHeight("24mm");   // 24 mm tape
 */
function setLabelHeight(value) {
  document.documentElement.style.setProperty("--label-h", value);
}