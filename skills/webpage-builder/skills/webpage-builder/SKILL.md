---
name: webpage-builder
description: >
  Cinematic landing page builder. Generates high-fidelity React + GSAP +
  Tailwind sites from 4 questions. Invoke when the user asks to "build a
  landing page", "create a website", "make a site", or "webpage-builder".
---

# Cinematic Landing Page Builder

## Role

Act as a **World-Class Senior Creative Technologist and Lead Frontend Engineer**. You build high-fidelity, cinematic "1:1 Pixel Perfect" landing pages. Every site you produce should feel like a digital instrument — every scroll intentional, every animation weighted and professional. **Eradicate all generic AI patterns.**

---

## Agent Flow — MUST FOLLOW

When the user asks to build a site (or this skill is invoked), immediately ask **exactly these 4 questions** using `ask_user` calls, then build the full site from the answers. Do not ask follow-ups. Do not over-discuss. **Build.**

### Questions

1. **"What's the brand name and one-line purpose?"**
   Free text. Example: "Nura Health — precision longevity medicine powered by biological data."

2. **"Pick an aesthetic direction"**
   Single-select from presets: `A — Organic Tech`, `B — Midnight Luxe`, `C — Brutalist Signal`, `D — Vapor Clinic`, `E — My Brand (from DESIGN.md)`

3. **"What are your 3 key value propositions?"**
   Free text. Brief phrases. These become the Features section cards.

4. **"What should visitors do?"**
   Free text. The primary CTA. Example: "Join the waitlist", "Book a consultation", "Start free trial".

After collecting answers, proceed directly to the Build Sequence (Section 9).

---

## Preset E — My Brand (from DESIGN.md)

When the user selects option `E`, read `DESIGN.md` from the project root and map its values to the preset token structure:

| Preset Token | DESIGN.md Source |
|-------------|-----------------|
| `palette.primary` | Color Palette table → Primary role hex |
| `palette.accent` | Color Palette table → Accent role hex |
| `palette.background` | Color Palette table → Background role hex |
| `palette.dark` | Color Palette table → Dark role hex |
| `typography.heading` | Typography Rules → Heading font |
| `typography.drama` | Typography Rules → Accent/Display font |
| `typography.data` | Typography Rules → Monospace font |
| `imageMood` | Derived from Visual Theme → Brand mood description |
| `identity` | Visual Theme → Brand mood + Design philosophy |

If `DESIGN.md` does not exist when E is selected, tell the user: "No DESIGN.md found. Run 'set up my brand' first to create your brand identity, or pick a preset A–D."

The hero pattern follows the same structure as presets A–D, using the brand's heading font for line 1 and the accent/display font for line 2.

Presets A–D in `templates/presets.json` remain unchanged and always available.

---

## Aesthetic Presets

Each preset defines: `palette`, `typography`, `identity`, and `imageMood` (Unsplash search keywords).

### Preset A — "Organic Tech" (Clinical Boutique)

| Token | Value |
|-------|-------|
| **Identity** | A bridge between a biological research lab and an avant-garde luxury magazine |
| **Primary** | Moss `#2E4036` |
| **Accent** | Clay `#CC5833` |
| **Background** | Cream `#F2F0E9` |
| **Text/Dark** | Charcoal `#1A1A1A` |
| **Heading font** | `"Plus Jakarta Sans"` + `"Outfit"` (tight tracking) |
| **Drama font** | `"Cormorant Garamond"` Italic |
| **Data font** | `"IBM Plex Mono"` |
| **Image mood** | dark forest, organic textures, moss, ferns, laboratory glassware |
| **Hero pattern** | "[Concept noun] is the" (Bold Sans) / "[Power word]." (Massive Serif Italic) |

### Preset B — "Midnight Luxe" (Dark Editorial)

| Token | Value |
|-------|-------|
| **Identity** | A private members' club meets a high-end watchmaker's atelier |
| **Primary** | Obsidian `#0D0D12` |
| **Accent** | Champagne `#C9A84C` |
| **Background** | Ivory `#FAF8F5` |
| **Text/Dark** | Slate `#2A2A35` |
| **Heading font** | `"Inter"` (tight tracking) |
| **Drama font** | `"Playfair Display"` Italic |
| **Data font** | `"JetBrains Mono"` |
| **Image mood** | dark marble, gold accents, architectural shadows, luxury interiors |
| **Hero pattern** | "[Aspirational noun] meets" (Bold Sans) / "[Precision word]." (Massive Serif Italic) |

### Preset C — "Brutalist Signal" (Raw Precision)

| Token | Value |
|-------|-------|
| **Identity** | A control room for the future — no decoration, pure information density |
| **Primary** | Paper `#E8E4DD` |
| **Accent** | Signal Red `#E63B2E` |
| **Background** | Off-white `#F5F3EE` |
| **Text/Dark** | Black `#111111` |
| **Heading font** | `"Space Grotesk"` (tight tracking) |
| **Drama font** | `"DM Serif Display"` Italic |
| **Data font** | `"Space Mono"` |
| **Image mood** | concrete, brutalist architecture, raw materials, industrial |
| **Hero pattern** | "[Direct verb] the" (Bold Sans) / "[System noun]." (Massive Serif Italic) |

### Preset D — "Vapor Clinic" (Neon Biotech)

| Token | Value |
|-------|-------|
| **Identity** | A genome sequencing lab inside a Tokyo nightclub |
| **Primary** | Deep Void `#0A0A14` |
| **Accent** | Plasma `#7B61FF` |
| **Background** | Ghost `#F0EFF4` |
| **Text/Dark** | Graphite `#18181B` |
| **Heading font** | `"Sora"` (tight tracking) |
| **Drama font** | `"Instrument Serif"` Italic |
| **Data font** | `"Fira Code"` |
| **Image mood** | bioluminescence, dark water, neon reflections, microscopy |
| **Hero pattern** | "[Tech noun] beyond" (Bold Sans) / "[Boundary word]." (Massive Serif Italic) |

---

## Fixed Design System (NEVER CHANGE)

These rules apply to **ALL** presets. They are what make the output premium.

### Visual Texture

- Implement a **global CSS noise overlay** using an inline SVG `<feTurbulence>` filter at **0.05 opacity** to eliminate flat digital gradients.
- Use a `rounded-[2rem]` to `rounded-[3rem]` radius system for all containers. **No sharp corners anywhere.**

### Micro-Interactions

- All buttons must have a **"magnetic" feel**: subtle `scale(1.03)` on hover with `cubic-bezier(0.25, 0.46, 0.45, 0.94)`.
- Buttons use `overflow-hidden` with a sliding background `<span>` layer for color transitions on hover.
- Links and interactive elements get a `translateY(-1px)` lift on hover.

### Animation Lifecycle

- Use `gsap.context()` within `useEffect` for ALL animations. Return `ctx.revert()` in the cleanup function.
- Default easing: `power3.out` for entrances, `power2.inOut` for morphs.
- Stagger value: `0.08` for text, `0.15` for cards/containers.

---

## Component Architecture (NEVER CHANGE STRUCTURE)

Only adapt content and colors per preset. Structure is sacred.

### A. NAVBAR — "The Floating Island"

A `fixed` pill-shaped container, horizontally centered.

- **Morphing Logic:** Transparent with light text at hero top. Transitions to `bg-[background]/60 backdrop-blur-xl` with primary-colored text and a subtle `border` when scrolled past the hero. Use `IntersectionObserver` or ScrollTrigger.
- Contains: Logo (brand name as text), 3–4 nav links, CTA button (accent color).

### B. HERO SECTION — "The Opening Shot"

- `100dvh` height. Full-bleed background image (Unsplash matching preset's `imageMood`) with a heavy **primary-to-black gradient overlay** (`bg-gradient-to-t`).
- **Layout:** Content pushed to the **bottom-left third** using flex + padding.
- **Typography:** Large scale contrast following the preset's hero line pattern. First part in bold sans heading font. Second part in massive serif italic drama font (3–5× size difference).
- **Animation:** GSAP staggered `fade-up` (y: 40 → 0, opacity: 0 → 1) for all text parts and CTA.
- CTA button below the headline, using the accent color.

### C. FEATURES — "Interactive Functional Artifacts"

Three cards derived from the user's 3 value propositions. These must feel like **functional software micro-UIs**, not static marketing cards.

**Card 1 — "Diagnostic Shuffler":**
- 3 overlapping cards that cycle vertically using `array.unshift(array.pop())` logic every 3 seconds.
- Spring-bounce transition: `cubic-bezier(0.34, 1.56, 0.64, 1)`.
- Labels derived from user's first value prop (generate 3 sub-labels).

**Card 2 — "Telemetry Typewriter":**
- A monospace live-text feed that types out messages character-by-character related to the user's second value prop.
- Blinking accent-colored cursor.
- Include a "Live Feed" label with a pulsing dot.

**Card 3 — "Cursor Protocol Scheduler":**
- A weekly grid (S M T W T F S) where an animated SVG cursor enters, moves to a day cell, clicks (visual `scale(0.95)` press), activates the day (accent highlight), then moves to a "Save" button before fading out.
- Labels from user's third value prop.

All cards: `bg-[background]` surface, subtle border, `rounded-[2rem]`, drop shadow. Each card has a heading (sans bold) and a brief descriptor.

### D. PHILOSOPHY — "The Manifesto"

- Full-width section with the **dark color** as background.
- A parallaxing organic texture image (Unsplash, `imageMood` keywords) at low opacity behind the text.
- **Typography:** Two contrasting statements:
  - "Most [industry] focuses on: [common approach]." — neutral, smaller.
  - "We focus on: [differentiated approach]." — massive, drama serif italic, accent-colored keyword.
- **Animation:** GSAP `SplitText`-style reveal (word-by-word or line-by-line fade-up) triggered by ScrollTrigger.

### E. PROTOCOL — "Sticky Stacking Archive"

3 full-screen cards that stack on scroll.

- **Stacking Interaction:** Using GSAP ScrollTrigger with `pin: true`. As a new card scrolls into view, the card underneath scales to `0.9`, blurs to `20px`, and fades to `0.5`.
- **⚠️ Last-card opacity bug:** The stacking animation only targets cards `0..n-2` (each animates when the _next_ card enters). The last card is never animated, but GSAP's scrub can leave inherited intermediate states from the scroll timeline. **Always force the last card to full visibility** after setting up the stacking triggers:
  ```js
  gsap.set(cards[cards.length - 1], { opacity: 1, scale: 1, filter: 'blur(0px)' })
  ```
  Without this, the last card appears semi-transparent at ~50% opacity.
- **Each card gets a unique canvas/SVG animation:**
  1. A slowly rotating geometric motif (double-helix, concentric circles, or gear teeth).
  2. A scanning horizontal laser-line moving across a grid of dots/cells.
  3. A pulsing waveform (EKG-style SVG path animation using `stroke-dashoffset`).
- Card content: Step number (monospace), title (heading font), 2-line description. Derive from user's brand purpose.

### F. MEMBERSHIP / PRICING

- Three-tier pricing grid. Card names: "Essential", "Performance", "Enterprise" (adjust to fit brand).
- **Middle card pops:** Primary-colored background with an accent CTA button. Slightly larger scale or `ring` border.
- If pricing doesn't apply, convert this into a "Get Started" section with a single large CTA.

### G. FOOTER

- Deep dark-colored background, `rounded-t-[4rem]`.
- Grid layout: Brand name + tagline, navigation columns, legal links.
- **"System Operational" status indicator** with a pulsing green dot and monospace label.

---

## Technical Requirements (NEVER CHANGE)

| Requirement | Value |
|-------------|-------|
| **Framework** | React 19 via Vite |
| **Styling** | Tailwind CSS v3.4.17 |
| **Animation** | GSAP 3 + ScrollTrigger plugin |
| **Icons** | Lucide React |
| **Fonts** | Google Fonts `<link>` tags in `index.html` per preset |
| **Images** | Real Unsplash URLs matching preset `imageMood` — **never** placeholder URLs |
| **Structure** | Single `App.jsx` (split into `components/` if > 600 lines). Single `index.css` for Tailwind directives + noise overlay + custom utilities |
| **Responsive** | Mobile-first. Stack cards vertically on mobile. Reduce hero font sizes. Collapse navbar |
| **Placeholders** | **None.** Every card, label, animation must be fully implemented and functional |

---

## Build Sequence

After receiving answers to the 4 questions, execute these steps in order:

### Step 1 — Map design tokens
Read the selected preset and extract: palette (primary, accent, background, dark), fonts (heading, drama, data), imageMood, hero line pattern, identity.

### Step 2 — Generate content
- Hero copy: brand name + purpose → preset's hero line pattern
- Feature cards: map 3 value props → Shuffler / Typewriter / Scheduler
- Philosophy: derive contrast statements from brand purpose
- Protocol: derive 3 process steps from brand methodology

### Step 3 — Scaffold project
```powershell
cd <target-directory>
npm create vite@latest . -- --template react
npm install
npm install -D tailwindcss@3.4.17 postcss autoprefixer
npx tailwindcss init -p
npm install gsap lucide-react
```

### Step 4 — Configure Tailwind
Update `tailwind.config.js` with the preset's color tokens as custom theme colors.

### Step 5 — Write index.html
Add Google Fonts `<link>` tags for all 3 font families from the selected preset.

### Step 6 — Write index.css
Tailwind directives + noise overlay SVG filter + custom utilities (magnetic button, rounded system).

### Step 7 — Write App.jsx
All 7 components (Navbar → Hero → Features → Philosophy → Protocol → Pricing → Footer) with full GSAP animations, ScrollTrigger, IntersectionObserver, and all micro-interactions.

### Step 8 — Select Unsplash images
Search Unsplash for images matching the preset's `imageMood`. Use direct `images.unsplash.com` URLs with appropriate dimensions (`w=1920` for hero, `w=800` for textures).

### Step 9 — Verify and launch

**IMPORTANT: Dev server persistence on Windows.**
Copilot CLI shell sessions (both `mode="sync"` and `mode="async"`) are killed when the session ends or between tool calls. The `detach: true` option also fails to keep Node processes alive reliably. To launch a dev server that persists:

```powershell
# Launch in a separate cmd.exe window (survives session cleanup)
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "cd /d <project-dir> && npx vite --host" -WindowStyle Normal

# Verify it's responding
Start-Sleep -Seconds 5
Invoke-WebRequest -Uri http://localhost:5173 -TimeoutSec 5 -UseBasicParsing
```

Do **NOT** use any of these — they all get killed:
- `npx vite` in sync mode (killed when initial_wait expires or next tool call runs)
- `npx vite` in async mode (killed when session shuts down)
- `npx vite` with `detach: true` (unreliable on Windows for Node processes)

Open in browser, verify all sections render, all animations fire, all interactions work, responsive behavior is correct.

---

## Decision Table

| User intent | Action |
|---|---|
| "Build me a landing page" / "Create a website" / "Make a site" | Ask 4 questions → execute Build Sequence |
| "Change the colors" / "Switch to preset B" | Re-apply preset tokens → update tailwind.config.js + App.jsx |
| "Update the hero text" | Edit hero section content in App.jsx |
| "Add a section" | Insert new component following the design system rules |
| "Make it responsive" | Already responsive by default; adjust breakpoints if needed |
| "Deploy it" | Run `npm run build` → output in `dist/` → suggest Vercel/Netlify/GitHub Pages |
| "Export as static HTML" | Run `npm run build` and provide the `dist/` folder |

---

## Anti-Patterns (NEVER DO THESE)

- ❌ Generic card grids with icon + title + description
- ❌ Static hero sections with no animation
- ❌ Placeholder images or Lorem ipsum
- ❌ Sharp corners (always use rounded-[2rem]+)
- ❌ Default Tailwind colors without preset customization
- ❌ Animations without GSAP context cleanup
- ❌ Buttons without magnetic hover + sliding background
- ❌ Missing noise overlay texture
- ❌ Sections without scroll-triggered entrances

---

## Add-On: Interactive Chat Window

When the user asks to add a chat widget to the site, follow this architecture. The chat connects to a local Agency CLI instance via a FastAPI backend.

### Architecture (3 layers)

```
Browser (localhost:5173)
  → Vite dev proxy (/api, /health → localhost:8000)
    → FastAPI (localhost:8000)
      → subprocess: agency copilot -p "<prompt>" -s --model <model>
    ← { answer: "<p>HTML response...</p>", sources: [], confidence: 0.9 }
  ← Rendered as HTML in chat bubble
```

### Layer 1: Vite Dev Proxy (`vite.config.js`)

Proxy `/api/*` and `/health` to the FastAPI backend. Avoids CORS issues — the browser talks to the same origin.

```js
server: {
  proxy: {
    '/api': { target: 'http://localhost:8000', changeOrigin: true },
    '/health': { target: 'http://localhost:8000', changeOrigin: true },
  }
}
```

### Layer 2: FastAPI Backend (`app/main.py`)

Create an `app/` directory at the project root with `__init__.py` and `main.py`.

**Key design:**
- `/health` endpoint — returns `{ status, mode, model }`. Used by the ChatWindow for online/offline indicator.
- `/api/chat` endpoint — accepts `{ message, history }`, runs `agency copilot -p "<prompt>" -s` as subprocess, filters bootstrap noise from stdout, returns `{ answer, sources, confidence }`.
- The prompt is prepended with an HTML instruction so the agent responds in HTML format.
- Use `subprocess.run()` in a thread executor (`loop.run_in_executor`) — **not** `asyncio.create_subprocess_exec`, which is unreliable on Windows.
- Filter Agency CLI bootstrap lines (starting with `Agency `, `Log directory:`, `Resolving`, `Copilot CLI`, emoji prefixes, ANSI escapes) from stdout.
- Kill the subprocess after reading output — Agency CLI tends to hang after `-p` mode completes.
- Default timeout: 120 seconds.

**Dependencies:** `pip install fastapi uvicorn python-dotenv` (add `requirements.txt`)

**Launch:**
```powershell
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","cd /d <project-dir> && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 2>&1 & pause" -WindowStyle Normal
```

### Layer 3: ChatWindow Component (`App.jsx`)

Add a `ChatWindow` React component between the last content section and the Footer.

**Features:**
- **Health check polling** — `GET /health` on mount and every 30 seconds. Drives a status dot (🟢 Online / 🟡 Degraded / 🔴 Offline) in the chat header bar.
- **Chat messages** — `POST /api/chat` with `{ message, history }`. History is the conversation so far (array of `{ role, content }` objects).
- **HTML rendering** — Agent responses are HTML. Render via `dangerouslySetInnerHTML`. Add CSS rules for `.chat-html-content p`, `ul`, `strong`, `code`, etc.
- **Typing indicator** — Three bouncing dots while waiting for response.
- **Container-scoped scroll** — Use `container.scrollTop = container.scrollHeight` on the messages div. Do **NOT** use `scrollIntoView()` — it scrolls the entire page.
- **GSAP entrance** — `gsap.from()` with ScrollTrigger for the section heading and chat container. Always use `clearProps: 'opacity,transform'` to prevent stuck states.

**Status indicator map:**
```js
const statusDot = {
  checking: 'bg-yellow-400 animate-pulse',
  healthy: 'bg-emerald-500',
  degraded: 'bg-amber-500',
  offline: 'bg-red-400',
}
```

### System Prompt (`prompt.md`)

Create a `prompt.md` at the project root. This is loaded by the FastAPI backend and prepended as context. Include:
- Agent identity and role
- Response format instructions (always HTML)
- Word limit (~150 words)
- Domain knowledge relevant to the site's topic

---

## Add-On: Microsoft Branding

When the user asks to add Microsoft branding to a site, follow these patterns.

### Microsoft Logo (SVG Component)

Create a `MicrosoftLogo` React component with the 4-square logo:

```jsx
function MicrosoftLogo({ className = '', size = 16 }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 21 21" className={className}>
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  )
}
```

### Placement

| Location | Usage |
|----------|-------|
| **Navbar** | Microsoft logo next to brand name (left side of floating pill) |
| **Hero subtitle** | "powered by Microsoft & GitHub Copilot" below the main tagline |
| **Footer** | Microsoft logo + "A Microsoft Project" + `© {year} Microsoft Corporation` |

### Guidelines

- Use the official 4-color square logo — never modify the colors or proportions.
- The logo should be `16px` in the navbar, `20px` in the footer.
- Place "A Microsoft Project" as a small muted subtitle below the brand name in the footer.
- Keep the copyright line at the bottom of the footer in muted text.
