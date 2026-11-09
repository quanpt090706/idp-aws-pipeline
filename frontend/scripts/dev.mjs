import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { configFromEnv } from "./config.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const config = configFromEnv(process.env);
const mime = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json" };
createServer(async (req, res) => {
  try {
    const pathname = new URL(req.url, "http://localhost:5173").pathname;
    if (pathname === "/config.json") {
      res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(config));
      return;
    }
    const relative = pathname === "/" ? "index.html" : pathname.slice(1);
    if (!/^(index\.html|styles\.css|app\.js|auth\.js|api\.js|format\.js|mock\.js|mock\/(invoice|transcript)\.json)$/.test(relative)) {
      res.writeHead(404);
      res.end();
      return;
    }
    const filename = relative.startsWith("mock/")
      ? path.join(root, "..", "tests", "fixtures", "expected", path.basename(relative))
      : path.join(root, "src", relative);
    const body = await readFile(filename);
    res.writeHead(200, { "Content-Type": mime[path.extname(filename)], "Cache-Control": "no-store" });
    res.end(body);
  } catch {
    res.writeHead(500);
    res.end();
  }
}).listen(5173, "127.0.0.1", () => console.log("Frontend: http://localhost:5173/"));
