"""
Shared configuration loader for Office skills.
Reads branding, templates, and per-format rules from agentconfig.json.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULTS = {
    "branding": {
        "company": "Your Company",
        "program": "",
        "primary_color": "#0078D4",
        "accent_color": "#50E6FF",
        "dark_color": "#1B1A19",
        "font_heading": "Segoe UI Semibold",
        "font_body": "Segoe UI",
        "logo_path": None,
    },
    "powerpoint": {
        "default_template": None,
        "slide_width_inches": 13.333,
        "slide_height_inches": 7.5,
        "title_font_size_pt": 28,
        "body_font_size_pt": 18,
        "footer_text": "",
        "slide_numbers": True,
        "max_bullets_per_slide": 6,
    },
    "excel": {
        "header_fill_color": "#0078D4",
        "header_font_color": "#FFFFFF",
        "stripe_color": "#F3F2F1",
        "default_font": "Segoe UI",
        "default_font_size_pt": 11,
        "auto_filter": True,
        "freeze_header_row": True,
    },
    "word": {
        "default_template": None,
        "heading_font": "Segoe UI Semibold",
        "body_font": "Segoe UI",
        "body_font_size_pt": 11,
        "page_margin_inches": 1.0,
        "header_text": "",
        "footer_text": "",
    },
    "output_dir": "output",
}


@dataclass
class BrandingConfig:
    company: str = "Your Company"
    program: str = ""
    primary_color: str = "#0078D4"
    accent_color: str = "#50E6FF"
    dark_color: str = "#1B1A19"
    font_heading: str = "Segoe UI Semibold"
    font_body: str = "Segoe UI"
    logo_path: Optional[str] = None


@dataclass
class PowerPointConfig:
    default_template: Optional[str] = None
    slide_width_inches: float = 13.333
    slide_height_inches: float = 7.5
    title_font_size_pt: int = 28
    body_font_size_pt: int = 18
    footer_text: str = ""
    slide_numbers: bool = True
    max_bullets_per_slide: int = 6


@dataclass
class ExcelConfig:
    header_fill_color: str = "#0078D4"
    header_font_color: str = "#FFFFFF"
    stripe_color: str = "#F3F2F1"
    default_font: str = "Segoe UI"
    default_font_size_pt: int = 11
    auto_filter: bool = True
    freeze_header_row: bool = True


@dataclass
class WordConfig:
    default_template: Optional[str] = None
    heading_font: str = "Segoe UI Semibold"
    body_font: str = "Segoe UI"
    body_font_size_pt: int = 11
    page_margin_inches: float = 1.0
    header_text: str = ""
    footer_text: str = ""


@dataclass
class OfficeConfig:
    branding: BrandingConfig = field(default_factory=BrandingConfig)
    powerpoint: PowerPointConfig = field(default_factory=PowerPointConfig)
    excel: ExcelConfig = field(default_factory=ExcelConfig)
    word: WordConfig = field(default_factory=WordConfig)
    output_dir: str = "output"


def _merge(defaults: dict, overrides: dict) -> dict:
    """Deep merge overrides into defaults."""
    result = dict(defaults)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(config_path: Optional[str] = None) -> OfficeConfig:
    """Load office configuration from agentconfig.json."""
    if config_path is None:
        config_path = PROJECT_ROOT / "agentconfig.json"
    else:
        config_path = Path(config_path)

    raw = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            full = json.load(f)
            raw = full.get("office", {})

    merged = _merge(DEFAULTS, raw)

    # Resolve relative paths against project root
    branding = BrandingConfig(**merged["branding"])
    if branding.logo_path and not os.path.isabs(branding.logo_path):
        branding.logo_path = str(PROJECT_ROOT / branding.logo_path)

    pptx = PowerPointConfig(**merged["powerpoint"])
    if pptx.default_template and not os.path.isabs(pptx.default_template):
        pptx.default_template = str(PROJECT_ROOT / pptx.default_template)

    word = WordConfig(**merged["word"])
    if word.default_template and not os.path.isabs(word.default_template):
        word.default_template = str(PROJECT_ROOT / word.default_template)

    output_dir = merged.get("output_dir", "output")
    if not os.path.isabs(output_dir):
        output_dir = str(PROJECT_ROOT / output_dir)

    return OfficeConfig(
        branding=branding,
        powerpoint=pptx,
        excel=ExcelConfig(**merged["excel"]),
        word=word,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    cfg = load_config()
    print(json.dumps({
        "branding": cfg.branding.__dict__,
        "powerpoint": cfg.powerpoint.__dict__,
        "excel": cfg.excel.__dict__,
        "word": cfg.word.__dict__,
        "output_dir": cfg.output_dir,
    }, indent=2))
