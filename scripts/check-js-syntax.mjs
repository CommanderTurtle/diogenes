#!/usr/bin/env bun

const requested = Bun.argv.slice(2);
const files = requested.length
  ? requested
  : [
      "static/app.js",
      ...await Array.fromAsync(
        new Bun.Glob("static/js/**/*.js").scan({ cwd: ".", onlyFiles: true }),
      ),
    ];

const parser = new Bun.Transpiler({ loader: "js" });
const failures = [];

for (const file of [...new Set(files)].sort()) {
  try {
    parser.transformSync(await Bun.file(file).text());
  } catch (error) {
    failures.push(`${file}: ${error?.message || error}`);
  }
}

if (failures.length) {
  throw new Error(`JavaScript parse failures:\n${failures.join("\n")}`);
}

console.log(`Parsed ${files.length} JavaScript files with Bun ${Bun.version}.`);
