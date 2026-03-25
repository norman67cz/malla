from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlparse

from ..config import AppConfig


@dataclass(slots=True, frozen=True)
class WikiPageInfo:
    path: str
    name: str
    modified_ts: float


class WikiService:
    """Filesystem-backed Markdown wiki helper."""

    _WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]|]+?))?(?:\|([^\]]+))?\]\]")

    @staticmethod
    def _sort_key(page_path: str) -> tuple[list[int], str]:
        stem = PurePosixPath(page_path).stem.strip().lower()
        match = re.match(r"^(\d+(?:\.\d+)*)", stem)
        if not match:
            return ([], stem)

        numeric_prefix = [int(part) for part in match.group(1).split(".")]
        remainder = stem[match.end() :].strip(" -_.")
        return (numeric_prefix, remainder)

    @staticmethod
    def get_base_dir(cfg: AppConfig) -> Path:
        raw_path = (cfg.wiki_directory or "wiki").strip() or "wiki"
        wiki_dir = Path(raw_path).expanduser()
        if not wiki_dir.is_absolute():
            wiki_dir = Path.cwd() / wiki_dir
        return wiki_dir.resolve()

    @staticmethod
    def list_pages(cfg: AppConfig) -> list[WikiPageInfo]:
        base_dir = WikiService.get_base_dir(cfg)
        if not base_dir.exists() or not base_dir.is_dir():
            return []

        pages: list[WikiPageInfo] = []
        for page_path in base_dir.rglob("*.md"):
            if not page_path.is_file():
                continue

            rel_path = page_path.relative_to(base_dir).as_posix()
            if any(part.startswith(".") for part in PurePosixPath(rel_path).parts):
                continue

            stat = page_path.stat()
            pages.append(
                WikiPageInfo(
                    path=rel_path,
                    name=page_path.stem.replace("_", " "),
                    modified_ts=stat.st_mtime,
                )
            )

        return sorted(pages, key=lambda page: WikiService._sort_key(page.path))

    @staticmethod
    def normalize_page_path(page: str | None, cfg: AppConfig) -> str:
        raw_page = (page or cfg.wiki_default_page or "index.md").strip() or "index.md"
        normalized = PurePosixPath(raw_page)

        if normalized.is_absolute():
            raise ValueError("Absolute wiki paths are not allowed")
        if normalized.suffix.lower() != ".md":
            raise ValueError("Only .md wiki files are allowed")
        if any(part in {"", ".", ".."} for part in normalized.parts):
            raise ValueError("Invalid wiki path")
        if any(part.startswith(".") for part in normalized.parts):
            raise ValueError("Hidden wiki paths are not allowed")

        return normalized.as_posix()

    @staticmethod
    def resolve_page_path(page: str | None, cfg: AppConfig) -> tuple[str, Path]:
        base_dir = WikiService.get_base_dir(cfg)
        normalized_page = WikiService.normalize_page_path(page, cfg)
        target_path = (base_dir / normalized_page).resolve()

        if base_dir != target_path and base_dir not in target_path.parents:
            raise ValueError("Wiki path escapes the configured wiki directory")

        return normalized_page, target_path

    @staticmethod
    def read_page(page: str | None, cfg: AppConfig) -> tuple[str, str, bool]:
        normalized_page, target_path = WikiService.resolve_page_path(page, cfg)
        if not target_path.exists():
            return normalized_page, "", False
        return normalized_page, target_path.read_text(encoding="utf-8"), True

    @staticmethod
    def write_page(page: str | None, content: str, cfg: AppConfig) -> str:
        normalized_page, target_path = WikiService.resolve_page_path(page, cfg)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return normalized_page

    @staticmethod
    def delete_page(page: str | None, cfg: AppConfig) -> str:
        normalized_page, target_path = WikiService.resolve_page_path(page, cfg)
        if target_path.exists():
            target_path.unlink()
        return normalized_page

    @staticmethod
    def rename_page(page: str | None, new_page: str | None, cfg: AppConfig) -> str:
        normalized_page, source_path = WikiService.resolve_page_path(page, cfg)
        normalized_new_page, target_path = WikiService.resolve_page_path(new_page, cfg)
        if normalized_page == normalized_new_page:
            return normalized_page
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.exists():
            source_path.rename(target_path)
        return normalized_new_page

    @staticmethod
    def render_internal_links(content: str) -> str:
        def replace_link(match: re.Match[str]) -> str:
            raw_target = match.group(1).strip()
            raw_label = (match.group(2) or "").strip()
            raw_mode = (match.group(3) or "").strip().lower()

            if not raw_target:
                return match.group(0)

            open_in_new_tab = False
            if raw_target.endswith("^"):
                raw_target = raw_target[:-1].strip()
                open_in_new_tab = True

            if raw_mode in {"new", "blank", "tab"}:
                open_in_new_tab = True

            if not raw_target:
                return match.group(0)

            parsed_target = urlparse(raw_target)
            is_external = parsed_target.scheme.lower() in {"http", "https", "mailto"}
            target = (
                raw_target
                if is_external or raw_target.lower().endswith(".md")
                else f"{raw_target}.md"
            )
            label = raw_label or raw_target
            if open_in_new_tab:
                href = target if is_external else f"/wiki?page={target}"
                return (
                    f'<a href="{href}" target="_blank" '
                    f'rel="noopener noreferrer">{label}</a>'
                )
            if is_external:
                return f"[{label}]({target})"
            return f"[{label}](/wiki?page={target})"

        return WikiService._WIKI_LINK_RE.sub(replace_link, content)
