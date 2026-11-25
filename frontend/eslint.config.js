import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig([
  globalIgnores(["dist", "coverage"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, tseslint.configs.recommended, reactHooks.configs.flat.recommended],
    languageOptions: { ecmaVersion: 2023, globals: globals.browser },
    rules: {
      // Security design (contract 4.1 / ARCHITECTURE): the session is an HttpOnly server-side cookie. Credentials,
      // tokens and CSRF values must never be persisted in web storage, so web storage is banned outright.
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "Web storage is forbidden: sessions are HttpOnly cookies; keep the CSRF token in memory." },
        { name: "sessionStorage", message: "Web storage is forbidden: sessions are HttpOnly cookies; keep the CSRF token in memory." },
      ],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "localStorage", message: "Web storage is forbidden." },
        { object: "window", property: "sessionStorage", message: "Web storage is forbidden." },
        { object: "globalThis", property: "localStorage", message: "Web storage is forbidden." },
        { object: "globalThis", property: "sessionStorage", message: "Web storage is forbidden." },
      ],
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "Do not inject raw HTML; user content is untrusted." },
      ],
    },
  },
]);
