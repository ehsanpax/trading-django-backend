import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CRITICAL_FILES = {
    ROOT / "trades" / "views.py": [
        r"class\s+OpenPositionsLiveView\b",
        r"class\s+AllOpenPositionsLiveView\b",
        r"class\s+PendingOrdersView\b",
        r"class\s+AllPendingOrdersView\b",
        r"class\s+CancelPendingOrderView\b",
        r"class\s+UpdateStopLossAPIView\b",
        r"class\s+PartialCloseTradeView\b",
        r"class\s+SynchronizeAccountTradesView\b",
        r"class\s+WatchlistViewSet\b",
    ],
}


def main() -> int:
    missing = []
    for file_path, patterns in CRITICAL_FILES.items():
        try:
            text = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            missing.append((str(file_path), "<file missing>"))
            continue
        for pat in patterns:
            if not re.search(pat, text):
                missing.append((str(file_path), pat))
    if missing:
        sys.stderr.write("\n[Guard] Missing critical symbols detected:\n")
        for fp, pat in missing:
            sys.stderr.write(f" - {fp}: {pat}\n")
        sys.stderr.write("\nIf you intentionally removed or renamed these, update scripts/check_critical_symbols.py and tests.\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
