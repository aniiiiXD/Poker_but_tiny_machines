/**
 * Per-game vocabulary, shared by the leaderboard, event pages, replays, and
 * the workshop. Poker plays hands; the other games play matches.
 */

const NAMES: Record<string, string> = {
  poker: "Poker",
  bluff: "Bluff",
  uno: "Uno",
  hexchange: "Hexchange",
};

/** Short name for inline copy. Tabs and badges prefer the API's display name. */
export function gameName(id: string | null | undefined): string {
  if (!id) return NAMES.poker;
  return NAMES[id] ?? id.charAt(0).toUpperCase() + id.slice(1);
}

/** What one deal of the game is counted in, plural form. */
export function gameUnit(id: string | null | undefined): string {
  return id === "poker" ? "hands" : "matches";
}

/** Label for the per-table cap on an event: maximum hands / maximum matches. */
export function gameCapLabel(id: string | null | undefined): string {
  return id === "poker" ? "Maximum hands" : "Maximum matches";
}

/** "3 hands" / "1 match" / "2 matches". */
export function unitCount(count: number, id: string | null | undefined): string {
  if (id === "poker") return `${count} hand${count === 1 ? "" : "s"}`;
  return `${count} match${count === 1 ? "" : "es"}`;
}
