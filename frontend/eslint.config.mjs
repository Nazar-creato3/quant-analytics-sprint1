import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "out/**",
      "coverage/**",
      "dist/**",
    ],
  },
  ...nextCoreWebVitals,
  {
    files: ["src/**/*.{js,jsx,ts,tsx}"],
    ignores: ["src/lib/chartColors.ts"],
    rules: {
      // eslint-plugin-react-hooks 7 (Next 16) newly errors on patterns that
      // already passed CI under ESLint 8. Keep them visible; do not fail this bump.
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "no-restricted-syntax": [
        "warn",
        {
          selector: "Literal[value=/^#[0-9a-fA-F]{3,8}$/]",
          message:
            "Hardcoded hex color — use CSS tokens or import from @/lib/chartColors.",
        },
        {
          selector: "Literal[value=/^rgba?\\(/]",
          message:
            "Hardcoded rgba color — use CSS tokens or import from @/lib/chartColors.",
        },
      ],
    },
  },
];

export default eslintConfig;
