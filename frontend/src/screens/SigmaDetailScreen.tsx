import React from "react";
import { ScreenStub } from "./ScreenStub";

/**
 * Sigma rule detail screen — stub.
 * NOTE: This file exists as a seam for S-324 but is NOT currently wired in
 * AppShell. The AppShell routes both #/sigma and #/sigma/:id to SigmaScreen
 * (which handles selection internally). S-324 will wire this file and replace
 * SigmaScreen's internal sub-route handling.
 */
export const SigmaDetailScreen: React.FC = () => {
  return <ScreenStub label="Sigma rule detail" />;
};
