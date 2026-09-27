"""Format references for the configured repository.

Semantic approval belongs to the caller. The repository is the effective
`[provider.github].repo` that Kaji resolves from `.kaji/config.toml` and the
ignored `.kaji/config.local.toml` overlay; no remote discovery occurs.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from kaji_harness.config import KajiConfig  # type: ignore[import-untyped]
from kaji_harness.errors import HarnessError  # type: ignore[import-untyped]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: GitHub が owner 名と repository 名に許す文字。テンプレートの仮の値
#: `<owner>/<repo>` はここで必ず拒否される。
_GITHUB_REPOSITORY = re.compile(
    r"([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})"
)

#: A newly created template has no legacy repository names to accept.
LEGACY_REPOSITORIES: tuple[str, ...] = ()

START = "<!-- kaji-design:start -->"
END = "<!-- kaji-design:end -->"


class InvalidReference(ValueError):
    """A reference or its replacement boundary is not unambiguous."""


class UnconfiguredRepository(InvalidReference):
    """`[provider.github].repo` is not a real GitHub `owner/name`."""


def configured_repository(repository_root: Path = _REPOSITORY_ROOT) -> str:
    """Return the `[provider.github].repo` that Kaji resolves for this checkout.

    Kaji's own loader applies the `.kaji/config.local.toml` overlay, so the
    value always matches what `kaji issue` and `kaji pr` operate on.
    """
    try:
        config = KajiConfig.discover(repository_root)
    except HarnessError as error:
        raise UnconfiguredRepository(
            f"cannot load Kaji configuration: {error}"
        ) from error
    return "" if config.provider is None else config.provider.github.repo


def synchronize(
    body: str,
    design_path: str,
    sha: str,
    summary: str = "",
    *,
    repository: str | None = None,
) -> str:
    """Preserve the body outside one block, or append when both markers are absent.

    This is a text operation, not a design validator: no Git/provider access,
    semantic approval inference, verdict, or automatic publication.
    `repository` defaults to the configured `owner/name`.
    """
    repository = configured_repository() if repository is None else repository
    match = _GITHUB_REPOSITORY.fullmatch(repository)
    if match is None:
        raise UnconfiguredRepository(
            f"[provider.github].repo is {repository!r}; set it to your GitHub "
            "owner/name in .kaji/config.local.toml (docs/howto/use-template.md)"
        )
    owner, name = match.groups()
    repository_alternation = "|".join(
        re.escape(candidate) for candidate in (name, *LEGACY_REPOSITORIES)
    )
    if not re.fullmatch(
        r"designs/issues/issue-[1-9][0-9]*-[a-z0-9-]+\.md", design_path
    ):
        raise InvalidReference("expected a canonical designs/issues path")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise InvalidReference("expected a full lowercase design SHA")
    newline = "\r\n" if "\r\n" in body else "\n"
    url = f"https://github.com/{owner}/{name}/blob/{sha}/{design_path}"
    fields = [
        f"Design: `{design_path}`",
        f"Commit: `{sha}`",
        f"[Design at this commit]({url})",
    ]
    if "<!-- kaji-design:" not in body:
        summary = summary.strip()
        if (
            not summary
            or len(summary.splitlines()) > 20
            or "<!-- kaji-design:" in summary
        ):
            raise InvalidReference(
                "a new block needs a nonempty summary of at most 20 lines without markers"
            )
        normalized_summary = newline.join(summary.splitlines())
        block = newline.join([START, newline.join(fields), "", normalized_summary, END])
        separator = (
            ""
            if not body or body.endswith(newline * 2)
            else newline
            if body.endswith(newline)
            else newline * 2
        )
        return body + separator + block + newline
    if (
        body.count(START) != 1
        or body.count(END) != 1
        or body.count("<!-- kaji-design:") != 2
    ):
        raise InvalidReference("ambiguous or malformed design markers")
    start, end = body.index(START), body.index(END)
    if end < start:
        raise InvalidReference("inverted design markers")
    for position, marker in ((start, START), (end, END)):
        if position and body[position - 1] != "\n":
            raise InvalidReference("design markers must occupy their own lines")
        following = body[position + len(marker) :]
        if following and not following.startswith(("\n", "\r\n")):
            raise InvalidReference("design markers must occupy their own lines")
    # Only recognized reference fields are changed. Summary, headings, commit
    # annotations and all other lines remain byte-for-byte intact. A supplied
    # summary is only a creation input, never permission to replace existing text.
    inner_start = start + len(START)
    inner = body[inner_start:end]
    # A leading title and its whitespace precede the metadata. Once a blank
    # line after a field or any prose starts the summary, never scan it again.
    title = re.match(r"\A(?:[ \t]*\r?\n)*#{1,6}[ \t]+[^\r\n]*\r?\n", inner)
    position = title.end() if title else 0
    whitespace = re.match(r"(?:[ \t]*\r?\n)*", inner[position:])
    assert whitespace is not None
    position += whitespace.end()
    patterns = [
        (re.compile(r"^(?:- )?(?:Design|設計書):\s*(`)([^`]+)(`)"), design_path),
        (re.compile(r"^(?:- )?(?:Commit|設計commit):\s*(`)([0-9a-f]{40})(`)"), sha),
        (
            re.compile(
                r"^(?:- permalink: ?|\[Design at this commit\]\()"
                rf"(https://github\.com/{re.escape(owner)}/)"
                rf"((?:{repository_alternation})/blob/[0-9a-f]{{40}}/[^\s)]+)"
            ),
            f"{name}/blob/{sha}/{design_path}",
        ),
    ]
    seen = [False] * len(patterns)
    lines = []
    in_header = True
    for line in inner[position:].splitlines(keepends=True):
        if not in_header:
            lines.append(line)
            continue
        for index, (pattern, replacement) in enumerate(patterns):
            match = pattern.match(line)
            if match:
                if seen[index]:
                    raise InvalidReference(
                        "duplicate reference field; retain the body and resolve manually"
                    )
                seen[index] = True
                line = line[: match.start(2)] + replacement + line[match.end(2) :]
                break
        else:
            if re.match(
                r"^(?:- )?(?:Design|設計書|Commit|設計commit|permalink):|^\[Design at this commit\]",
                line,
            ):
                raise InvalidReference(
                    "unrecognized reference field; retain the body and repair manually"
                )
            in_header = False
        lines.append(line)
    missing = [
        field for field, present in zip(fields, seen, strict=True) if not present
    ]
    # If an old block lacks a reference, add it without reconstructing its text.
    insertion = newline.join(missing) + newline if missing else ""
    if insertion and not any(seen):
        insertion += newline
    block = START + inner[:position] + insertion + "".join(lines) + END
    return body[:start] + block + body[end + len(END) :]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--design-path", required=True)
    parser.add_argument("--design-sha", required=True)
    parser.add_argument(
        "--summary-file",
        type=Path,
        help="Nonempty initial summary for a missing block; existing block text is always preserved",
    )
    args = parser.parse_args()
    try:
        result = synchronize(
            args.body_file.read_bytes().decode("utf-8"),
            args.design_path,
            args.design_sha,
            args.summary_file.read_text(encoding="utf-8") if args.summary_file else "",
        )
    except (OSError, UnicodeError, InvalidReference) as error:
        print(f"cannot format design reference: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
