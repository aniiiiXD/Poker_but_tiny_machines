# Stack Theory visual system

## Identity
A competitive poster wrapped around a tangible game object. Warm bone surfaces, dense red typography, vermilion felt, lacquer rails, ivory cards and striped chips. The main line is “CAN YOUR AI GAMBLE SMART?” The product is a student code competition using simulated chips.

## Navigation
Exactly three public destinations: Arena (`/`), Sponsors (`/sponsors`), Contact (`/contact`). The logo returns to Arena. Account, team, workshop, events, standings, rules and replays remain accessible through contextual arena tools, not global navigation.

## Typography and color
Self-hosted licensed Barlow for body and forms; Barlow Condensed 800 for display. Display uses deliberate three-line composition with protected text space. Bone `#f1ece2`, red `#bd1a25`, ink `#171513`. Internal code editors use monospace on lacquer; replay cards remain ivory on deep red felt. No gradient text, glass panels or invented traction.

## Scene
Procedural Three.js meshes, canvas card textures, soft contact shadow, layered oval rails and physical cards. Pointer parallax is restrained. Deal is an illustrative card animation, separate from real practice games. Pause/Resume motion supports keyboard input and system reduced-motion changes; dealing is immediate when motion is disabled. Offscreen rendering pauses, device pixel ratio is capped, geometry and listeners are disposed on route change. `/?view=static` exposes the same fallback used when WebGL is unavailable.

Hero visual, updated: a live Monte Carlo equity terminal (`EquityPanel.tsx`) - two random hands, streets opening card by card, ASCII win/tie/lose bars and an equity sparkline, computed in the visitor's browser with a real 7-card evaluator. No canned numbers. The Three.js table (`TableScene.tsx`) is retired from the hero but kept in the repo.

## Responsive behavior
Desktop uses an asymmetric poster with the table to the right. Large screens scale both typography and canvas; mobile stacks typography, deliberately cropped table, controls and CTA. Primary navigation stays visible at phone widths. The Three.js scene loads as a separate chunk; Sponsors and Contact do not initialize a 3D renderer.

## Research and review
Study notes and original direction: REDESIGN.md. Research sources: [Lusion](https://lusion.co), [Igloo](https://www.igloo.inc), [Bruno Simon](https://bruno-simon.com). Original geometry and artwork, no copied site assets. Hyde GLM generated substantive scene and page code; local coordinators reviewed and corrected it. Provenance is in review/hyde-scene.md and review/hyde-pages.md. Astra reviewed rendered desktop and mobile artifacts and required iteration before clearing the composition.
