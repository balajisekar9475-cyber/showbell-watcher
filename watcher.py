import json
import os
from pathlib import Path
import requests
from bs4 import BeautifulSoup

WATCHLIST_FILE = Path("watchlist.json")
STATE_FILE = Path("notified_state.json")

# Loaded safely from GitHub Repository Secrets
TELEGRAM_USER = os.environ.get("TELEGRAM_USER", "").strip()
VOICE_LANG = os.environ.get("VOICE_LANG", "en-IN-Standard-A").strip()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def trigger_callmebot(message: str) -> bool:
    if not TELEGRAM_USER:
        print("ERROR: TELEGRAM_USER secret is missing.")
        return False

    # CallMeBot trims spoken text at 256 characters
    safe_text = message[:256]

    # requests.get automatically URL-encodes all parameters
    params = {
        "user": TELEGRAM_USER,
        "text": safe_text,
        "lang": VOICE_LANG,  # Standard voices only (not Wavenet)
        "rpt": "2",          # Repeat spoken alert twice
        "cc": "yes",         # Also send a Telegram text copy with details
    }

    try:
        resp = requests.get(
            "https://api.callmebot.com/start.php",
            params=params,
            timeout=20,
        )
        print(f"CallMeBot response ({resp.status_code}): {resp.text[:150]}")
        return resp.status_code == 200
    except requests.RequestException as exc:
        print(f"Failed to reach CallMeBot: {exc}")
        return False


def is_ticket_live(movie: dict) -> tuple[bool, str]:
    url = movie.get("bookingUrl", "").strip()
    if not url:
        return False, "No URL provided"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code} (site may be blocking bots)"

        soup = BeautifulSoup(resp.text, "html.parser")
        page_text = " ".join(soup.get_text(" ").lower().split())

        title_found = movie["title"].lower() in page_text
        keywords = [k.lower() for k in movie.get("matchKeywords", ["book tickets"])]
        theatres = [t.lower() for t in movie.get("preferredTheatres", [])]

        keyword_hit = any(k in page_text for k in keywords)
        theatre_hits = [t for t in theatres if t in page_text]

        if title_found and (keyword_hit or theatre_hits):
            matched_info = ", ".join(theatre_hits) if theatre_hits else "your city"
            return True, matched_info

        return False, "Not live yet"
    except requests.RequestException as exc:
        return False, f"Request error: {exc}"


def main():
    watchlist = load_json(WATCHLIST_FILE, [])
    notified_ids = set(load_json(STATE_FILE, []))
    state_changed = False

    for movie in watchlist:
        movie_id = movie.get("id") or movie.get("title")
        if movie.get("status") != "watching":
            continue
        if movie_id in notified_ids:
            print(f"Skipping '{movie['title']}' (already notified).")
            continue

        live, detail = is_ticket_live(movie)
        print(f"Checked '{movie['title']}': live={live} ({detail})")

        if live:
            alert_msg = (
                f"ShowBell Alert! Tickets for {movie['title']} are now open in "
                f"{detail}. Open ShowBell or check your booking link now: {movie['bookingUrl']}"
            )
            if trigger_callmebot(alert_msg):
                notified_ids.add(movie_id)
                state_changed = True

    if state_changed:
        save_json(STATE_FILE, sorted(notified_ids))
        print("Updated notified_state.json")


if __name__ == "__main__":
    main()