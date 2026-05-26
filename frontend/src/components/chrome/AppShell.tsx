import React, { useCallback, useEffect, useState } from "react";
import { WsProvider } from "@/components/WsProvider";
import { DisconnectedBanner } from "@/components/DisconnectedBanner";
import { Toaster } from "@/components/ui/sonner";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { parseHash, serializeHash, ROUTE_REGISTRY, type RouteName } from "@/lib/routes";

// ── Screen imports ────────────────────────────────────────────────────────────
import { OverviewScreen } from "@/screens/OverviewScreen";
import { AlertsScreen } from "@/screens/AlertsScreen";
import { AlertDetailScreen } from "@/screens/AlertDetailScreen";
import { EventsScreen } from "@/screens/EventsScreen";
import { EntitiesScreen } from "@/screens/EntitiesScreen";
import { AttackScreen } from "@/screens/AttackScreen";
import { SigmaScreen } from "@/screens/SigmaScreen";
import { HuntScreen } from "@/screens/HuntScreen";
import { ReceiversScreen } from "@/screens/ReceiversScreen";
import { ModelsScreen } from "@/screens/ModelsScreen";
import { SettingsScreen } from "@/screens/SettingsScreen";

type RouteMatch = ReturnType<typeof parseHash>;

function routeToLabel(route: RouteName): string {
  return ROUTE_REGISTRY.find((r) => r.route === route)?.label ?? route;
}

function renderScreen(match: RouteMatch): React.ReactElement {
  switch (match.route) {
    case "overview":
      return <OverviewScreen />;
    case "alerts":
      return match.id ? <AlertDetailScreen /> : <AlertsScreen />;
    case "events":
      return <EventsScreen />;
    case "entities":
      return <EntitiesScreen />;
    case "attack":
      return <AttackScreen />;
    case "hunt":
      return <HuntScreen />;
    case "sigma":
      return <SigmaScreen />;
    case "receivers":
      return <ReceiversScreen />;
    case "models":
      return <ModelsScreen />;
    case "settings":
      return <SettingsScreen />;
    default:
      return <OverviewScreen />;
  }
}

function getBreadcrumb(match: RouteMatch): string[] {
  const label = routeToLabel(match.route);
  if ("id" in match && match.id) {
    return ["Workspace", label, match.id];
  }
  if ("uuid" in match && match.uuid) {
    return ["Workspace", label, match.uuid.slice(0, 8) + "…"];
  }
  return ["Workspace", label];
}

/**
 * The full dashboard shell.
 * Grid: 212px sidebar + 1fr main; 52px topbar + 1fr content.
 * Manages hash-based routing; delegates screen rendering to src/screens/.
 * Later stories replace only their own screen file — never touch this shell.
 */
export const AppShell: React.FC = () => {
  const [routeMatch, setRouteMatch] = useState<RouteMatch>(() =>
    parseHash(window.location.hash),
  );

  const syncHash = useCallback(() => {
    const match = parseHash(window.location.hash);
    setRouteMatch(match);

    // If the legacy hash format resolves to a new route, normalise it so
    // future navigations use the canonical form (avoids double-normalise loop
    // because we only rewrite if the hash actually differs).
    const canonical = serializeHash(match);
    const current = window.location.hash || "#";
    if (current !== canonical && current !== "#" + canonical.slice(1)) {
      // Only normalise non-empty legacy hashes (coverage, sigma-rules, entity=)
      if (current !== "#" && current !== "") {
        window.history.replaceState(null, "", canonical);
      }
    }
  }, []);

  useEffect(() => {
    syncHash();
    window.addEventListener("hashchange", syncHash);
    window.addEventListener("popstate", syncHash);
    return () => {
      window.removeEventListener("hashchange", syncHash);
      window.removeEventListener("popstate", syncHash);
    };
  }, [syncHash]);

  const handleNavigate = useCallback((route: RouteName) => {
    const hash = serializeHash({ route });
    window.location.hash = hash;
  }, []);

  return (
    <WsProvider>
      <div
        style={{
          width: "100vw",
          height: "100vh",
          display: "grid",
          gridTemplateColumns: "212px 1fr",
          gridTemplateRows: "52px 1fr",
          gridTemplateAreas: '"sidebar topbar" "sidebar main"',
          background: "var(--bg)",
          fontFamily: "var(--font-display)",
          color: "var(--text)",
          overflow: "hidden",
        }}
      >
        <Sidebar activeRoute={routeMatch.route} onNavigate={handleNavigate} />
        <Topbar breadcrumb={getBreadcrumb(routeMatch)} />
        <div
          style={{
            gridArea: "main",
            overflow: "hidden",
            borderTop: "1px solid var(--line)",
            borderLeft: "1px solid var(--line)",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <DisconnectedBanner />
          {renderScreen(routeMatch)}
        </div>
      </div>
      <Toaster richColors position="bottom-right" />
    </WsProvider>
  );
};
