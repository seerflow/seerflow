/** Standard Lockheed Martin Cyber Kill Chain® mapped to MITRE ATT&CK tactics. */
export interface KillChainStageDefinition {
  /** MITRE ATT&CK tactic ID, e.g. "TA0043" */
  taId: string;
  label: string;
}

export const KILL_CHAIN_STAGES: KillChainStageDefinition[] = [
  { taId: "TA0043", label: "Reconnaissance" },
  { taId: "TA0042", label: "Resource Development" },
  { taId: "TA0001", label: "Initial Access" },
  { taId: "TA0002", label: "Execution" },
  { taId: "TA0003", label: "Persistence" },
  { taId: "TA0006", label: "Credential Access" },
  { taId: "TA0040", label: "Impact" },
];
