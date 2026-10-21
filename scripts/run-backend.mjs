import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import dotenv from "dotenv";

const windows = process.platform === "win32";
const root = resolve(import.meta.dirname, "..");
dotenv.config({ path: resolve(root, ".env") });
const virtualenv = resolve(root, windows ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const command = process.env.PYTHON || (existsSync(virtualenv) ? virtualenv : windows ? "py" : "python3");
const args = [
  ...(command === "py" ? ["-3"] : []), "-m", "uvicorn", "app.main:app", "--app-dir", "app/backend", "--reload",
  "--host", process.env.API_HOST || "127.0.0.1", "--port", process.env.API_PORT || "8000",
];
const child = spawn(command, args, { cwd: root, stdio: "inherit", env: process.env });
child.on("error", () => console.error("Python 3.11+ was not found. Install Python and backend dependencies; see README.md."));
child.on("exit", (code) => process.exit(code ?? 1));
