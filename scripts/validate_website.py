"""Validate local links, anchors and basic structure in the static website."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


class PageParser(HTMLParser):
    """Collect IDs and local resource references from one HTML page."""

    def __init__(self, path: Path) -> None:
        """Create a parser for one source page."""

        super().__init__()
        self.path = path
        self.ids: set[str] = set()
        self.references: list[tuple[str, str]] = []
        self.errors: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Record identifiers and link-bearing attributes from a start tag."""

        del tag
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            if element_id in self.ids:
                self.errors.append(f"{self.path}: duplicate id {element_id!r}")
            self.ids.add(element_id)
        for attribute in ("href", "src"):
            value = attributes.get(attribute)
            if value:
                self.references.append((attribute, value))


def validate(root: Path) -> list[str]:
    """Return validation errors for the website rooted at ``root``."""

    pages = tuple(sorted(root.glob("*.html")))
    parsed: dict[Path, PageParser] = {}
    errors: list[str] = []
    for page in pages:
        parser = PageParser(page)
        parser.feed(page.read_text(encoding="utf-8"))
        parsed[page.resolve()] = parser
        errors.extend(parser.errors)

    for page, parser in parsed.items():
        for _attribute, reference in parser.references:
            if reference.startswith(("http:", "https:", "mailto:")):
                continue
            target_text, _separator, fragment = reference.partition("#")
            target = (page.parent / target_text).resolve() if target_text else page
            if target_text and not target.exists():
                errors.append(f"{page}: missing local resource {reference!r}")
                continue
            if fragment and target.suffix.lower() == ".html":
                target_page = parsed.get(target)
                if target_page is not None and fragment not in target_page.ids:
                    errors.append(f"{page}: missing anchor {reference!r}")

    stylesheet = root / "styles.css"
    css = stylesheet.read_text(encoding="utf-8")
    if css.count("{") != css.count("}"):
        errors.append(f"{stylesheet}: unbalanced braces")
    return errors


def main() -> int:
    """Validate the repository website and print a compact result."""

    website_root = Path(__file__).resolve().parents[1] / "website"
    errors = validate(website_root)
    if errors:
        print("\n".join(errors))
        return 1
    page_count = len(tuple(website_root.glob("*.html")))
    print(f"Website validation passed: {page_count} HTML pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
