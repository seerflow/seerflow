module.exports = {
  root: true,
  env: { browser: true, es2022: true, node: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: 2022, sourceType: "module" },
  plugins: ["@typescript-eslint", "react-refresh"],
  ignorePatterns: ["dist", "node_modules", ".eslintrc.cjs"],
  rules: {
    "react-refresh/only-export-components": [
      "warn",
      { allowConstantExport: true },
    ],
  },
  overrides: [
    {
      // shadcn/ui generated primitives co-locate variant helpers with
      // components. The react-refresh HMR caveat does not apply here, since
      // these are stable library files we do not edit often.
      files: ["src/components/ui/**"],
      rules: { "react-refresh/only-export-components": "off" },
    },
  ],
};
