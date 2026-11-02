export default {
  extends: ["@commitlint/config-conventional"],
  // Skip merge commits even when they carry a type prefix (e.g.
  // "chore: Merge pull request #2 ..."), which defeats commitlint's
  // built-in merge-commit ignore.
  ignores: [
    (message) =>
      /^(\w+(\([^)]*\))?!?:\s+)?Merge (branch|pull request|remote-tracking branch|tag|commit) /.test(
        message,
      ),
  ],
  rules: {
    "header-max-length": [0, "always", Infinity],
    "body-max-line-length": [0, "always", Infinity],
    "footer-max-line-length": [0, "always", Infinity],
  },
};
