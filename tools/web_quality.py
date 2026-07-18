"""Check the static Russian judge demonstrator without requiring a browser runtime."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def main() -> int:
    required = ("index.html", "styles.css", "app.js", "README.md")
    missing = [name for name in required if not (WEB / name).is_file()]
    content = "\n".join((WEB / name).read_text(encoding="utf-8") for name in required if (WEB / name).is_file())
    checks = {
        "accessible_canvas": 'aria-label="Трёхмерный просмотр' in content and 'tabindex="0"' in content,
        "error_state": 'id="error-card"' in content and 'role="alert"' in content,
        "focus_visible": ":focus-visible" in content,
        "local_only": "file.arrayBuffer()" in content and not re.search(r"\b(?:fetch|XMLHttpRequest|WebSocket)\s*\(", content),
        "official_dimensions": "length > 10" in content and "length < 450" in content and "width < 320" in content,
        "official_k": "metrics.circularity > 0.8" in content,
        "reduced_motion": "prefers-reduced-motion" in content,
        "russian_interface": all(word in content for word in ("Проверить модель", "Результат проверки", "Скачать отчёт")),
        "test_states": all(f'forcedState === "{state}"' in content for state in ("loading", "partial", "fault", "tampered")),
    }
    result = {
        "checks": checks,
        "missing": missing,
        "result": "pass" if not missing and all(checks.values()) else "fail",
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
