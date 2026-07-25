// Bun intentionally does not implement URL imports. Node-oriented test harnesses
// commonly use base64 JavaScript data URLs to evaluate a generated ESM module,
// so the `node` compatibility entrypoint resolves that one deterministic form.
Bun.plugin({
  name: "sandwich-node-data-url",
  setup(builder) {
    builder.onResolve(
      { filter: /^data:text\/javascript;base64,/ },
      (args) => ({ path: args.path, namespace: "sandwich-data-js" }),
    );
    builder.onLoad(
      { filter: /.*/, namespace: "sandwich-data-js" },
      (args) => {
        const separator = args.path.indexOf(",");
        if (separator < 0) {
          throw new Error("invalid JavaScript data URL");
        }
        return {
          contents: Buffer.from(args.path.slice(separator + 1), "base64").toString("utf8"),
          loader: "js",
        };
      },
    );
  },
});
