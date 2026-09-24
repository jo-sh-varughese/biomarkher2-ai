"""The `biomark` command.

One command in place of the two separate steps a demo used to need --
building the React portal (`cd ui && npm run build`) and then starting the
Python viewer (`python -m app.server`). It builds `ui/dist` only when it is
missing or `--rebuild-ui` is given, so a machine with no Node installed can
still run this as long as someone already built `ui/dist` once (on any
machine) and it travels with the repo -- the actual serving in app/server.py
stays standard-library-only either way; npm is only ever needed at build time,
never at request time.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from threading import Timer

from app.server import UI_DIST_DEFAULT, build_argparser, serve

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"


def _build_ui(ui_dist: Path, *, force: bool) -> None:
    index = ui_dist / "index.html"
    if index.is_file() and not force:
        return

    npm = shutil.which("npm")
    if npm is None:
        if index.is_file():
            print(f"WARNING: `npm` not found; serving the existing (possibly "
                  f"stale) build at {ui_dist}.", file=sys.stderr)
            return
        raise SystemExit(
            f"{index} does not exist and `npm` is not on PATH, so the review "
            "portal cannot be built.\n"
            "Install Node.js, then either:\n"
            f"  - run `npm install && npm run build` inside {UI_DIR}, or\n"
            "  - copy a pre-built ui/dist/ from another machine,\n"
            "and run `biomark` again."
        )

    if not (UI_DIR / "node_modules").is_dir():
        print("Installing UI dependencies (npm install) ...")
        subprocess.run([npm, "install"], cwd=UI_DIR, check=True)

    print("Building the review portal (npm run build) ...")
    subprocess.run([npm, "run", "build"], cwd=UI_DIR, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_argparser()
    parser.prog = "biomark"
    parser.description = (
        "Build the BioMarkHER2 review portal if needed, then serve it "
        "together with the Python backend -- one command in place of "
        "`npm run build` followed by `python -m app.server`."
    )
    parser.set_defaults(ui_dist=str(UI_DIST_DEFAULT))
    parser.add_argument(
        "--rebuild-ui", action="store_true",
        help="Rebuild ui/dist even if a build already exists there.",
    )
    parser.add_argument(
        "--no-build", action="store_true",
        help="Never attempt to build the UI; fail if ui/dist is missing.",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Do not open a browser tab on start.",
    )
    args = parser.parse_args(argv)

    ui_dist = Path(args.ui_dist)
    if args.no_build:
        if not (ui_dist / "index.html").is_file():
            raise SystemExit(f"{ui_dist}/index.html is missing and --no-build was given.")
    else:
        _build_ui(ui_dist, force=args.rebuild_ui)

    if not args.no_browser:
        url = f"http://{args.host}:{args.port}/"
        # Fired once, after a short delay so it lands after the "review
        # viewer -> ..." banner rather than racing the still-loading model.
        Timer(1.0, lambda: webbrowser.open(url)).start()

    return serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
