# Hexchange starter kit (Stack Theory Hexchange v1)

Hexchange is a hex-island trading game **inspired by the classic trading board
game designed by Klaus Teuber (1995)** — rebuilt from scratch for this arena,
with a structured trade overlay instead of table talk. You produce resources
from dice rolls, build roads, settlements and cities, buy secret development
cards, dodge the robber, and trade with the other seats through bounded
`offer` → `accept` / `reject` / `counter` edges. First seat to 10 victory
points wins.

## Rules (Stack Theory Hexchange v1)

- 3–4 seats on a fixed 19-hex island (4 forest, 4 pasture, 4 wheat, 3 brick,
  3 ore, 1 desert) with seeded number tokens 2–12 (no 7). Both dice are rolled
  each turn; hexes showing the sum produce for adjacent buildings (cities
  produce double). A roll of 7 brings the robber instead.
- Setup: two free settlements + roads each, snake order; the second settlement
  pays one resource per adjacent non-desert hex.
- Costs: road = 1 brick + 1 forest, settlement = 1 brick + 1 forest +
  1 pasture + 1 wheat, city = 2 wheat + 3 ore, dev card = 1 ore + 1 pasture +
  1 wheat. Bank trades are a flat 4:1.
- The trade overlay: at most 3 offers per turn, each answered in seat order by
  `accept` (executes immediately) / `reject` / `counter` (replaces the offer).
  Offer contents are public; hands are not.
- The robber: on a 7 (or a knight), move it to a different hex and optionally
  steal 1 random token from an adjacent seat holding more than 7. The victim
  is public; the token is not.
- Dev deck (25, hidden): 14 knight, 5 VP, 2 monopoly, 2 road-building,
  2 year-of-plenty. One card per turn, never the one just bought. VP cards
  count secretly toward victory.
- First seat to 10 VP (settlement 1, city 2, VP card 1) wins. After 500
  decisions the leaders by VP win and ties share the match point. Invalid
  actions are faults with deterministic fallbacks (end turn / reject).

## What your bot sees

Only public information plus your own things: the board, every building and
road, everyone's resource **counts** (never their types), all trade offers,
the robber, and — privately — your own resource tokens by type and your own
development cards. Never the dev deck order, opponents' hands, or the stolen
token.

## Files

- `agent.py` — a documented starter you can submit as-is, then improve.
- Edit locally, then upload in the Workshop (choose the Hexchange game) or
  push `agent.py` to a connected GitHub repository.

## Strategy ideas

- Grab high-pip intersections early; the distance rule means the good spots
  go first. Wheat and ore fuel cities and dev cards — the late game.
- The overlay is public: watch who offers what, and counter offers that are
  almost good enough. Three offers per turn is a budget — don't burn it on
  hopeless asks.
- A robber on your best hex shuts down production; knights both move it and
  make you someone nobody wants to rob.
- Track the dev deck: every purchase is public even though the card is not —
  when the deck is empty, `buy_dev` just burns a fault.
