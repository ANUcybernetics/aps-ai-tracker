// Based on the sibling benswift-me config (extends stylelint-config-standard,
// drops no-descending-specificity), but with the standard rules that conflict
// with this repo's deliberate choices turned off, so stylelint stays a useful
// *semantic* CSS linter without fighting oxfmt (which owns formatting) or this
// project's design system.
export default {
  extends: ["stylelint-config-standard"],
  rules: {
    "no-descending-specificity": null,

    // oxfmt owns formatting — don't let stylelint contest it. value-keyword-case
    // also wrongly lowercases font-family names (Arial, Menlo, Consolas).
    "comment-empty-line-before": null,
    "custom-property-empty-line-before": null,
    "value-keyword-case": null,
    "import-notation": null,

    // deliberate, repo-wide design decisions
    "selector-class-pattern": null, // BEM-style names: wall__cell, pb__first
    "hue-degree-notation": null, // oklch hues are written unitless throughout tokens.css
    "property-no-vendor-prefix": null, // -webkit-text-size-adjust / line-clamp need the prefix
  },
};
