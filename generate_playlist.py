#!/usr/bin/env python3
"""Generate a legal English-language IPTV playlist from IPTV-org public data."""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


M3U_URL = "https://iptv-org.github.io/iptv/languages/eng.m3u"
CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
OUTPUT_PATH = Path("iptv.m3u")
USER_AGENT = "iptv-english-north-america-generator/1.0"

ATTRIBUTE_RE = re.compile(r'([\w-]+)="([^"]*)"')
COUNTRY_SUFFIX_RE = re.compile(r"\.([a-z]{2})(?:@|$)", re.IGNORECASE)

CANADA = {"CA"}
UNITED_STATES = {"US"}
UNITED_KINGDOM = {"GB", "UK"}
COLOMBIA = {"CO"}
CARIBBEAN = {
    "AG",
    "AI",
    "AW",
    "BB",
    "BL",
    "BM",
    "BQ",
    "BS",
    "CU",
    "CW",
    "DM",
    "DO",
    "GD",
    "GP",
    "HT",
    "JM",
    "KN",
    "KY",
    "LC",
    "MF",
    "MQ",
    "MS",
    "PR",
    "SX",
    "TC",
    "TT",
    "VC",
    "VG",
    "VI",
}
AMERICAS = {
    "AR",
    "BO",
    "BR",
    "BZ",
    "CL",
    "CR",
    "EC",
    "FK",
    "GF",
    "GL",
    "GT",
    "GY",
    "HN",
    "MX",
    "NI",
    "PA",
    "PE",
    "PY",
    "SR",
    "SV",
    "UY",
    "VE",
}

REGION_ORDER = {
    "Canada": 0,
    "United States": 1,
    "United Kingdom": 2,
    "Caribbean": 3,
    "North America": 4,
    "Colombia English": 5,
    "Americas English": 6,
    "International English": 7,
}

CATEGORY_ORDER = {
    "News": 0,
    "Sports": 1,
    "Movies": 2,
    "Entertainment": 3,
    "Music": 4,
    "Comedy": 5,
    "Culture": 6,
    "TV Shows / Series": 7,
    "Retro / Classic TV": 8,
    "Documentary": 9,
    "Family": 10,
    "Kids": 11,
    "Lifestyle": 12,
    "Cooking": 13,
    "Auto": 14,
    "Outdoor": 15,
    "Travel": 16,
    "Science": 17,
    "Education": 18,
    "Business": 19,
    "Weather": 20,
    "Animation": 21,
    "Cable / General": 22,
    "Public Affairs": 23,
    "Religious": 24,
    "Shopping": 25,
    "Other English": 26,
}

NSFW_KEYWORDS = (
    "adult",
    "adults only",
    "erotic",
    "erotica",
    "hardcore",
    "hot",
    "nude",
    "nudity",
    "playboy",
    "porn",
    "porno",
    "sex",
    "sexy",
    "xxx",
    "xxl",
)
NSFW_RE = re.compile(
    r"(^|[\s/|:;,_\-[({])("
    + "|".join(re.escape(keyword) for keyword in NSFW_KEYWORDS)
    + r")($|[\s/|:;,_\])}])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class M3UEntry:
    attrs: dict[str, str]
    title: str
    url: str
    original_group: str
    metadata: dict[str, Any]
    region: str
    category: str


def download_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc


def parse_extinf(line: str) -> tuple[dict[str, str], str] | None:
    if not line.startswith("#EXTINF:"):
        return None
    comma_index = find_unquoted_comma(line)
    if comma_index == -1:
        return None
    attrs_part = line[:comma_index]
    title = line[comma_index + 1 :].strip()
    attrs = {match.group(1): match.group(2) for match in ATTRIBUTE_RE.finditer(attrs_part)}
    return attrs, title


def find_unquoted_comma(line: str) -> int:
    in_quote = False
    for index, char in enumerate(line):
        if char == '"':
            in_quote = not in_quote
        elif char == "," and not in_quote:
            return index
    return -1


def parse_m3u(text: str, metadata_by_id: dict[str, dict[str, Any]]) -> tuple[list[M3UEntry], dict[str, int]]:
    lines = [line.strip() for line in text.splitlines()]
    entries: list[M3UEntry] = []
    seen_urls: set[str] = set()
    stats = {
        "malformed_entries": 0,
        "duplicate_urls_removed": 0,
        "nsfw_entries_excluded": 0,
    }

    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("#EXTINF:"):
            index += 1
            continue

        parsed = parse_extinf(line)
        if parsed is None:
            stats["malformed_entries"] += 1
            index += 1
            continue

        attrs, title = parsed
        url = ""
        lookahead = index + 1
        while lookahead < len(lines):
            candidate = lines[lookahead].strip()
            if not candidate:
                lookahead += 1
                continue
            if candidate.startswith("#"):
                if candidate.startswith("#EXTINF:"):
                    break
                lookahead += 1
                continue
            url = candidate
            break

        if not title or not url or not is_probable_stream_url(url):
            stats["malformed_entries"] += 1
            index = max(lookahead, index + 1)
            continue

        normalized_url = url.strip()
        if normalized_url in seen_urls:
            stats["duplicate_urls_removed"] += 1
            index = lookahead + 1
            continue

        tvg_id = attrs.get("tvg-id", "").strip()
        metadata = lookup_metadata(tvg_id, metadata_by_id)
        original_group = attrs.get("group-title", "").strip()

        if is_nsfw(attrs, title, metadata):
            stats["nsfw_entries_excluded"] += 1
            index = lookahead + 1
            continue

        region = determine_region(tvg_id, metadata)
        category = determine_category(original_group, metadata, title)

        seen_urls.add(normalized_url)
        entries.append(
            M3UEntry(
                attrs=attrs,
                title=title,
                url=normalized_url,
                original_group=original_group,
                metadata=metadata,
                region=region,
                category=category,
            )
        )
        index = lookahead + 1

    return entries, stats


def is_probable_stream_url(url: str) -> bool:
    return url.startswith(("http://", "https://", "rtmp://", "rtsp://"))


def lookup_metadata(tvg_id: str, metadata_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not tvg_id:
        return {}

    candidates = [tvg_id]
    if "@" in tvg_id:
        candidates.append(tvg_id.split("@", 1)[0])

    for candidate in candidates:
        metadata = metadata_by_id.get(candidate)
        if metadata:
            return metadata
    return {}


def is_nsfw(attrs: dict[str, str], title: str, metadata: dict[str, Any]) -> bool:
    if bool(metadata.get("is_nsfw")):
        return True

    fields: list[str] = [title]
    fields.extend(attrs.get(name, "") for name in ("tvg-id", "tvg-name", "group-title"))
    fields.extend(str(item) for item in metadata.get("categories", []) or [])
    fields.append(str(metadata.get("name", "")))
    return any(NSFW_RE.search(field or "") for field in fields)


def determine_region(tvg_id: str, metadata: dict[str, Any]) -> str:
    countries = metadata_countries(tvg_id, metadata)
    broadcast_area = {str(item).upper() for item in metadata.get("broadcast_area", []) or []}

    if countries & CANADA:
        return "Canada"
    if countries & UNITED_STATES:
        return "United States"
    if countries & UNITED_KINGDOM:
        return "United Kingdom"
    if countries & CARIBBEAN:
        return "Caribbean"
    if countries & {"MX"} or "R/NAMER" in broadcast_area:
        return "North America"
    if countries & COLOMBIA:
        return "Colombia English"
    if countries & AMERICAS:
        return "Americas English"
    return "International English"


def metadata_countries(tvg_id: str, metadata: dict[str, Any]) -> set[str]:
    countries: set[str] = set()
    country = metadata.get("country")
    if isinstance(country, str) and country:
        countries.add(country.upper())

    for area in metadata.get("broadcast_area", []) or []:
        area_text = str(area).upper()
        if area_text.startswith("C/") and len(area_text) >= 4:
            countries.add(area_text.split("/", 1)[1][:2])
        elif area_text.startswith("S/") and len(area_text) >= 4:
            countries.add(area_text.split("/", 1)[1][:2])

    match = COUNTRY_SUFFIX_RE.search(tvg_id or "")
    if match:
        countries.add(match.group(1).upper())

    return countries


def determine_category(original_group: str, metadata: dict[str, Any], title: str) -> str:
    candidates: list[str] = []
    candidates.append(original_group)
    candidates.extend(str(item) for item in metadata.get("categories", []) or [])
    candidates.append(title)

    haystack = " ".join(candidate for candidate in candidates if candidate).lower()
    rules = [
        ("News", ("news", "headline")),
        ("Sports", ("sport", "football", "soccer", "basketball", "baseball", "hockey", "golf", "racing")),
        ("Movies", ("movie", "movies", "cinema", "film")),
        ("Music", ("music", "radio", "vh1", "mtv")),
        ("Comedy", ("comedy",)),
        ("Culture", ("culture", "arts", "art", "museum")),
        ("TV Shows / Series", ("series", "shows", "drama", "soap", "telenovela")),
        ("Retro / Classic TV", ("retro", "classic", "classics", "oldies", "nostalgia")),
        ("Documentary", ("documentary", "docs", "docu")),
        ("Family", ("family",)),
        ("Kids", ("kids", "children", "cartoonito", "nick", "pbs kids")),
        ("Lifestyle", ("lifestyle", "home", "fashion", "health", "wellness")),
        ("Cooking", ("cooking", "food", "kitchen", "recipe")),
        ("Auto", ("auto", "cars", "motor", "motors")),
        ("Outdoor", ("outdoor", "hunt", "fish", "fishing", "adventure")),
        ("Travel", ("travel", "tourism")),
        ("Science", ("science", "space", "nature", "technology", "tech")),
        ("Education", ("education", "educational", "learning", "university")),
        ("Business", ("business", "finance", "financial", "market", "bloomberg")),
        ("Weather", ("weather",)),
        ("Animation", ("animation", "anime", "cartoon")),
        ("Public Affairs", ("public", "government", "parliament", "c-span", "legislature", "civic")),
        ("Religious", ("religious", "faith", "church", "christian", "gospel", "islam", "jewish")),
        ("Shopping", ("shopping", "shop", "qvc", "hsn")),
        ("Entertainment", ("entertainment", "general", "variety")),
    ]
    for category, needles in rules:
        if any(needle in haystack for needle in needles):
            return category

    if original_group and original_group.lower() not in {"undefined", "other"}:
        return normalize_known_category(original_group)
    return "Other English"


def normalize_known_category(value: str) -> str:
    lower = value.strip().lower()
    known = {
        "animation": "Animation",
        "auto": "Auto",
        "business": "Business",
        "classic": "Retro / Classic TV",
        "comedy": "Comedy",
        "cooking": "Cooking",
        "documentary": "Documentary",
        "education": "Education",
        "entertainment": "Entertainment",
        "family": "Family",
        "general": "Cable / General",
        "kids": "Kids",
        "legislative": "Public Affairs",
        "lifestyle": "Lifestyle",
        "movies": "Movies",
        "music": "Music",
        "news": "News",
        "outdoor": "Outdoor",
        "religious": "Religious",
        "science": "Science",
        "series": "TV Shows / Series",
        "shop": "Shopping",
        "sports": "Sports",
        "travel": "Travel",
        "weather": "Weather",
    }
    return known.get(lower, "Other English")


def load_channel_metadata(text: str) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse {CHANNELS_URL}: {exc}") from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"Expected a list from {CHANNELS_URL}")

    metadata: dict[str, dict[str, Any]] = {}
    for item in payload:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            metadata[item["id"]] = item
    return metadata


def build_playlist(entries: list[M3UEntry]) -> str:
    sorted_entries = sorted(
        entries,
        key=lambda entry: (
            REGION_ORDER.get(entry.region, 99),
            CATEGORY_ORDER.get(entry.category, 99),
            natural_key(entry.title),
            entry.url,
        ),
    )

    output = ["#EXTM3U"]
    for entry in sorted_entries:
        group_title = f"{entry.region} / {entry.category}"
        attrs = dict(entry.attrs)
        if not attrs.get("tvg-name"):
            attrs["tvg-name"] = str(entry.metadata.get("name") or entry.title)
        if not attrs.get("tvg-logo"):
            attrs["tvg-logo"] = str(entry.metadata.get("logo") or "")
        attrs["group-title"] = group_title

        attr_text = format_attrs(attrs)
        output.append(f'#EXTINF:-1 {attr_text},{entry.title}')
        output.append(entry.url)
    output.append("")
    return "\n".join(output)


def natural_key(value: str) -> list[Any]:
    parts = re.split(r"(\d+)", value.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def format_attrs(attrs: dict[str, str]) -> str:
    ordered_keys = ["tvg-id", "tvg-name", "tvg-logo", "group-title"]
    keys = ordered_keys + sorted(key for key in attrs if key not in ordered_keys)
    return " ".join(f'{key}="{escape_attr(attrs.get(key, ""))}"' for key in keys)


def escape_attr(value: str) -> str:
    return str(value).replace('"', "&quot;").strip()


def validate_playlist(path: Path) -> dict[str, int]:
    if not path.exists():
        raise RuntimeError(f"{path} does not exist")

    text = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    if not lines or not lines[0].startswith("#EXTM3U"):
        raise RuntimeError(f"{path} must start with #EXTM3U")

    channel_count = 0
    duplicate_count = 0
    nsfw_count = 0
    seen_urls: set[str] = set()
    index = 1
    while index < len(lines):
        line = lines[index]
        if not line:
            index += 1
            continue
        if not line.startswith("#EXTINF:"):
            raise RuntimeError(f"Expected #EXTINF at line {index + 1}, got: {line[:80]}")

        parsed = parse_extinf(line)
        if parsed is None:
            raise RuntimeError(f"Malformed #EXTINF at line {index + 1}")
        attrs, title = parsed
        if not title:
            raise RuntimeError(f"Missing channel title at line {index + 1}")
        if is_nsfw(attrs, title, {}):
            nsfw_count += 1

        if index + 1 >= len(lines):
            raise RuntimeError(f"Missing stream URL after line {index + 1}")
        url = lines[index + 1]
        if not is_probable_stream_url(url):
            raise RuntimeError(f"Invalid stream URL after line {index + 1}: {url[:80]}")
        if url in seen_urls:
            duplicate_count += 1
        seen_urls.add(url)
        channel_count += 1
        index += 2

    if channel_count == 0:
        raise RuntimeError(f"{path} contains no channels")
    if duplicate_count:
        raise RuntimeError(f"{path} contains {duplicate_count} duplicate stream URLs")
    if nsfw_count:
        raise RuntimeError(f"{path} contains {nsfw_count} NSFW-looking entries")

    return {
        "channels": channel_count,
        "duplicate_urls": duplicate_count,
        "nsfw_entries": nsfw_count,
    }


def generate(output_path: Path) -> dict[str, int]:
    m3u_text = download_text(M3U_URL)
    metadata_text = download_text(CHANNELS_URL)
    metadata_by_id = load_channel_metadata(metadata_text)
    entries, stats = parse_m3u(m3u_text, metadata_by_id)
    if not entries:
        raise RuntimeError("No usable channels were generated")

    output_path.write_text(build_playlist(entries), encoding="utf-8", newline="\n")
    validation = validate_playlist(output_path)
    stats.update(validation)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or validate the English IPTV playlist from IPTV-org public data."
    )
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Playlist path to write")
    parser.add_argument("--validate-only", metavar="PATH", help="Validate an existing M3U file and exit")
    args = parser.parse_args()

    try:
        if args.validate_only:
            stats = validate_playlist(Path(args.validate_only))
            action = "validated"
        else:
            stats = generate(Path(args.output))
            action = "generated"
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        textwrap.dedent(
            f"""\
            Playlist {action} successfully.
            channels={stats.get("channels", 0)}
            duplicate_urls_removed={stats.get("duplicate_urls_removed", stats.get("duplicate_urls", 0))}
            nsfw_entries_excluded={stats.get("nsfw_entries_excluded", stats.get("nsfw_entries", 0))}
            malformed_entries_skipped={stats.get("malformed_entries", 0)}
            """
        ).strip()
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
