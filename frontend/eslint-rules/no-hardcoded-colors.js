/**
 * Flags new hardcoded #hex / rgba() literals outside chartColors.ts (Design Token Layer guard).
 */

const ALLOWED = /chartColors\.ts$/;
const HEX = /#[0-9a-fA-F]{3,8}\b/;
const RGBA = /rgba?\(\s*\d+/;

/** @type {import('eslint').Rule.RuleModule} */
module.exports = {
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow hardcoded color literals; use Design Token Layer or chartColors.ts",
    },
    schema: [],
    messages: {
      hardcoded:
        "Hardcoded color literal — use CSS tokens (Tailwind cockpit-* / text-*) or import from @/lib/chartColors.",
    },
  },
  create(context) {
    const filename = context.getFilename().replace(/\\/g, "/");
    if (!filename.includes("/frontend/src/")) return {};
    if (ALLOWED.test(filename)) return {};

    function check(node, value) {
      if (typeof value !== "string") return;
      if (!HEX.test(value) && !RGBA.test(value)) return;
      context.report({ node, messageId: "hardcoded" });
    }

    return {
      Literal(node) {
        check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.raw);
      },
    };
  },
};
