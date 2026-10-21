import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const windows = process.platform === "win32";
const root = resolve(import.meta.dirname, "..");
const virtualenv = resolve(root, windows ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const command = process.env.PYTHON || (existsSync(virtualenv) ? virtualenv : windows ? "py" : "python3");
const args = [...(command === "py" ? ["-3"] : []), "-m", "app.seed", ...process.argv.slice(2)];
const result = spawnSync(command, args, {
  cwd: resolve(root, "app", "backend"),
  stdio: "inherit",
  env: process.env,
});
if (result.error) {
  console.error("Python 3.11+ was not found. Install Python and backend dependencies; see README.md.");
  process.exit(1);
}
process.exit(result.status ?? 1);
