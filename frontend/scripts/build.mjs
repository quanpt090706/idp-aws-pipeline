import { cp, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { configFromEnv } from "./config.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const config = configFromEnv(process.env);
await mkdir(dist, { recursive: true });
for (const name of ["index.html", "styles.css", "app.js", "auth.js", "api.js", "format.js", "mock.js"]) {
  await cp(path.join(root, "src", name), path.join(dist, name));
}
await mkdir(path.join(dist, "mock"), { recursive: true });
for (const name of ["invoice", "transcript"]) {
  await cp(
    path.join(root, "..", "tests", "fixtures", "expected", `${name}.json`),
    path.join(dist, "mock", `${name}.json`),
  );
}
await writeFile(path.join(dist, "config.json"), JSON.stringify(config, null, 2) + "\n");
console.log(`Built ${dist} (${config.mode} mode)`);
