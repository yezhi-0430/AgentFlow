"""Start only this project's backend and frontend; stop them with Ctrl+C."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def runtime():
    environment = ROOT / "backend" / ".venv"
    candidate = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python = str(candidate) if candidate.exists() else sys.executable
    node = shutil.which("node")
    vite = ROOT / "frontend/node_modules/vite/bin/vite.js"
    if not node or not vite.is_file():
        raise RuntimeError("Install Node.js 22.13+ (22.x) or 24+ and run npm ci in frontend first.")
    version = subprocess.check_output([node, "-p", "process.versions.node"], text=True).strip()
    major, minor, *_ = map(int, version.split("."))
    if not ((major == 22 and minor >= 13) or major >= 24):
        raise RuntimeError("Node.js 22.13+ (22.x) or 24+ is required.")
    result = subprocess.run(
        [python, "-c", "import sys; assert sys.version_info >= (3, 11); import fastapi, uvicorn, openai"],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError('Install backend dependencies: python -m pip install -e "./backend[dev]"')
    return python, node, str(vite)


def ensure_available(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is in use. Stop its owning service or choose another port.")


def stop_children(children):
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
    for child in reversed(children):
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check installed runtimes without starting services")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    args = parser.parse_args()
    if any(not 1 <= port <= 65535 for port in (args.backend_port, args.frontend_port)):
        parser.error("Ports must be between 1 and 65535.")
    if args.backend_port == args.frontend_port:
        parser.error("Backend and frontend must use different ports.")
    children = []
    try:
        python, node, vite = runtime()
        if args.check:
            print("Runtime check passed: Python, Node.js, backend dependencies, and Vite are available.")
            return 0
        ensure_available(args.backend_port)
        ensure_available(args.frontend_port)
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        children.append(subprocess.Popen(
            [python, "-m", "uvicorn", "agentflow.api.app:app", "--host", "127.0.0.1", "--port", str(args.backend_port)],
            cwd=ROOT / "backend", env=environment,
        ))
        frontend_environment = {**environment, "VITE_API_BASE_URL": f"http://127.0.0.1:{args.backend_port}"}
        children.append(subprocess.Popen(
            [node, vite, "--host", "127.0.0.1", "--port", str(args.frontend_port), "--strictPort"],
            cwd=ROOT / "frontend", env=frontend_environment,
        ))
        print(f"Frontend: http://127.0.0.1:{args.frontend_port}", flush=True)
        print(f"API docs: http://127.0.0.1:{args.backend_port}/docs", flush=True)
        print("Press Ctrl+C to stop this project's services.", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        raise RuntimeError("A service exited. See its output above.")
    except KeyboardInterrupt:
        print("\nStopping AgentFlow...")
        return 0
    except (RuntimeError, OSError) as error:
        print(f"Startup failed: {error}", file=sys.stderr)
        return 1
    finally:
        stop_children(children)


if __name__ == "__main__":
    raise SystemExit(main())
