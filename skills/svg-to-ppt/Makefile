SHELL := /bin/bash

SVG ?= templates/ppt_shape_starter.svg
SVG_FILES := templates/ppt_shape_starter.svg examples/api_profile_filtering_flow.svg examples/svg-to-ppt-map.svg
REQUIRED_FILES := skills/svg-to-ppt/SKILL.md CHECKLIST.md README.md $(SVG_FILES)
MAX_FONT_SIZE ?= 28
MAX_TEXT_CHARS ?= 90
STRICT_TEXT_FIT ?= 1
MIN_LINE_GAP ?= 18

.PHONY: help validate validate-ps check-files check-svg-safety validate-svg

help:
	@echo "Targets:"
	@echo "  make validate                  # Validate skill file structure + SVG safety rules"
	@echo "  make validate-ps               # Validate using PowerShell script (Windows-friendly)"
	@echo "  make check-files               # Ensure required skill files exist"
	@echo "  make check-svg-safety          # Run SVG rule checks across bundled SVGs"
	@echo "  make validate-svg SVG=path     # Validate one SVG file"
	@echo "Notes:"
	@echo "  Makefile recipes use bash. On Windows, run in Git Bash/WSL"
	@echo "  or use: powershell -ExecutionPolicy Bypass -File scripts/validate-svg.ps1"
	@echo "Variables:"
	@echo "  MAX_FONT_SIZE=$(MAX_FONT_SIZE)  # Fail if any font-size exceeds this value"
	@echo "  MAX_TEXT_CHARS=$(MAX_TEXT_CHARS) # Max characters per text segment before wrap is required"
	@echo "  STRICT_TEXT_FIT=$(STRICT_TEXT_FIT) # 1=fail on long text (default), 0=warn only"
	@echo "  MIN_LINE_GAP=$(MIN_LINE_GAP) # Minimum y-distance between consecutive tspan lines"

validate: check-files check-svg-safety
	@echo "OK: svg-to-ppt skill validation passed"

validate-ps:
	@powershell -NoProfile -ExecutionPolicy Bypass -File scripts/validate-svg.ps1 -MaxFontSize $(MAX_FONT_SIZE) -MaxTextChars $(MAX_TEXT_CHARS) -StrictTextFit $(STRICT_TEXT_FIT) -MinLineGap $(MIN_LINE_GAP)

check-files:
	@for f in $(REQUIRED_FILES); do \
		if [ ! -f "$$f" ]; then \
			echo "Missing required file: $$f"; \
			exit 1; \
		fi; \
	done
	@echo "OK: required files present"

check-svg-safety:
	@for f in $(SVG_FILES); do \
		$(MAKE) --no-print-directory validate-svg SVG="$$f" || exit 1; \
	done
	@echo "OK: SVG safety checks passed"

validate-svg:
	@if [ ! -f "$(SVG)" ]; then \
		echo "SVG file not found: $(SVG)"; \
		exit 1; \
	fi
	@if grep -Eq '<marker\\b|marker-(start|mid|end)=' "$(SVG)"; then \
		echo "FAIL $(SVG): marker-based arrows are not allowed"; \
		exit 1; \
	fi
	@if grep -Eq '<path\\b' "$(SVG)"; then \
		echo "FAIL $(SVG): <path> found (prefer primitives: rect/line/polygon/text)"; \
		exit 1; \
	fi
	@if grep -Eqi '(xlink:href|href)=\"https?://' "$(SVG)"; then \
		echo "FAIL $(SVG): external references are not allowed"; \
		exit 1; \
	fi
	@if grep -Eo 'font-size="[0-9]+' "$(SVG)" | sed 's/[^0-9]//g' | awk -v max="$(MAX_FONT_SIZE)" 'BEGIN{bad=0} {if ($$1 > max) {bad=1}} END{exit bad}'; then \
		:; \
	else \
		echo "FAIL $(SVG): font-size exceeds MAX_FONT_SIZE=$(MAX_FONT_SIZE)"; \
		exit 1; \
	fi
	@if awk -v max="$(MAX_TEXT_CHARS)" 'BEGIN{bad=0} {line=$$0; while (match(line, />[^<]+</)) {segment=substr(line, RSTART+1, RLENGTH-2); gsub(/^[[:space:]]+|[[:space:]]+$$/, "", segment); if (length(segment) > max) bad=1; line=substr(line, RSTART+RLENGTH)}} END{exit bad}' "$(SVG)"; then \
		:; \
	else \
		if [ "$(STRICT_TEXT_FIT)" = "1" ]; then \
			echo "FAIL $(SVG): very long text segment found; wrap text or widen box (MAX_TEXT_CHARS=$(MAX_TEXT_CHARS))"; \
			exit 1; \
		else \
			echo "WARN $(SVG): long text segment found; consider wrapping or widening box (MAX_TEXT_CHARS=$(MAX_TEXT_CHARS))"; \
		fi; \
	fi
	@echo "OK $(SVG)"
