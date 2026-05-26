/**
 * Hash route registry for the Seerflow dashboard shell.
 *
 * Generalises lib/hash.ts into a full route registry supporting the new
 * #/<route> format while preserving backward compat with legacy deep-link
 * formats (#entity=<uuid>, #coverage, #sigma-rules).
 *
 * No router dependency — pure hash parsing.
 */

export type RouteName =
  | "overview"
  | "alerts"
  | "events"
  | "entities"
  | "attack"
  | "hunt"
  | "sigma"
  | "receivers"
  | "models"
  | "settings";

export type NavGroup = "Monitor" | "Investigate" | "Configure";

export interface RouteMatch {
  route: RouteName;
  /** Present for #/alerts/:id */
  id?: string;
  /** Present for #/entities/:uuid or legacy #entity=<uuid> */
  uuid?: string;
}

export interface RouteEntry {
  route: RouteName;
  label: string;
  group: NavGroup;
  /** SVG path string for the 14×14 hairline icon */
  iconPath: string;
}

// Icon paths from the DBSidebar mockup (dashboard.jsx)
export const ROUTE_REGISTRY: RouteEntry[] = [
  // Monitor
  {
    route: "overview",
    label: "Overview",
    group: "Monitor",
    iconPath: "M3 12h4l2-6 4 12 2-6h4",
  },
  {
    route: "alerts",
    label: "Alerts",
    group: "Monitor",
    iconPath: "M12 3v9M12 16v.01M6 19h12l-6-10z",
  },
  {
    route: "events",
    label: "Events",
    group: "Monitor",
    iconPath: "M3 6h18M3 12h18M3 18h12",
  },
  // Investigate
  {
    route: "entities",
    label: "Entities",
    group: "Investigate",
    iconPath:
      "M6 18a3 3 0 100-6 3 3 0 000 6zM18 8a3 3 0 100-6 3 3 0 000 6zM18 22a3 3 0 100-6 3 3 0 000 6zM9 16l6-4M9 16l6 4",
  },
  {
    route: "attack",
    label: "ATT&CK",
    group: "Investigate",
    iconPath: "M3 4h18v4H3zM3 10h18v4H3zM3 16h18v4H3z",
  },
  {
    route: "hunt",
    label: "Hunt",
    group: "Investigate",
    iconPath: "M9 9.5a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM3 3l9.5 9.5",
  },
  // Configure
  {
    route: "sigma",
    label: "Sigma rules",
    group: "Configure",
    iconPath: "M5 4h14v16l-7-3-7 3z",
  },
  {
    route: "receivers",
    label: "Receivers",
    group: "Configure",
    iconPath: "M4 10h16M4 14h16M4 6h16M4 18h16",
  },
  {
    route: "models",
    label: "Models",
    group: "Configure",
    iconPath: "M3 12c4 0 4-6 8-6s4 6 8 6",
  },
  {
    route: "settings",
    label: "Settings",
    group: "Configure",
    iconPath: "M12 9a3 3 0 100 6 3 3 0 000-6zM12 2v3M12 19v3M2 12h3M19 12h3",
  },
];

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Parse a window.location.hash string into a RouteMatch.
 *
 * Supports:
 *   New format:  #/overview, #/alerts, #/alerts/:id, #/entities/:uuid, #/sigma/:id, …
 *   Legacy:      #entity=<uuid>[&range=…], #coverage, #sigma-rules
 *   Default:     "" | "#" → overview
 */
export function parseHash(hash: string): RouteMatch {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;

  // Empty → default
  if (!raw || raw === "/") return { route: "overview" };

  // ── New #/<route>[/<id>] format ─────────────────────────────────────────
  if (raw.startsWith("/")) {
    const parts = raw.slice(1).split("/");
    const routeKey = parts[0] as RouteName;
    const param = parts[1] ?? undefined;

    switch (routeKey) {
      case "overview":
        return { route: "overview" };
      case "alerts":
        return param ? { route: "alerts", id: param } : { route: "alerts" };
      case "events":
        return { route: "events" };
      case "entities":
        return param ? { route: "entities", uuid: param } : { route: "entities" };
      case "attack":
        return { route: "attack" };
      case "hunt":
        return { route: "hunt" };
      case "sigma":
        return param ? { route: "sigma", id: param } : { route: "sigma" };
      case "receivers":
        return { route: "receivers" };
      case "models":
        return { route: "models" };
      case "settings":
        return { route: "settings" };
      default:
        return { route: "overview" };
    }
  }

  // ── Legacy format backward compat ──────────────────────────────────────

  // Legacy #coverage → attack
  if (raw === "coverage") return { route: "attack" };

  // Legacy #sigma-rules → sigma
  if (raw === "sigma-rules") return { route: "sigma" };

  // Legacy #entity=<uuid>[&...] → entities with uuid
  if (raw.includes("entity=") || raw.includes("&entity=")) {
    const params = new URLSearchParams(raw);
    const uuid = params.get("entity");
    if (uuid && UUID_RE.test(uuid)) {
      return { route: "entities", uuid };
    }
  }

  // Unknown → default overview
  return { route: "overview" };
}

/**
 * Serialise a RouteMatch back to a hash string (new format).
 */
export function serializeHash(match: RouteMatch): string {
  const { route } = match;

  switch (route) {
    case "alerts":
      return match.id ? `#/alerts/${match.id}` : "#/alerts";
    case "entities":
      return match.uuid ? `#/entities/${match.uuid}` : "#/entities";
    case "sigma":
      return match.id ? `#/sigma/${match.id}` : "#/sigma";
    default:
      return `#/${route}`;
  }
}
