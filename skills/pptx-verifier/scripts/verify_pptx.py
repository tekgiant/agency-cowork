#!/usr/bin/env python3
"""PowerPoint verification script — checks structural integrity and common issues."""

import json
import sys
import zipfile
from pathlib import Path


def verify_pptx(filepath: str) -> dict:
    """Run structural verification on a .pptx file. Returns a results dict."""
    path = Path(filepath)
    results = {
        "file": str(path),
        "passed": True,
        "checks": [],
    }

    # Check file exists
    if not path.exists():
        results["passed"] = False
        results["checks"].append({"name": "file_exists", "passed": False, "detail": "File not found"})
        return results

    # Check file header — detect DRM-wrapped OLE2
    with open(path, "rb") as f:
        header = f.read(4)

    if header == b"\xd0\xcf\x11\xe0":
        results["passed"] = False
        results["checks"].append({
            "name": "file_format",
            "passed": False,
            "detail": "OLE2 header detected — file is DRM-wrapped. Strip DRM before verification.",
        })
        return results

    if header != b"\x50\x4b\x03\x04":
        results["passed"] = False
        results["checks"].append({
            "name": "file_format",
            "passed": False,
            "detail": f"Unknown file header: {header.hex()}. Expected ZIP (OOXML).",
        })
        return results

    results["checks"].append({"name": "file_format", "passed": True, "detail": "Valid OOXML ZIP"})

    # Check ZIP integrity
    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            if bad:
                results["passed"] = False
                results["checks"].append({
                    "name": "zip_integrity",
                    "passed": False,
                    "detail": f"Corrupt entry in ZIP: {bad}",
                })
            else:
                results["checks"].append({"name": "zip_integrity", "passed": True, "detail": "All ZIP entries valid"})

            # Count slides
            slide_files = [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            slide_count = len(slide_files)
            results["slide_count"] = slide_count
            results["checks"].append({
                "name": "slide_count",
                "passed": slide_count > 0,
                "detail": f"{slide_count} slide(s) found",
            })

            # Check each slide for empty text
            import xml.etree.ElementTree as ET

            ns = {
                "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            }

            empty_slides = []
            placeholder_text_found = []

            for slide_file in sorted(slide_files):
                with zf.open(slide_file) as sf:
                    tree = ET.parse(sf)
                    root = tree.getroot()

                    # Find all text runs
                    texts = []
                    for t_elem in root.iter(f"{{{ns['a']}}}t"):
                        if t_elem.text and t_elem.text.strip():
                            texts.append(t_elem.text.strip())

                    slide_num = slide_file.replace("ppt/slides/slide", "").replace(".xml", "")

                    if not texts:
                        empty_slides.append(slide_num)

                    # Check for placeholder text
                    for text in texts:
                        lower = text.lower()
                        if any(ph in lower for ph in ["lorem ipsum", "title here", "[insert", "click to add", "placeholder"]):
                            placeholder_text_found.append({"slide": slide_num, "text": text[:80]})

            if empty_slides:
                results["checks"].append({
                    "name": "empty_slides",
                    "passed": False,
                    "detail": f"Slides with no text content: {', '.join(empty_slides)}",
                })
                results["passed"] = False
            else:
                results["checks"].append({
                    "name": "empty_slides",
                    "passed": True,
                    "detail": "All slides have text content",
                })

            if placeholder_text_found:
                results["checks"].append({
                    "name": "placeholder_text",
                    "passed": False,
                    "detail": f"Placeholder text found: {json.dumps(placeholder_text_found)}",
                })
                results["passed"] = False
            else:
                results["checks"].append({
                    "name": "placeholder_text",
                    "passed": True,
                    "detail": "No placeholder text found",
                })

    except zipfile.BadZipFile:
        results["passed"] = False
        results["checks"].append({
            "name": "zip_integrity",
            "passed": False,
            "detail": "File is not a valid ZIP — likely corrupted by bad hex colors or encoding.",
        })
        return results

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_pptx.py <path-to-pptx> [expected-slide-count]")
        sys.exit(1)

    filepath = sys.argv[1]
    try:
        expected_slides = int(sys.argv[2]) if len(sys.argv) > 2 else None
    except ValueError:
        print(f"Warning: ignoring non-numeric expected-slide-count: {sys.argv[2]}")
        expected_slides = None

    results = verify_pptx(filepath)

    # Check expected slide count if provided
    if expected_slides is not None and "slide_count" in results:
        match = results["slide_count"] == expected_slides
        results["checks"].append({
            "name": "expected_slide_count",
            "passed": match,
            "detail": f"Expected {expected_slides}, found {results['slide_count']}",
        })
        if not match:
            results["passed"] = False

    # Print results
    status = "PASSED" if results["passed"] else "FAILED"
    print(f"\n{'='*60}")
    print(f"PowerPoint Verification: {status}")
    print(f"File: {results['file']}")
    print(f"{'='*60}")

    for check in results["checks"]:
        icon = "✓" if check["passed"] else "✗"
        print(f"  {icon} {check['name']}: {check['detail']}")

    print(f"{'='*60}\n")

    # Exit with code 1 if any check failed
    sys.exit(0 if results["passed"] else 1)


if __name__ == "__main__":
    main()
