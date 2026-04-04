from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import shutil
import re
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

from ..config import AppConfig


@dataclass(slots=True, frozen=True)
class WikiPageInfo:
    path: str
    name: str
    modified_ts: float


@dataclass(slots=True, frozen=True)
class WikiImageInfo:
    name: str
    modified_ts: float
    used_by: tuple[str, ...] = ()


class WikiService:
    """Filesystem-backed Markdown wiki helper."""

    _WIKI_LINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]|]+?))?(?:\|([^\]]+))?\]\]")
    _WIKI_SPACE_RE = re.compile(r"\[\[space:(\d{1,4})\]\]", re.IGNORECASE)
    _WIKI_IMAGE_RE = re.compile(r"\[\[img:([^\]|]+?)(?:\|([^\]]+))?\]\]", re.IGNORECASE)
    _ALLOWED_IMAGE_EXTENSIONS = {".png", ".gif", ".jpg", ".jpeg"}
    _PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
    _GIF_SIGNATURES = {b"GIF87a", b"GIF89a"}
    _JPEG_SIGNATURE = b"\xff\xd8\xff"

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
        if target_path.exists():
            backup_path = target_path.with_name(f"{target_path.name}.old")
            shutil.copy2(target_path, backup_path)
        target_path.write_text(content, encoding="utf-8")
        return normalized_page

    @staticmethod
    def get_image_dir(cfg: AppConfig) -> Path:
        return (WikiService.get_base_dir(cfg) / "img").resolve()

    @staticmethod
    def normalize_image_name(filename: str) -> str:
        candidate = secure_filename(Path(filename).name)
        suffix = Path(candidate).suffix.lower()
        if not candidate or suffix not in WikiService._ALLOWED_IMAGE_EXTENSIONS:
            raise ValueError("Only .png and .gif wiki images are allowed")
        return candidate

    @staticmethod
    def resolve_image_path(filename: str, cfg: AppConfig) -> tuple[str, Path]:
        image_dir = WikiService.get_image_dir(cfg)
        image_name = WikiService.normalize_image_name(filename)
        image_path = (image_dir / image_name).resolve()
        if image_dir != image_path.parent:
            raise ValueError("Invalid wiki image path")
        return image_name, image_path

    @staticmethod
    def save_image(upload, cfg: AppConfig) -> str:
        filename = getattr(upload, "filename", "") or ""
        image_name, image_path = WikiService.resolve_image_path(filename, cfg)
        suffix = Path(image_name).suffix.lower()
        stream = getattr(upload, "stream", None)
        if stream is None:
            raise ValueError("Invalid upload stream")
        header = stream.read(16)
        stream.seek(0)
        if suffix == ".png" and not header.startswith(WikiService._PNG_SIGNATURE):
            raise ValueError("Invalid PNG signature")
        if suffix == ".gif" and header[:6] not in WikiService._GIF_SIGNATURES:
            raise ValueError("Invalid GIF signature")
        if suffix in {".jpg", ".jpeg"} and not header.startswith(
            WikiService._JPEG_SIGNATURE
        ):
            raise ValueError("Invalid JPEG signature")
        image_path.parent.mkdir(parents=True, exist_ok=True)
        upload.save(image_path)
        return image_name

    @staticmethod
    def list_images(cfg: AppConfig) -> list[WikiImageInfo]:
        image_dir = WikiService.get_image_dir(cfg)
        if not image_dir.exists() or not image_dir.is_dir():
            return []

        image_usage = WikiService.get_image_usage(cfg)
        images: list[WikiImageInfo] = []
        for image_path in image_dir.iterdir():
            if not image_path.is_file():
                continue
            if image_path.suffix.lower() not in WikiService._ALLOWED_IMAGE_EXTENSIONS:
                continue
            stat = image_path.stat()
            images.append(
                WikiImageInfo(
                    name=image_path.name,
                    modified_ts=stat.st_mtime,
                    used_by=tuple(image_usage.get(image_path.name, ())),
                )
            )
        return sorted(images, key=lambda image: image.name.lower())

    @staticmethod
    def get_image_usage(cfg: AppConfig) -> dict[str, list[str]]:
        usage: dict[str, list[str]] = {}
        for page in WikiService.list_pages(cfg):
            try:
                _, content, exists = WikiService.read_page(page.path, cfg)
            except Exception:
                continue
            if not exists or not content:
                continue

            for match in WikiService._WIKI_IMAGE_RE.finditer(content):
                try:
                    image_name = WikiService.normalize_image_name(match.group(1).strip())
                except ValueError:
                    continue
                usage.setdefault(image_name, [])
                if page.name not in usage[image_name]:
                    usage[image_name].append(page.name)
        return usage

    @staticmethod
    def delete_image(filename: str, cfg: AppConfig) -> str:
        image_name, image_path = WikiService.resolve_image_path(filename, cfg)
        if image_path.exists():
            backup_path = image_path.with_name(f"{image_path.name}.bak")
            if backup_path.exists():
                backup_path.unlink()
            image_path.rename(backup_path)
        return image_name

    @staticmethod
    def delete_page(page: str | None, cfg: AppConfig) -> str:
        normalized_page, target_path = WikiService.resolve_page_path(page, cfg)
        if target_path.exists():
            backup_path = target_path.with_name(f"{target_path.name}.bak")
            if backup_path.exists():
                backup_path.unlink()
            target_path.rename(backup_path)
        return normalized_page

    @staticmethod
    def rename_page(page: str | None, new_page: str | None, cfg: AppConfig) -> str:
        normalized_page, source_path = WikiService.resolve_page_path(page, cfg)
        normalized_new_page, target_path = WikiService.resolve_page_path(new_page, cfg)
        if normalized_page == normalized_new_page:
            return normalized_page
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            raise ValueError("Target wiki page already exists")
        if source_path.exists():
            source_path.rename(target_path)
        return normalized_new_page

    @staticmethod
    def render_internal_links(content: str) -> str:
        content = content.replace("[[br]]", "<br>").replace("[[BR]]", "<br>")
        content = WikiService._WIKI_SPACE_RE.sub(
            lambda match: f'<div style="height: {max(0, min(int(match.group(1)), 400))}px;"></div>',
            content,
        )
        content = WikiService._WIKI_IMAGE_RE.sub(
            lambda match: (
                f'<img src="/wiki/media/img/{WikiService.normalize_image_name(match.group(1).strip())}" '
                f'alt="{(match.group(2) or match.group(1)).strip()}" loading="lazy">'
            ),
            content,
        )

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
