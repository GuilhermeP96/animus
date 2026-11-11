"""Supply-chain and cross-platform checkout integrity for offline assets."""

import hashlib
import json
from pathlib import Path


def test_all_locked_preview_assets_keep_upstream_bytes():
    root = Path(__file__).resolve().parents[1] / "desktop/windows"
    lock = json.loads((root / "preview-deps.lock.json").read_text("utf-8"))
    assert lock["schema"] == 1 and len(lock["files"]) > 100
    for relative, expected in lock["files"].items():
        file = root / relative
        assert root in file.resolve().parents
        assert hashlib.sha256(file.read_bytes()).hexdigest() == expected, relative
    packages = {p["name"] for p in lock["packages"]}
    assert {"mermaid", "dompurify", "markdown-it", "katex", "Microsoft.Web.WebView2"} <= packages


def test_runtime_distribution_has_licenses_for_each_preview_package():
    root = Path(__file__).resolve().parents[1] / "desktop/windows"
    lock = json.loads((root / "preview-deps.lock.json").read_text("utf-8"))
    for package in lock["packages"]:
        if package["name"] == "Microsoft.Web.WebView2":
            license_path = root / "vendor/webview2/LICENSE.txt"
        else:
            name = package["name"].replace("@", "").replace("/", "-")
            license_path = root / "preview/vendor/licenses" / (name + "-LICENSE.txt")
        assert license_path.is_file() and license_path.stat().st_size > 100
