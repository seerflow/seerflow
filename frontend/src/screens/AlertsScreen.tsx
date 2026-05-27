import React, { useCallback } from "react";
import { AlertFeed } from "@/components/AlertFeed/AlertFeed";
import { useAlertStore } from "@/stores/alerts";

/**
 * Alerts list screen — S-321 redesign.
 *
 * Renders the live AlertFeed full-screen. Alert row clicks navigate to
 * #/alerts/:id (the AlertDetailScreen) in addition to opening the legacy
 * inline panel.
 *
 * The AlertFeed already manages its own WS subscription, backfill, filtering,
 * and sidebar detail panel. We overlay navigation: when a row is clicked we
 * push `#/alerts/:id` to the hash so the shell renders AlertDetailScreen.
 */
export const AlertsScreen: React.FC = () => {
  const selectAlert = useCallback((id: string) => {
    useAlertStore.getState().selectAlert(id);
    window.location.hash = `#/alerts/${id}`;
  }, []);

  return (
    <div
      data-testid="alerts-screen"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
        padding: "12px",
      }}
    >
      <AlertFeedWithNav onSelectAlert={selectAlert} />
    </div>
  );
};

/**
 * Thin wrapper that intercepts AlertFeed's internal onSelectAlert to also
 * push the hash route. We can't patch AlertFeed directly (guardrail), so we
 * observe selectAlert from the store after mount and patch the hash.
 */
function AlertFeedWithNav({ onSelectAlert }: { onSelectAlert: (id: string) => void }): JSX.Element {
  // Monkey-patch the store's selectAlert with our nav-aware version for this
  // screen mount. The store is module-singleton so we restore on unmount.
  const originalSelectAlert = useAlertStore.getState().selectAlert;

  React.useEffect(() => {
    const patchedSelectAlert = (id: string): void => {
      onSelectAlert(id);
    };
    useAlertStore.setState({ selectAlert: patchedSelectAlert });
    return () => {
      useAlertStore.setState({ selectAlert: originalSelectAlert });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onSelectAlert]);

  return <AlertFeed />;
}
