param(
    [string[]]$SvgFiles = @(
        "templates/ppt_shape_starter.svg",
        "examples/api_profile_filtering_flow.svg",
        "examples/svg-to-ppt-map.svg"
    ),
    [int]$MaxFontSize = 28,
    [int]$MaxTextChars = 90,
    [int]$StrictTextFit = 1,
    [int]$MinLineGap = 18,
    [double]$TextWidthFactor = 0.56,
    [int]$HorizontalPadding = 16,
    [int]$MinRectWidthForFitCheck = 260
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Split-Path -Parent $scriptRoot
Set-Location $skillRoot

function Fail([string]$Message) {
    Write-Host "FAIL: $Message" -ForegroundColor Red
    exit 1
}

function Get-AttrNumber($node, [string]$name, [double]$defaultValue) {
    if (-not $node.Attributes[$name]) {
        return $defaultValue
    }
    $raw = $node.Attributes[$name].Value
    $m = [regex]::Match($raw, '[-+]?[0-9]*\.?[0-9]+')
    if ($m.Success) {
        return [double]$m.Value
    }
    return $defaultValue
}

foreach ($svg in $SvgFiles) {
    if (-not (Test-Path $svg)) {
        Fail "Missing SVG file: $svg"
    }

    $raw = Get-Content $svg -Raw

    if ($raw -match '<marker\b|marker-(start|mid|end)=') {
        Fail "$svg contains marker-based arrows"
    }

    if ($raw -match '<path\b') {
        Fail "$svg contains <path>; use rect/line/polygon/text"
    }

    if ($raw -match '(xlink:href|href)="https?://') {
        Fail "$svg contains external references"
    }

    $fontMatches = [regex]::Matches($raw, 'font-size="(\d+)')
    foreach ($m in $fontMatches) {
        $size = [int]$m.Groups[1].Value
        if ($size -gt $MaxFontSize) {
            Fail "$svg has font-size $size > MaxFontSize=$MaxFontSize"
        }
    }

    [xml]$doc = $raw
    $rectNodes = $doc.SelectNodes("//*[local-name()='rect']")
    $textNodes = $doc.SelectNodes("//*[local-name()='text']")

    $rects = @()
    foreach ($rect in $rectNodes) {
        $x = Get-AttrNumber $rect 'x' 0
        $y = Get-AttrNumber $rect 'y' 0
        $w = Get-AttrNumber $rect 'width' 0
        $h = Get-AttrNumber $rect 'height' 0
        if ($w -gt 0 -and $h -gt 0) {
            $rects += [PSCustomObject]@{
                X = $x
                Y = $y
                W = $w
                H = $h
                Right = $x + $w
                Bottom = $y + $h
                Area = $w * $h
            }
        }
    }

    foreach ($textNode in $textNodes) {
        $defaultX = Get-AttrNumber $textNode 'x' 0
        $defaultY = Get-AttrNumber $textNode 'y' 0
        $defaultFont = Get-AttrNumber $textNode 'font-size' 12
        $lines = @()

        $tspans = $textNode.SelectNodes("./*[local-name()='tspan']")
        if ($tspans.Count -gt 0) {
            foreach ($tspan in $tspans) {
                $lineText = $tspan.InnerText.Trim()
                if ([string]::IsNullOrWhiteSpace($lineText)) {
                    continue
                }
                $lineX = Get-AttrNumber $tspan 'x' $defaultX
                $lineY = Get-AttrNumber $tspan 'y' $defaultY
                $lineFont = Get-AttrNumber $tspan 'font-size' $defaultFont
                $lineAnchor = if ($tspan.Attributes['text-anchor']) { $tspan.Attributes['text-anchor'].Value } elseif ($textNode.Attributes['text-anchor']) { $textNode.Attributes['text-anchor'].Value } else { 'start' }
                $lines += [PSCustomObject]@{ Text = $lineText; X = $lineX; Y = $lineY; Font = $lineFont; Anchor = $lineAnchor }
            }
        } else {
            $lineText = $textNode.InnerText.Trim()
            if (-not [string]::IsNullOrWhiteSpace($lineText)) {
                $lineAnchor = if ($textNode.Attributes['text-anchor']) { $textNode.Attributes['text-anchor'].Value } else { 'start' }
                $lines += [PSCustomObject]@{ Text = $lineText; X = $defaultX; Y = $defaultY; Font = $defaultFont; Anchor = $lineAnchor }
            }
        }

        if ($lines.Count -gt 1) {
            $sorted = $lines | Sort-Object Y
            for ($i = 1; $i -lt $sorted.Count; $i++) {
                $gap = $sorted[$i].Y - $sorted[$i - 1].Y
                if ($gap -lt $MinLineGap) {
                    Fail "$svg has tight line spacing ($gap px) below MinLineGap=$MinLineGap"
                }
            }
        }

        foreach ($line in $lines) {
            if ($line.Text.Length -gt $MaxTextChars) {
                if ($StrictTextFit -eq 1) {
                    Fail "$svg has text segment longer than MaxTextChars=${MaxTextChars}: '$($line.Text)'"
                }
                Write-Host "WARN: $svg has long text segment (>$MaxTextChars chars): '$($line.Text)'" -ForegroundColor Yellow
            }

            $candidateRects = $rects | Where-Object {
                $line.X -ge $_.X -and $line.X -le $_.Right -and $line.Y -ge $_.Y -and $line.Y -le $_.Bottom
            } | Sort-Object Area

            if ($candidateRects.Count -gt 0) {
                $container = $candidateRects[0]
                if ($container.W -lt $MinRectWidthForFitCheck) {
                    continue
                }

                $estimatedWidth = $line.Text.Length * $line.Font * $TextWidthFactor
                $projectedRight = switch ($line.Anchor) {
                    'middle' { $line.X + ($estimatedWidth / 2) }
                    'end' { $line.X }
                    default { $line.X + $estimatedWidth }
                }

                if (($projectedRight + $HorizontalPadding) -gt $container.Right) {
                    if ($StrictTextFit -eq 1) {
                        Fail "$svg line appears to overflow right edge; wrap text or widen box: '$($line.Text)'"
                    }
                    Write-Host "WARN: $svg line may overflow right edge: '$($line.Text)'" -ForegroundColor Yellow
                }
            }
        }
    }

    Write-Host "OK: $svg" -ForegroundColor Green
}

Write-Host "Validation complete" -ForegroundColor Green
