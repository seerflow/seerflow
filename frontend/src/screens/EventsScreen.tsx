import React from "react";
import { EventStream } from "@/components/EventStream/EventStream";

/**
 * Events screen — P0b interim wrapper.
 * Renders the existing EventStream until the Events redesign (S-325).
 * S-325 will replace the body of this file.
 */
export const EventsScreen: React.FC = () => {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <EventStream />
    </div>
  );
};
