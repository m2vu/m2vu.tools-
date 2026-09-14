from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import random
import re
import shutil
import socket
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter, Retry

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme


THEME = Theme({
    "ok": "bold #c792ea",
    "warn": "bold #d4aaff",
    "err": "bold #e06cff",
    "info": "#9d7cd8",
    "dim": "#5c4e8a",
    "accent": "#caa9fa",
    "accent2": "#a78bfa",
    "val": "#ede0ff",
    "head": "bold #e0aaff",
})

console = Console(theme=THEME)

BANNER = r"""
██      ██   ██████   ██      ██ ██      ██      ██████████   ██████     ██████   ██
████  ████ ██      ██ ██      ██ ██      ██          ██     ██      ██ ██      ██ ██
██  ██  ██       ██   ██      ██ ██      ██          ██     ██      ██ ██      ██ ██
██      ██     ██       ██  ██   ██      ██          ██     ██      ██ ██      ██ ██
██      ██ ██████████     ██       ██████   ████     ██       ██████     ██████   ██████████
""".strip("\n")

GRADIENT_PALETTE = [
    "#6e40c9",
    "#8648d8",
    "#9d52e6",
    "#b45ef2",
    "#ca6cf8",
    "#dd82fb",
    "#eeaafd",
]

_RAIN_CHARS = (
    "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿ"
    "ﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ"
    "ﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓ"
    "ﾔﾕﾗﾘﾙﾚﾛﾜﾝ0123456789"
)

_RAIN_TONES = [93, 99, 129, 135, 141, 183]

_UA = "Mozilla/5.0 (compatible; m2vu.tools/1.0; +public-data-search)"

FILE_EXTENSIONS = (
    "*.txt",
    "*.json",
    "*.csv",
    "*.log",
)

EMAIL_RE = re.compile(
    r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
)

DEFAULT_TIMEOUT = 8.0

DEFAULT_SCAN_DIR: Path | None = None


def gradient_text(text: str) -> Text:
    out = Text()

    for i, char in enumerate(text):
        if char == " ":
            out.append(char)
        else:
            out.append(
                char,
                style=GRADIENT_PALETTE[i % len(GRADIENT_PALETTE)],
            )

    return out


def render_banner() -> Panel:
    lines = [
        gradient_text(line)
        for line in BANNER.split("\n")
    ]

    body = Text("\n").join(lines)

    return Panel(
        body,
        border_style="#6e40c9",
        expand=False,
        padding=(0, 2),
    )


def pause(
    message: str = "Press Enter to continue..."
) -> None:
    console.input(
        f"\n[dim]{message}[/]"
    )


def clear_screen() -> None:
    console.clear()


def section(title: str) -> None:
    console.print(
        f"\n[head]── {title} ──[/]\n"
    )


def purple_rain(
    duration: float = 1.1,
    fps: int = 18,
) -> None:
    try:
        size = shutil.get_terminal_size(
            fallback=(80, 24)
        )
        cols = max(size.columns, 10)
        rows = max(size.lines, 5)
    except OSError:
        cols, rows = 80, 24

    drops = [
        random.randint(-rows, 0)
        for _ in range(cols)
    ]

    speeds = [
        random.choice([1, 1, 2])
        for _ in range(cols)
    ]

    trail = 6

    sys.stdout.write("\033[?25l\033[2J")
    sys.stdout.flush()

    try:
        frames = max(
            int(duration * fps),
            1,
        )

        for _ in range(frames):
            buffer = ["\033[H"]

            for y in range(rows):
                row = []

                for x in range(cols):
                    offset = drops[x] - y

                    if offset == 0:
                        row.append(
                            "\033[38;5;255m"
                            + random.choice(_RAIN_CHARS)
                        )

                    elif 0 < offset <= trail:
                        tone = _RAIN_TONES[
                            min(
                                offset - 1,
                                len(_RAIN_TONES) - 1,
                            )
                        ]

                        row.append(
                            f"\033[38;5;{tone}m"
                            + random.choice(_RAIN_CHARS)
                        )

                    else:
                        row.append(" ")

                buffer.append(
                    "".join(row)
                )
                buffer.append("\n")

            sys.stdout.write(
                "".join(buffer)
                + "\033[0m"
            )
            sys.stdout.flush()

            for x in range(cols):
                drops[x] += speeds[x]

                if (
                    drops[x] - trail > rows
                    and random.random() > 0.94
                ):
                    drops[x] = random.randint(
                        -rows,
                        0,
                    )

            time.sleep(1 / fps)

    finally:
        if sys.platform == "win32":
            os.system("cls")
        else:
            sys.stdout.write(
                "\033[2J\033[H\033[?25h\033[0m"
            )
        sys.stdout.flush()


def make_session() -> requests.Session:
    session = requests.Session()

    session.headers.update({
        "User-Agent": _UA,
        "Accept": "*/*",
    })

    retry = Retry(
        total=2,
        backoff_factor=0.35,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=[
            "GET",
            "HEAD",
        ],
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_maxsize=16,
    )

    session.mount(
        "https://",
        adapter,
    )

    session.mount(
        "http://",
        adapter,
    )

    return session


SESSION = make_session()


def http_get(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[int | None, str, str | None]:

    try:
        response = SESSION.get(
            url,
            timeout=timeout,
            allow_redirects=True,
        )

        return (
            response.status_code,
            response.text,
            None,
        )

    except requests.exceptions.SSLError as exc:
        return (
            None,
            "",
            f"SSL error: {exc}",
        )

    except requests.RequestException as exc:
        return (
            None,
            "",
            str(exc),
        )


def collect_files(
    directory: Path,
) -> list[Path]:

    found: set[Path] = set()

    for extension in FILE_EXTENSIONS:
        for file in directory.rglob(extension):
            if file.is_file():
                found.add(file)

    return sorted(found)


def select_files(
    directory: Path,
) -> list[Path]:

    files = collect_files(directory)

    if not files:
        console.print(
            "[warn]Aucun fichier compatible trouvé.[/]"
        )
        return []

    section("File selector")

    for index, file in enumerate(files, 1):
        try:
            relative = file.relative_to(directory)
        except ValueError:
            relative = file

        console.print(
            f"  [accent]\\[{index:>3}][/] "
            f"[val]{relative}[/]"
        )

    console.print(
        "\n[dim]"
        "Sélection : 1 | 1,3,7 | 2-8 | all | q"
        "[/]"
    )

    choice = Prompt.ask(
        "  [val]Files[/]"
    ).strip().lower()

    if choice in {
        "q",
        "quit",
        "back",
    }:
        return []

    if choice == "all":
        return files

    selected: set[int] = set()

    for item in choice.split(","):
        item = item.strip()

        if not item:
            continue

        if "-" in item:
            try:
                start, end = map(
                    int,
                    item.split("-", 1),
                )

                if start > end:
                    start, end = end, start

                for number in range(
                    start,
                    end + 1,
                ):
                    if 1 <= number <= len(files):
                        selected.add(number)

            except ValueError:
                console.print(
                    f"[warn]Sélection ignorée : {item}[/]"
                )

        else:
            try:
                number = int(item)

                if 1 <= number <= len(files):
                    selected.add(number)

            except ValueError:
                console.print(
                    f"[warn]Sélection ignorée : {item}[/]"
                )

    return [
        files[number - 1]
        for number in sorted(selected)
    ]


def highlight_line(
    line: str,
    pattern: re.Pattern | None,
) -> Text:

    if pattern is None:
        return Text(line)

    output = Text()
    position = 0

    for match in pattern.finditer(line):
        output.append(
            line[position:match.start()]
        )

        output.append(
            line[
                match.start():match.end()
            ],
            style="bold #e0aaff",
        )

        position = match.end()

    output.append(line[position:])

    return output


def scan_selected_files(
    files: list[Path],
    keywords: list[str],
) -> None:

    section("Csint")

    escaped = [
        re.escape(keyword)
        for keyword in keywords
        if keyword
    ]

    pattern = (
        re.compile(
            "|".join(escaped),
            re.IGNORECASE,
        )
        if escaped
        else None
    )

    total_hits = 0
    matched_files = 0

    def scan_file(
        path: Path,
    ) -> tuple[Path, int, list[tuple[int, str]]]:

        hits = 0
        shown: list[tuple[int, str]] = []
        seen_lines: set[int] = set()

        try:
            with path.open(
                "r",
                encoding="utf-8",
                errors="ignore",
                newline="",
            ) as handle:

                for line_number, line in enumerate(
                    handle,
                    1,
                ):
                    lower = line.lower()

                    if any(
                        keyword in lower
                        for keyword in keywords
                    ):
                        if line_number not in seen_lines:
                            hits += 1
                            seen_lines.add(line_number)
                            shown.append(
                                (
                                    line_number,
                                    line.rstrip(
                                        "\r\n"
                                    ),
                                )
                            )

        except (
            OSError,
            UnicodeError,
        ):
            return path, -1, []

        return path, hits, shown

    workers = min(
        16,
        max(2, len(files)),
    )

    with Progress(
        SpinnerColumn(
            spinner_name="dots",
            style="info",
        ),
        TextColumn(
            "[progress.description]{task.description}"
        ),
        BarColumn(
            bar_width=28,
            style="#6e40c9",
            complete_style="#dd82fb",
        ),
        TaskProgressColumn(),
        console=console,
    ) as progress:

        task = progress.add_task(
            "Scanning",
            total=len(files),
        )

        with ThreadPoolExecutor(
            max_workers=workers,
        ) as executor:

            futures = {
                executor.submit(
                    scan_file,
                    file,
                ): file
                for file in files
            }

            for future in as_completed(
                futures
            ):
                path, hits, lines = future.result()

                progress.update(
                    task,
                    advance=1,
                    description=(
                        f"[dim]{path.name[:30]}[/]"
                    ),
                )

                if hits < 0:
                    console.print(
                        f"[warn]Impossible de lire "
                        f"{path}[/]"
                    )
                    continue

                if not hits:
                    continue

                matched_files += 1
                total_hits += hits

                console.print(
                    f"\n[accent]▌[/] "
                    f"[val]{path}[/] "
                    f"[dim]({hits} résultat(s))[/]"
                )

                for number, line in lines:
                    console.print(
                        Text(
                            f"  {number:>6}  ",
                            style="dim",
                        )
                        + highlight_line(
                            line,
                            pattern,
                        )
                    )

    console.rule(
        style="#6e40c9"
    )

    if total_hits:
        console.print(
            f"[ok]{total_hits} résultat(s) "
            f"dans {matched_files} fichier(s).[/]"
        )
    else:
        console.print(
            "[warn]Aucun résultat.[/]"
        )

    pause()


def Csint(
    query: str | None = None,
) -> None:

    global DEFAULT_SCAN_DIR

    section("Csint")

    if DEFAULT_SCAN_DIR is not None:
        console.print(
            f"[info]Dossier par défaut : {DEFAULT_SCAN_DIR}[/]"
        )
        console.print(
            "[dim]Entrée pour utiliser ce dossier, ou tape un autre chemin.[/]"
        )

    raw_directory = Prompt.ask(
        "  [val]Directory[/] "
        "[dim](Enter = dossier par défaut ou dossier courant)[/]"
    ).strip()

    if raw_directory:
        directory = Path(raw_directory).expanduser()
    elif DEFAULT_SCAN_DIR is not None:
        directory = DEFAULT_SCAN_DIR
    else:
        directory = Path.cwd()

    if not directory.exists():
        console.print(
            f"[err]Répertoire introuvable : "
            f"{directory}[/]"
        )
        pause()
        return

    if not directory.is_dir():
        console.print(
            "[err]Le chemin indiqué n'est pas "
            "un répertoire.[/]"
        )
        pause()
        return

    DEFAULT_SCAN_DIR = directory

    console.print(
        f"[info]Répertoire : {directory}[/]"
    )

    files = select_files(directory)

    if not files:
        pause()
        return

    console.print(
        f"\n[ok]{len(files)} fichier(s) "
        "sélectionné(s).[/]"
    )

    raw_query = (
        query
        or Prompt.ask(
            "  [val]Keyword(s)[/] "
            "[dim](comma separated)[/]"
        )
    ).strip()

    if not raw_query:
        console.print(
            "[warn]Aucun mot-clé.[/]"
        )
        pause()
        return

    keywords = [
        value.strip().lower()
        for value in raw_query.split(",")
        if value.strip()
    ]

    scan_selected_files(
        files,
        keywords,
    )


@dataclass(frozen=True)
class Platform:
    name: str
    url_template: str
    not_found_status: tuple[int, ...] = (404,)
    not_found_markers: tuple[str, ...] = ()
    category: str = "social"
    unreliable: bool = False

    def url_for(
        self,
        username: str,
    ) -> str:
        return self.url_template.format(
            username
        )


PLATFORMS: list[Platform] = [
    Platform(
        "GitHub",
        "https://github.com/{}",
        category="development",
    ),
    Platform(
        "GitLab",
        "https://gitlab.com/{}",
        category="development",
    ),
    Platform(
        "Bitbucket",
        "https://bitbucket.org/{}",
        category="development",
    ),
    Platform(
        "Codeberg",
        "https://codeberg.org/{}",
        category="development",
    ),
    Platform(
        "PyPI",
        "https://pypi.org/user/{}/",
        category="development",
    ),
    Platform(
        "Docker Hub",
        "https://hub.docker.com/u/{}",
        category="development",
    ),
    Platform(
        "Hugging Face",
        "https://huggingface.co/{}",
        category="ai",
    ),
    Platform(
        "Reddit",
        "https://www.reddit.com/user/{}",
    ),
    Platform(
        "Twitch",
        "https://www.twitch.tv/{}",
    ),
    Platform(
        "YouTube",
        "https://www.youtube.com/@{}",
    ),
    Platform(
        "Steam",
        "https://steamcommunity.com/id/{}",
        not_found_status=(),
        not_found_markers=(
            "The specified profile could not be found",
        ),
    ),
    Platform(
        "Pinterest",
        "https://www.pinterest.com/{}/",
    ),
    Platform(
        "Keybase",
        "https://keybase.io/{}",
    ),
    Platform(
        "Telegram",
        "https://t.me/{}",
        not_found_status=(),
        not_found_markers=(
            "If you have Telegram",
        ),
        unreliable=True,
    ),
    Platform(
        "TikTok",
        "https://www.tiktok.com/@{}",
        not_found_markers=(
            "Couldn't find this account",
        ),
        unreliable=True,
    ),
    Platform(
        "Instagram",
        "https://www.instagram.com/{}/",
        unreliable=True,
    ),
    Platform(
        "X",
        "https://x.com/{}",
        unreliable=True,
    ),
    Platform(
        "Facebook",
        "https://www.facebook.com/{}",
        unreliable=True,
    ),
    Platform(
        "Mastodon",
        "https://mastodon.social/@{}",
        unreliable=True,
    ),
    Platform(
        "Replit",
        "https://replit.com/@{}",
        category="development",
    ),
    Platform(
        "Pastebin",
        "https://pastebin.com/u/{}",
    ),
    Platform(
        "Scratch",
        "https://scratch.mit.edu/users/{}/",
        not_found_markers=(
            "The page you were looking for doesn't exist",
        ),
    ),
    Platform(
        "Gravatar",
        "https://gravatar.com/{}",
    ),
    Platform(
        "Linktree",
        "https://linktr.ee/{}",
        not_found_markers=(
            "Sorry, this page isn't available",
        ),
    ),
    Platform(
        "Wattpad",
        "https://www.wattpad.com/user/{}",
        not_found_markers=(
            "Sorry, we can't find that page",
        ),
    ),
    Platform(
        "Fiverr",
        "https://www.fiverr.com/{}",
        not_found_markers=(
            "Oops! Page not found",
        ),
        unreliable=True,
    ),
    Platform(
        "Vimeo",
        "https://vimeo.com/{}",
    ),
    Platform(
        "Flickr",
        "https://www.flickr.com/people/{}",
        not_found_markers=(
            "Page Not Found",
        ),
    ),
    Platform(
        "Trello",
        "https://trello.com/{}",
        unreliable=True,
    ),
    Platform(
        "Behance",
        "https://www.behance.net/{}",
    ),
    Platform(
        "Dribbble",
        "https://dribbble.com/{}",
    ),
    Platform(
        "Hackerearth",
        "https://www.hackerearth.com/@{}",
        not_found_markers=(
            "Page not found",
        ),
    ),
    Platform(
        "LeetCode",
        "https://leetcode.com/{}",
        not_found_markers=(
            "user not found",
        ),
    ),
    Platform(
        "Codeforces",
        "https://codeforces.com/profile/{}",
        not_found_markers=(
            "Social Graph",
        ),
    ),
    Platform(
        "Medium",
        "https://medium.com/@{}",
        not_found_markers=(
            "Page not found",
        ),
    ),
    Platform(
        "Dev.to",
        "https://dev.to/{}",
    ),
    Platform(
        "Substack",
        "https://{}.substack.com",
        not_found_markers=(
            "Get the Substack app",
        ),
        unreliable=True,
    ),
    Platform(
        "Producthunt",
        "https://www.producthunt.com/@{}",
        not_found_markers=(
            "404",
        ),
    ),
    Platform(
        "Bandcamp",
        "https://{}.bandcamp.com",
        not_found_markers=(
            "Sorry, that something isn't here",
        ),
        unreliable=True,
    ),
    Platform(
        "Soundcloud",
        "https://soundcloud.com/{}",
        not_found_markers=(
            "We can't find that user.",
        ),
    ),
    Platform(
        "Spotify",
        "https://open.spotify.com/user/{}",
        not_found_markers=(
            "Page not found",
        ),
        unreliable=True,
    ),
    Platform(
        "Last.fm",
        "https://www.last.fm/user/{}",
        not_found_markers=(
            "Sorry, this user does not exist",
        ),
    ),
    Platform(
        "Itch.io",
        "https://{}.itch.io",
        not_found_markers=(
            "is not a registered account",
        ),
        unreliable=True,
    ),
    Platform(
        "Gamebanana",
        "https://gamebanana.com/members/search/byname?_sName={}",
        not_found_markers=(
            "No results",
        ),
        unreliable=True,
    ),
]


@dataclass
class CheckResult:
    exists: bool | None
    url: str
    error: str | None = None


def check_platform(
    platform: Platform,
    username: str,
) -> CheckResult:

    url = platform.url_for(
        username
    )

    status, body, error = http_get(
        url,
        timeout=6,
    )

    if status is None:
        return CheckResult(
            None,
            url,
            error,
        )

    if status in platform.not_found_status:
        return CheckResult(
            False,
            url,
        )

    body_lower = body.lower()

    for marker in platform.not_found_markers:
        if marker.lower() in body_lower:
            return CheckResult(
                False,
                url,
            )

    return CheckResult(
        True,
        url,
    )


def osint_username(
    username: str | None = None,
) -> None:

    section("OSINT : username lookup")

    username = (
        username
        or Prompt.ask(
            "  [val]Username[/]"
        )
    ).strip()

    if not username:
        console.print(
            "[warn]Username vide.[/]"
        )
        pause()
        return

    console.print(
        f"[info]Recherche de "
        f"{len(PLATFORMS)} sources...[/]\n"
    )

    found = []

    with Progress(
        SpinnerColumn(
            spinner_name="dots",
            style="info",
        ),
        TextColumn(
            "[progress.description]{task.description}"
        ),
        BarColumn(
            bar_width=28,
            style="#6e40c9",
            complete_style="#dd82fb",
        ),
        TaskProgressColumn(),
        console=console,
    ) as progress:

        task = progress.add_task(
            "lookup",
            total=len(PLATFORMS),
        )

        with ThreadPoolExecutor(
            max_workers=12
        ) as executor:

            futures = {
                executor.submit(
                    check_platform,
                    platform,
                    username,
                ): platform
                for platform in PLATFORMS
            }

            for future in as_completed(
                futures
            ):
                platform = futures[future]

                try:
                    result = future.result()
                except Exception as exc:
                    result = CheckResult(
                        None,
                        platform.url_for(username),
                        str(exc),
                    )

                progress.update(
                    task,
                    advance=1,
                    description=(
                        f"[dim]{platform.name[:24]}[/]"
                    ),
                )

                if result.exists is True:
                    found.append(
                        (
                            platform,
                            result.url,
                        )
                    )

                    warning = (
                        " [dim](unreliable)[/]"
                        if platform.unreliable
                        else ""
                    )

                    progress.console.print(
                        f"  [ok]FOUND[/] "
                        f"[val]{platform.name}[/]"
                        f"{warning}"
                    )

                elif result.exists is None:
                    progress.console.print(
                        f"  [dim]UNKNOWN "
                        f"{platform.name}[/]"
                    )

    console.rule(
        style="#6e40c9"
    )

    if found:
        console.print(
            f"[ok]{len(found)} source(s) "
            "semblent correspondre.[/]\n"
        )

        for platform, url in sorted(
            found,
            key=lambda item: item[0].name.lower(),
        ):
            console.print(
                f"  [accent]{platform.name:<20}[/] "
                f"[dim]{url}[/]"
            )

    else:
        console.print(
            "[warn]Aucun profil confirmé.[/]"
        )

    pause()


def osint_email(
    email: str | None = None,
) -> None:

    section("OSINT : email analysis")

    email = (
        email
        or Prompt.ask(
            "  [val]Email[/]"
        )
    ).strip()

    if not EMAIL_RE.match(email):
        console.print(
            "[err]Format d'adresse email invalide.[/]"
        )
        pause()
        return

    domain = email.rsplit(
        "@",
        1,
    )[1].lower()

    console.print(
        f"[info]Domaine : {domain}[/]"
    )

    try:
        addresses = socket.getaddrinfo(
            domain,
            443,
            type=socket.SOCK_STREAM,
        )

        unique = sorted({
            result[4][0]
            for result in addresses
        })

        if unique:
            console.print(
                "[ok]DNS : domaine résolu[/]"
            )

            for address in unique[:10]:
                console.print(
                    f"  [dim]{address}[/]"
                )

    except socket.gaierror:
        console.print(
            "[warn]DNS : domaine non résolu.[/]"
        )

    digest = hashlib.md5(
        email.strip().lower().encode()
    ).hexdigest()

    status, _, error = http_get(
        f"https://www.gravatar.com/avatar/"
        f"{digest}?d=404",
        timeout=6,
    )

    if status == 200:
        console.print(
            "[ok]Gravatar public détecté.[/]"
        )
    elif status == 404:
        console.print(
            "[dim]Aucun Gravatar public trouvé.[/]"
        )
    else:
        console.print(
            f"[dim]Gravatar : vérification impossible "
            f"({error or status}).[/]"
        )

    pause()


def merge_data(
    first: dict,
    second: dict,
) -> dict:

    result = dict(first)

    for key, value in second.items():
        if (
            value is not None
            and value != ""
            and not result.get(key)
        ):
            result[key] = value

    return result


def fetch_ip_api(
    ip: str,
) -> dict:

    fields = ",".join([
        "status",
        "message",
        "country",
        "countryCode",
        "regionName",
        "city",
        "zip",
        "isp",
        "org",
        "as",
        "lat",
        "lon",
        "timezone",
        "proxy",
        "hosting",
        "mobile",
    ])

    status, body, _ = http_get(
        "http://ip-api.com/json/"
        f"{ip}?fields={fields}",
        timeout=7,
    )

    if status != 200:
        return {}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}

    if data.get("status") != "success":
        return {}

    return {
        "country": data.get("country"),
        "country_code": data.get(
            "countryCode"
        ),
        "region": data.get(
            "regionName"
        ),
        "city": data.get("city"),
        "zip": data.get("zip"),
        "isp": data.get("isp"),
        "org": data.get("org"),
        "asn": data.get("as"),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "timezone": data.get(
            "timezone"
        ),
        "proxy": data.get("proxy"),
        "hosting": data.get("hosting"),
        "mobile": data.get("mobile"),
    }


def fetch_ipinfo(
    ip: str,
) -> dict:

    status, body, _ = http_get(
        f"https://ipinfo.io/{ip}/json",
        timeout=7,
    )

    if status != 200:
        return {}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}

    latitude = None
    longitude = None

    location = data.get(
        "loc",
        "",
    )

    if "," in location:
        try:
            latitude, longitude = map(
                float,
                location.split(",", 1),
            )
        except ValueError:
            pass

    return {
        "country": data.get("country"),
        "region": data.get("region"),
        "city": data.get("city"),
        "zip": data.get("postal"),
        "org": data.get("org"),
        "timezone": data.get(
            "timezone"
        ),
        "hostname": data.get(
            "hostname"
        ),
        "lat": latitude,
        "lon": longitude,
    }


def fetch_ipwhois(
    ip: str,
) -> dict:

    status, body, _ = http_get(
        f"https://ipwho.is/{ip}",
        timeout=7,
    )

    if status != 200:
        return {}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {}

    if not data.get("success", False):
        return {}

    connection = data.get(
        "connection",
        {}
    )

    timezone = data.get(
        "timezone",
        {}
    )

    return {
        "country": data.get("country"),
        "country_code": data.get(
            "country_code"
        ),
        "region": data.get("region"),
        "city": data.get("city"),
        "zip": data.get("postal"),
        "isp": connection.get("isp"),
        "org": connection.get("org"),
        "asn": connection.get("asn"),
        "timezone": timezone.get(
            "id"
        ),
        "lat": data.get("latitude"),
        "lon": data.get("longitude"),
        "proxy": data.get(
            "security",
            {},
        ).get("proxy"),
        "hosting": data.get(
            "security",
            {},
        ).get("hosting"),
        "mobile": data.get(
            "security",
            {},
        ).get("mobile"),
    }


def osint_ip(
    ip: str | None = None,
) -> None:

    section("OSINT : IP intelligence")

    ip = (
        ip
        or Prompt.ask(
            "  [val]IP address[/]"
        )
    ).strip()

    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        console.print(
            "[err]Adresse IP invalide.[/]"
        )
        pause()
        return

    table = Table.grid(
        padding=(0, 2)
    )

    table.add_column(
        style="dim"
    )
    table.add_column(
        style="val"
    )

    table.add_row(
        "Version",
        f"IPv{address.version}",
    )

    if address.is_private:
        table.add_row(
            "Type",
            "Private",
        )

        console.print(
            Panel(
                table,
                title=f"IP: {ip}",
                border_style="#6e40c9",
            )
        )

        console.print(
            "[warn]Une IP privée n'a pas de "
            "géolocalisation Internet publique.[/]"
        )

        pause()
        return

    if address.is_loopback:
        table.add_row(
            "Type",
            "Loopback",
        )

    if address.is_reserved:
        table.add_row(
            "Type",
            "Reserved",
        )

    if address.is_link_local:
        table.add_row(
            "Type",
            "Link-local",
        )

    if address.is_global:
        table.add_row(
            "Type",
            "Public / global",
        )

    sources = [
        fetch_ip_api,
        fetch_ipinfo,
        fetch_ipwhois,
    ]

    merged: dict = {}

    with Progress(
        SpinnerColumn(
            spinner_name="dots",
            style="info",
        ),
        TextColumn(
            "[progress.description]{task.description}"
        ),
        console=console,
    ) as progress:

        task = progress.add_task(
            "Collecting IP intelligence",
            total=len(sources),
        )

        for source in sources:
            try:
                data = source(ip)
                merged = merge_data(
                    merged,
                    data,
                )
            except Exception:
                pass

            progress.update(
                task,
                advance=1,
            )

    if not merged:
        console.print(
            "[warn]Aucune donnée publique "
            "disponible pour cette IP.[/]"
        )
        pause()
        return

    def add_row(
        label: str,
        key: str,
    ) -> None:

        value = merged.get(key)

        if value is not None and value != "":
            table.add_row(
                label,
                str(value),
            )

    add_row(
        "Country",
        "country",
    )

    add_row(
        "Country code",
        "country_code",
    )

    add_row(
        "Region",
        "region",
    )

    add_row(
        "City",
        "city",
    )

    add_row(
        "Postal",
        "zip",
    )

    add_row(
        "ISP",
        "isp",
    )

    add_row(
        "Organization",
        "org",
    )

    add_row(
        "ASN",
        "asn",
    )

    add_row(
        "Timezone",
        "timezone",
    )

    add_row(
        "Hostname",
        "hostname",
    )

    if (
        merged.get("lat") is not None
        and merged.get("lon") is not None
    ):
        table.add_row(
            "Coordinates",
            f"{merged['lat']}, "
            f"{merged['lon']}",
        )

    flags = []

    if merged.get("proxy"):
        flags.append(
            "proxy/VPN possible"
        )

    if merged.get("hosting"):
        flags.append(
            "hosting/datacenter possible"
        )

    if merged.get("mobile"):
        flags.append(
            "mobile network possible"
        )

    if flags:
        table.add_row(
            "Network flags",
            ", ".join(flags),
        )

    console.print(
        Panel(
            table,
            title=f"IP intelligence — {ip}",
            border_style="#6e40c9",
        )
    )

    console.print(
        "\n[dim]"
        "La ville et les coordonnées sont une estimation "
        "de la localisation du réseau. Elles ne permettent "
        "pas de connaître la position physique exacte d'un "
        "utilisateur ou son adresse."
        "[/]"
    )

    pause()


def extract_title(
    html: str,
) -> str:

    match = re.search(
        r"<title[^>]*>(.*?)</title>",
        html or "",
        re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return "(title not found)"

    return re.sub(
        r"\s+",
        " ",
        match.group(1),
    ).strip()


def osint_url(
    url: str | None = None,
) -> None:

    section("OSINT : URL analysis")

    url = (
        url
        or Prompt.ask(
            "  [val]URL[/]"
        )
    ).strip()

    if not url:
        console.print(
            "[warn]URL vide.[/]"
        )
        pause()
        return

    if not url.startswith(
        ("http://", "https://")
    ):
        url = "https://" + url

    parsed = urlparse(url)

    if not parsed.netloc:
        console.print(
            "[err]URL invalide.[/]"
        )
        pause()
        return

    status, body, error = http_get(
        url
    )

    if status is None:
        console.print(
            f"[err]Request failed : "
            f"{error}[/]"
        )
        pause()
        return

    table = Table.grid(
        padding=(0, 2)
    )

    table.add_column(
        style="dim"
    )

    table.add_column(
        style="val"
    )

    table.add_row(
        "Status",
        str(status),
    )

    table.add_row(
        "Final URL",
        url,
    )

    table.add_row(
        "Host",
        parsed.netloc,
    )

    table.add_row(
        "Title",
        extract_title(body),
    )

    console.print(
        Panel(
            table,
            title="URL overview",
            border_style="#6e40c9",
        )
    )

    pause()


@dataclass
class SecurityCheck:
    name: str
    present: bool
    description: str


def security_check(
    url: str | None = None,
) -> None:

    section("OSINT : Security Check")

    url = (
        url
        or Prompt.ask(
            "  [val]URL to inspect[/]"
        )
    ).strip()

    if not url:
        console.print(
            "[warn]URL vide.[/]"
        )
        pause()
        return

    if not url.startswith(
        ("http://", "https://")
    ):
        url = "https://" + url

    parsed = urlparse(url)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        console.print(
            "[err]Schéma non supporté.[/]"
        )
        pause()
        return

    try:
        response = SESSION.get(
            url,
            timeout=10,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        console.print(
            f"[err]Connexion impossible : "
            f"{exc}[/]"
        )
        pause()
        return

    headers = {
        key.lower(): value
        for key, value in response.headers.items()
    }

    checks: list[SecurityCheck] = []

    def add(
        name: str,
        condition: bool,
        description: str,
    ) -> None:
        checks.append(
            SecurityCheck(
                name,
                condition,
                description,
            )
        )

    add(
        "HTTPS",
        response.url.startswith("https://"),
        "La requête finale utilise HTTPS.",
    )

    add(
        "HSTS",
        "strict-transport-security"
        in headers,
        "Strict-Transport-Security présent.",
    )

    add(
        "Content-Security-Policy",
        "content-security-policy"
        in headers,
        "CSP présente.",
    )

    add(
        "X-Content-Type-Options",
        headers.get(
            "x-content-type-options",
            "",
        ).lower() == "nosniff",
        "nosniff présent.",
    )

    add(
        "X-Frame-Options",
        "x-frame-options"
        in headers,
        "Protection contre certains usages iframe.",
    )

    add(
        "Referrer-Policy",
        "referrer-policy"
        in headers,
        "Politique de referrer présente.",
    )

    add(
        "Permissions-Policy",
        "permissions-policy"
        in headers,
        "Permissions-Policy présente.",
    )

    add(
        "Cross-Origin-Opener-Policy",
        "cross-origin-opener-policy"
        in headers,
        "COOP présente.",
    )

    add(
        "Cross-Origin-Resource-Policy",
        "cross-origin-resource-policy"
        in headers,
        "CORP présente.",
    )

    cookie_header = headers.get(
        "set-cookie",
        "",
    )

    if cookie_header:
        lower_cookie = cookie_header.lower()

        add(
            "Cookie Secure",
            "secure" in lower_cookie,
            "Secure détecté dans Set-Cookie.",
        )

        add(
            "Cookie HttpOnly",
            "httponly" in lower_cookie,
            "HttpOnly détecté dans Set-Cookie.",
        )

        add(
            "Cookie SameSite",
            "samesite" in lower_cookie,
            "SameSite détecté dans Set-Cookie.",
        )

    table = Table(
        title=(
            f"Passive security overview — "
            f"{parsed.netloc}"
        )
    )

    table.add_column(
        "Check",
        style="accent",
    )

    table.add_column(
        "Status"
    )

    table.add_column(
        "Observation"
    )

    for item in checks:
        if item.present:
            status = "[ok]PASS[/]"
        else:
            status = "[warn]REVIEW[/]"

        table.add_row(
            item.name,
            status,
            item.description,
        )

    console.print(table)

    info = Table.grid(
        padding=(0, 2)
    )

    info.add_column(
        style="dim"
    )

    info.add_column(
        style="val"
    )

    info.add_row(
        "HTTP status",
        str(response.status_code),
    )

    info.add_row(
        "Final URL",
        response.url,
    )

    info.add_row(
        "Content-Type",
        headers.get(
            "content-type",
            "not disclosed",
        ),
    )

    info.add_row(
        "Server",
        headers.get(
            "server",
            "not disclosed",
        ),
    )

    info.add_row(
        "Content-Length",
        headers.get(
            "content-length",
            "not disclosed",
        ),
    )

    console.print(
        Panel(
            info,
            title="HTTP information",
            border_style="#6e40c9",
        )
    )

    console.print(
        "\n[dim]"
        "Ce module effectue uniquement des contrôles "
        "passifs sur une réponse HTTP. Il ne tente pas "
        "d'exploiter une vulnérabilité, de contourner "
        "une authentification ou de lancer un scan agressif."
        "[/]"
    )

    pause()


def osint_menu() -> None:

    while True:
        clear_screen()

        section("OSINT")

        console.print(
            "  [accent]\\[1][/] "
            "[val]Username lookup[/]"
        )

        console.print(
            "  [accent]\\[2][/] "
            "[val]Email analysis[/]"
        )

        console.print(
            "  [accent]\\[3][/] "
            "[val]IP intelligence[/]"
        )

        console.print(
            "  [accent]\\[4][/] "
            "[val]URL analysis[/]"
        )

        console.print(
            "  [accent]\\[5][/] "
            "[val]Security check[/]"
        )

        console.print(
            "  [accent]\\[0][/] "
            "[dim]Back[/]"
        )

        choice = Prompt.ask(
            "\n  [val]Choice[/]"
        ).strip().lower()

        if choice == "1":
            osint_username()

        elif choice == "2":
            osint_email()

        elif choice == "3":
            osint_ip()

        elif choice == "4":
            osint_url()

        elif choice == "5":
            security_check()

        elif choice in {
            "0",
            "q",
            "back",
        }:
            return

        else:
            console.print(
                "[err]Choix invalide.[/]"
            )
            pause()


def set_default_directory() -> None:

    global DEFAULT_SCAN_DIR

    section("Csint — Dossier par défaut")

    current = (
        str(DEFAULT_SCAN_DIR)
        if DEFAULT_SCAN_DIR
        else "non défini"
    )

    console.print(
        f"[info]Dossier actuel : {current}[/]"
    )

    raw = Prompt.ask(
        "  [val]Nouveau dossier[/]"
    ).strip()

    if not raw:
        console.print(
            "[warn]Aucun chemin saisi.[/]"
        )
        pause()
        return

    path = Path(raw).expanduser()

    if not path.exists() or not path.is_dir():
        console.print(
            "[err]Chemin invalide ou introuvable.[/]"
        )
        pause()
        return

    DEFAULT_SCAN_DIR = path

    console.print(
        f"[ok]Dossier par défaut défini : {path}[/]"
    )

    pause()


@dataclass
class MenuOption:
    key: int
    name: str
    description: str
    action: object


MENU_OPTIONS = [
    MenuOption(
        1,
        "CSINT",
        "Search selected TXT / JSON / CSV / LOG files.",
        Csint,
    ),
    MenuOption(
        2,
        "OSINT",
        "Username, email, IP, URL and passive security.",
        osint_menu,
    ),
]


def build_menu() -> Table:

    table = Table.grid(
        padding=(0, 4)
    )

    table.add_column(
        style="accent",
        width=4,
    )

    table.add_column(
        style="val",
        width=20,
    )

    table.add_column(
        style="dim",
    )

    for option in MENU_OPTIONS:
        table.add_row(
            f"[{option.key}]",
            option.name,
            option.description,
        )

    table.add_row(
        "[0]",
        "Quit",
        "Exit the program.",
    )

    return table


def show_help() -> None:

    section("Help")

    console.print(
        "[val]"
        "1 → sélectionne un répertoire, puis les fichiers "
        "2 → ouvre les outils OSINT.\n"
        "H → affiche cette aide.\n"
        "V → affiche la version.\n"
        "Q → quitte le programme."
        "[/]"
    )

    pause()


def show_version() -> None:

    console.print(
        "\n[info]"
        "m2vu.tools — V1 (Final)"
        "[/]"
    )

    console.print(
        "[dim]"
        "CSINT + OSINT"
        "[/]"
    )

    pause()


def interactive_menu() -> None:

    purple_rain()

    while True:
        clear_screen()

        console.print(
            render_banner()
        )

        console.print(
            "\n"
            "  [accent]\\[A][/] [val]Aide[/]   "
            "[accent]\\[V][/] [val]Version[/]   "
            "[accent]\\[Q][/] [val]Quitter[/]\n"
        )

        console.print(
            build_menu()
        )

        try:
            username = os.getlogin()
        except OSError:
            username = "user"

        choice = Prompt.ask(
            "\n"
            f"[#6e40c9]┌──([bold white]"
            f"{username}"
            f"[/][#6e40c9]@[white]"
            f"m2vu.tools"
            f"[/][#6e40c9])[/]\n"
            f"[#6e40c9]└─$[/]"
        ).strip().lower()

        if choice in {
            "h",
            "help",
        }:
            show_help()

        elif choice in {
            "v",
            "version",
        }:
            show_version()

        elif choice in {
            "q",
            "quit",
            "exit",
            "0",
        }:
            clear_screen()
            return

        else:
            selected = next(
                (
                    option
                    for option in MENU_OPTIONS
                    if str(option.key) == choice
                ),
                None,
            )

            if selected:
                selected.action()

            else:
                console.print(
                    "\n[err]Choix invalide.[/]"
                )
                pause()


def build_arg_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        prog="m2vu_tools",
        description=(
            "CSINT and passive OSINT toolkit"
        ),
    )

    sub = parser.add_subparsers(
        dest="command"
    )

    sub.add_parser(
        "menu"
    )

    files_parser = sub.add_parser(
        "Csint"
    )

    files_parser.add_argument(
        "query"
    )

    user_parser = sub.add_parser(
        "osint-user"
    )

    user_parser.add_argument(
        "username"
    )

    email_parser = sub.add_parser(
        "osint-email"
    )

    email_parser.add_argument(
        "email"
    )

    ip_parser = sub.add_parser(
        "osint-ip"
    )

    ip_parser.add_argument(
        "ip"
    )

    url_parser = sub.add_parser(
        "osint-url"
    )

    url_parser.add_argument(
        "url"
    )

    security_parser = sub.add_parser(
        "security-check"
    )

    security_parser.add_argument(
        "url"
    )

    return parser


def main() -> None:

    args = build_arg_parser().parse_args()

    if args.command == "Csint":
        Csint(
            args.query
        )

    elif args.command == "osint-user":
        osint_username(
            args.username
        )

    elif args.command == "osint-email":
        osint_email(
            args.email
        )

    elif args.command == "osint-ip":
        osint_ip(
            args.ip
        )

    elif args.command == "osint-url":
        osint_url(
            args.url
        )

    elif args.command == "security-check":
        security_check(
            args.url
        )

    else:
        interactive_menu()


if __name__ == "__main__":
    main()