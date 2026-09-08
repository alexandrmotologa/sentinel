"""Capture real high-resolution screenshots of Sentinel terminal views using headless Chrome."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DOCS_DIR = Path("docs/screenshots")
ARTIFACT_DIR = Path(r"C:\Users\alexander\.gemini\antigravity-ide\brain\3589a361-1b83-4765-bff8-321a66f13cc2")

VIEWS = [
    ("01_dashboard.html", "01_dashboard.png", 1180, 720),
    ("02_probe.html", "02_probe.png", 1180, 680),
    ("03_check_config.html", "03_check_config.png", 1180, 740),
    ("04_metrics.html", "04_metrics.png", 1180, 760),
]

def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    for html_name, png_name, width, height in VIEWS:
        html_file = DOCS_DIR / html_name
        png_file = DOCS_DIR / png_name
        url = html_file.resolve().as_uri()

        cmd = [
            CHROME_PATH,
            "--headless=new",
            f"--screenshot={png_file.resolve()}",
            f"--window-size={width},{height}",
            "--hide-scrollbars",
            url,
        ]

        print(f"Capturing {png_name} at {width}x{height}...")
        subprocess.run(cmd, check=True)

        # Copy to artifact folder for interactive viewing
        dest_artifact = ARTIFACT_DIR / png_name
        shutil.copyfile(png_file, dest_artifact)
        print(f"  -> Saved to {png_file} and copied to {dest_artifact}")

    print("\nAll 4 production screenshots captured successfully!")

if __name__ == "__main__":
    main()
