# Nutrition engine web

React + TypeScript + Vite frontend for the FastAPI backend in `../api`. Styling is plain CSS with CSS variables; there's no Tailwind and no component library.

## Running it

Requires Node.js 20.19+ or 22.12+ (Vite 7's minimum).

```bash
cd web
npm install
npm run dev        # http://localhost:5173
```

The backend must be running too (see the root README). The app calls `/api/health` on load and shows whether the backend and its database are reachable.

| Command | Does |
|---|---|
| `npm run dev` | Dev server on http://localhost:5173 with hot reload |
| `npm run build` | Type-checks (`tsc -b`, strict) and builds to `dist/` |
| `npm run typecheck` | Type-checks only |
| `npm run preview` | Serves the built `dist/` |

## Configuration

`VITE_API_URL` sets the backend's base URL (default `http://127.0.0.1:8000`). To change it, copy `.env.example` to `.env` and edit it.

The dev server is pinned to `http://localhost:5173` because that's the backend's default `ALLOWED_ORIGINS` entry. If you serve the frontend from another origin (including `http://127.0.0.1:5173`), add it to `ALLOWED_ORIGINS` in the root `.env`. Otherwise the browser blocks the requests.

## Structure

| Path | Purpose |
|---|---|
| `src/api.ts` | Typed client for every backend endpoint. Its types mirror `api/models.py`, and every call throws `ApiError` (`status`, `detail`) on failure, including 422 validation errors. |
| `src/styles/tokens.css` | Design tokens: colors (including one per macro), spacing scale (4/8/12/16/24/32/48), radii (10px panels, 6px controls), type settings. |
| `src/styles/global.css` | Base styles, visible `:focus-visible` rings, the `.number` style for big macro figures, and a global `prefers-reduced-motion` rule. |
| `src/App.tsx` | The current screen: backend and database status. |

## Design rules

- **Type:** Archivo, loaded from Google Fonts with its width (`wdth`) and weight axes. Body text is normal width at weight 400/500. Big macro numbers use the `.number` class: condensed (`font-stretch: 75%`), weight 800, tabular figures.
- **Text:** sentence case everywhere, with no all-caps labels and no monospace.
- **Color:** use the tokens, never raw hex values in components. Every text/background pairing in the tokens meets WCAG AA (lowest: muted on `--surface-2`, 4.54:1).
- **Accessibility:** keyboard focus is always visible, and motion is disabled when the user prefers reduced motion. Color is never the only signal: status dots are paired with words.
