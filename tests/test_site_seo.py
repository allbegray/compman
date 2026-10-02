"""[L3] Homepage SEO invariants for the GitHub Pages site.

The site is dependency-free static HTML, so nothing else guards these: a
renamed anchor, a stale version string, or a FAQ answer that drifts from the
JSON-LD would ship silently. These tests fail the build instead.

Google's structured-data policy requires FAQPage answers to match the visible
page, which is asserted here rather than trusted.
"""

from __future__ import annotations

import json
import pathlib
import re
import struct
import xml.etree.ElementTree as ElementTree

import pytest

ROOT = pathlib.Path(__file__).parents[1]
SITE = ROOT / "docs" / "site"
INDEX = SITE / "index.html"
SITE_URL = "https://allbegray.github.io/compman/"

PAGE = INDEX.read_text(encoding="utf-8")


def _attr(name: str) -> str:
    """Content of the first <meta name|property="name" content="...">."""
    match = re.search(
        rf'<meta\s+(?:name|property)="{re.escape(name)}"\s+content="([^"]*)"', PAGE
    )
    assert match, f"missing meta tag: {name}"
    return match.group(1)


def _ld_json() -> dict:
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', PAGE, re.S
    )
    assert blocks, "no JSON-LD block found"
    return json.loads(blocks[0])


def _graph_by_type(schema_type: str) -> dict:
    for node in _ld_json()["@graph"]:
        if node["@type"] == schema_type:
            return node
    raise AssertionError(f"JSON-LD has no {schema_type} node")


# ---- titles and descriptions ----


def test_title_is_search_optimized_and_unique():
    title = re.search(r"<title>(.*?)</title>", PAGE).group(1).strip()
    assert 30 <= len(title) <= 70, f"title length {len(title)} outside 30-70"
    assert title.startswith("compman"), "brand must lead the title"
    assert "Docker Compose" in title, "primary keyword must be in the title"


def test_meta_description_is_search_optimized():
    description = _attr("description")
    assert 120 <= len(description) <= 165, f"length {len(description)} outside 120-165"
    for keyword in ("Docker Compose", "Podman", "backup", "deploy"):
        assert keyword in description, f"description is missing '{keyword}'"


def test_robots_meta_allows_indexing_with_large_previews():
    assert "index" in _attr("robots")
    assert "follow" in _attr("robots")
    assert "max-image-preview:large" in _attr("robots")


def test_canonical_url_is_absolute_and_matches_the_deployed_origin():
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', PAGE).group(1)
    assert canonical == SITE_URL
    assert _attr("og:url") == SITE_URL


# ---- social previews ----


@pytest.mark.parametrize(
    "name", ["og:type", "og:site_name", "og:title", "og:description", "og:image", "og:locale"]
)
def test_open_graph_tags_are_present(name: str):
    assert _attr(name).strip()


@pytest.mark.parametrize(
    "name", ["twitter:card", "twitter:title", "twitter:description", "twitter:image"]
)
def test_twitter_card_tags_are_present(name: str):
    assert _attr(name).strip()


def test_social_image_urls_are_absolute_and_exist():
    for name in ("og:image", "twitter:image"):
        url = _attr(name)
        assert url.startswith("https://"), f"{name} must be absolute for crawlers"
        filename = url.rsplit("/", 1)[-1]
        assert (SITE / filename).is_file(), f"{name} points at missing {filename}"


def test_og_image_is_a_valid_share_card():
    data = (SITE / "og-image.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (1200, 630), "Open Graph share cards are 1200x630"


def test_favicon_is_referenced_and_present():
    href = re.search(r'<link rel="icon" href="([^"]+)"', PAGE).group(1)
    assert (SITE / href.lstrip("/").replace("compman/", "")).is_file()


# ---- crawl discovery ----


def test_robots_txt_points_at_the_sitemap():
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots
    assert "Sitemap: https://allbegray.github.io/compman/sitemap.xml" in robots


def test_sitemap_is_valid_xml_and_lists_the_homepage():
    root = ElementTree.fromstring((SITE / "sitemap.xml").read_text(encoding="utf-8"))
    locations = [
        node.text for node in root.iter() if node.tag.endswith("}loc")
    ]
    assert locations == [SITE_URL]
    assert root.tag.endswith("}urlset")


def test_not_found_page_is_noindex_and_points_home():
    page = (SITE / "404.html").read_text(encoding="utf-8")
    assert 'content="noindex' in page
    assert 'href="/compman/"' in page


# ---- document structure ----


def test_page_has_exactly_one_h1_and_a_sane_heading_order():
    headings = re.findall(r"<h([1-6])[ >]", PAGE)
    assert headings.count("1") == 1, "exactly one h1 is required"
    levels = [int(level) for level in headings]
    for previous, current in zip(levels, levels[1:]):
        assert current - previous <= 1, "heading levels must not skip a rank"


def test_every_internal_anchor_link_resolves():
    ids = set(re.findall(r'id="([^"]+)"', PAGE))
    targets = set(re.findall(r'href="#([^"]+)"', PAGE))
    missing = sorted(targets - ids)
    assert missing == [], f"anchors with no matching element: {missing}"


def test_sections_are_labelled_for_assistive_technology():
    for section_id in ("features", "use-cases", "quick-start", "commands", "deploy", "install", "faq"):
        assert f'id="{section_id}"' in PAGE, f"missing section #{section_id}"
        assert f'aria-labelledby="{section_id}-heading"' in PAGE, f"#{section_id} is unlabelled"


# ---- structured data ----


def test_software_application_declares_the_required_fields():
    node = _graph_by_type("SoftwareApplication")
    for field in (
        "name",
        "description",
        "url",
        "softwareVersion",
        "applicationCategory",
        "operatingSystem",
        "license",
        "codeRepository",
        "offers",
    ):
        assert node.get(field), f"SoftwareApplication.{field} is empty"
    assert node["applicationCategory"] == "DeveloperApplication"
    assert node["offers"]["price"] == "0"
    assert node["url"] == SITE_URL


def test_software_version_matches_the_package_version():
    import tomllib

    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert _graph_by_type("SoftwareApplication")["softwareVersion"] == expected, (
        "JSON-LD softwareVersion drifted from pyproject.toml"
    )


def test_faq_json_ld_questions_all_appear_on_the_page():
    questions = re.findall(r"<summary>(.*?)</summary>", PAGE)
    assert len(questions) >= 8, "the FAQ should cover the common long-tail questions"
    for entry in _graph_by_type("FAQPage")["mainEntity"]:
        assert entry["name"] in questions, (
            f"FAQPage question is not visible on the page: {entry['name']}"
        )


def test_faq_json_ld_answers_are_substantive():
    for entry in _graph_by_type("FAQPage")["mainEntity"]:
        answer = entry["acceptedAnswer"]["text"]
        assert len(answer) > 60, f"thin answer for: {entry['name']}"


def test_structured_data_uses_only_schema_org_types():
    allowed = {
        "SoftwareApplication",
        "FAQPage",
        "ComputerLanguage",
        "Organization",
        "Offer",
        "Question",
        "Answer",
    }
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("@type"), str):
                found.add(node["@type"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(_ld_json())
    assert found <= allowed, f"unexpected schema.org types: {found - allowed}"


# ---- content accuracy ----


def test_python_requirement_on_the_page_matches_the_package():
    import tomllib

    requires = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "requires-python"
    ]
    minimum = re.search(r"(\d+\.\d+)", requires).group(1)
    assert f"Python {minimum}+" in PAGE, f"page does not state Python {minimum}+"
    assert "Python 3.10+" not in PAGE, "page claims an unsupported Python version"


def test_repository_links_point_at_the_current_owner():
    assert "aimnext-dev1/compman" not in PAGE
    assert "https://github.com/allbegray/compman" in PAGE


def test_site_assets_use_absolute_paths_so_the_error_page_still_styles():
    # A relative href from /compman/<bad-path>/ would 404 on the 404 page.
    assert 'href="/compman/styles.css"' in PAGE
    assert 'href="/compman/favicon.svg"' in PAGE