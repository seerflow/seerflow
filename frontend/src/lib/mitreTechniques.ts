/**
 * MITRE ATT&CK technique id → human name + tactic.
 *
 * Source: MITRE ATT&CK Enterprise Matrix (https://attack.mitre.org/)
 * Version: Enterprise v15.1 (2024-04-23)
 * Last updated: 2026-05-28 (S-338)
 *
 * Curated subset rather than the full STIX bundle (~3 MB JSON) — this map
 * covers:
 *   - Every technique id used by the bundled Sigma rule corpus under
 *     `src/seerflow/sigma/rules/**` (pinned in mitreTechniques.test.ts).
 *   - The demo-generator tokens used by the dashboard fixtures
 *     (`frontend/src/lib/demo/generators.ts`).
 *   - The most common heads across initial-access, persistence,
 *     privilege-escalation, defense-evasion, credential-access,
 *     lateral-movement, discovery, and exfiltration tactics.
 *
 * Lookup is case-insensitive via {@link getTechniqueName} / {@link getTechnique}.
 * Unknown ids return null so callers can render the bare token (e.g. `T9999.999`).
 *
 * To extend: add an entry below following the existing
 * `"Tnnnn(.sss)?": { name, tactic }` shape, then re-run
 * `npm run test src/lib/mitreTechniques.test.ts` to validate.
 *
 * `name` is the MITRE-published technique title verbatim (including the
 * `Parent: Sub` pattern for sub-techniques). `tactic` uses the
 * lowercase-hyphenated form (e.g. `"credential-access"`) so the rail's
 * uppercased pill render stays compact.
 */

export interface MitreTechnique {
  readonly name: string;
  readonly tactic?: string;
}

export const MITRE_TECHNIQUES: Readonly<Record<string, MitreTechnique>> = {
  // ── Initial Access ────────────────────────────────────────────────────────
  T1078: { name: "Valid Accounts", tactic: "initial-access" },
  T1189: { name: "Drive-by Compromise", tactic: "initial-access" },
  T1190: { name: "Exploit Public-Facing Application", tactic: "initial-access" },
  T1195: { name: "Supply Chain Compromise", tactic: "initial-access" },
  T1199: { name: "Trusted Relationship", tactic: "initial-access" },
  T1566: { name: "Phishing", tactic: "initial-access" },
  "T1566.001": { name: "Phishing: Spearphishing Attachment", tactic: "initial-access" },
  "T1566.002": { name: "Phishing: Spearphishing Link", tactic: "initial-access" },

  // ── Execution ─────────────────────────────────────────────────────────────
  T1053: { name: "Scheduled Task/Job", tactic: "execution" },
  "T1053.003": { name: "Scheduled Task/Job: Cron", tactic: "execution" },
  T1059: { name: "Command and Scripting Interpreter", tactic: "execution" },
  "T1059.001": {
    name: "Command and Scripting Interpreter: PowerShell",
    tactic: "execution",
  },
  "T1059.003": {
    name: "Command and Scripting Interpreter: Windows Command Shell",
    tactic: "execution",
  },
  "T1059.004": {
    name: "Command and Scripting Interpreter: Unix Shell",
    tactic: "execution",
  },
  T1204: { name: "User Execution", tactic: "execution" },
  "T1204.001": { name: "User Execution: Malicious Link", tactic: "execution" },
  "T1204.002": { name: "User Execution: Malicious File", tactic: "execution" },
  T1569: { name: "System Services", tactic: "execution" },

  // ── Persistence ───────────────────────────────────────────────────────────
  T1098: { name: "Account Manipulation", tactic: "persistence" },
  T1136: { name: "Create Account", tactic: "persistence" },
  "T1136.001": { name: "Create Account: Local Account", tactic: "persistence" },
  T1505: { name: "Server Software Component", tactic: "persistence" },
  "T1505.003": {
    name: "Server Software Component: Web Shell",
    tactic: "persistence",
  },
  T1543: { name: "Create or Modify System Process", tactic: "persistence" },
  "T1543.002": {
    name: "Create or Modify System Process: Systemd Service",
    tactic: "persistence",
  },
  T1546: { name: "Event Triggered Execution", tactic: "persistence" },
  "T1546.004": {
    name: "Event Triggered Execution: Unix Shell Configuration Modification",
    tactic: "persistence",
  },
  T1574: { name: "Hijack Execution Flow", tactic: "persistence" },
  "T1574.006": {
    name: "Hijack Execution Flow: Dynamic Linker Hijacking",
    tactic: "persistence",
  },

  // ── Privilege Escalation ─────────────────────────────────────────────────
  T1068: { name: "Exploitation for Privilege Escalation", tactic: "privilege-escalation" },
  T1548: { name: "Abuse Elevation Control Mechanism", tactic: "privilege-escalation" },

  // ── Defense Evasion ──────────────────────────────────────────────────────
  T1027: { name: "Obfuscated Files or Information", tactic: "defense-evasion" },
  T1036: { name: "Masquerading", tactic: "defense-evasion" },
  T1070: { name: "Indicator Removal", tactic: "defense-evasion" },
  "T1070.002": {
    name: "Indicator Removal: Clear Linux or Mac System Logs",
    tactic: "defense-evasion",
  },
  "T1070.003": {
    name: "Indicator Removal: Clear Command History",
    tactic: "defense-evasion",
  },
  T1140: { name: "Deobfuscate/Decode Files or Information", tactic: "defense-evasion" },
  T1221: { name: "Template Injection", tactic: "defense-evasion" },
  T1562: { name: "Impair Defenses", tactic: "defense-evasion" },
  "T1562.004": {
    name: "Impair Defenses: Disable or Modify System Firewall",
    tactic: "defense-evasion",
  },
  "T1562.006": {
    name: "Impair Defenses: Indicator Blocking",
    tactic: "defense-evasion",
  },

  // ── Credential Access ────────────────────────────────────────────────────
  T1003: { name: "OS Credential Dumping", tactic: "credential-access" },
  "T1003.001": {
    name: "OS Credential Dumping: LSASS Memory",
    tactic: "credential-access",
  },
  "T1003.008": {
    name: "OS Credential Dumping: /etc/passwd and /etc/shadow",
    tactic: "credential-access",
  },
  T1110: { name: "Brute Force", tactic: "credential-access" },
  "T1110.001": { name: "Brute Force: Password Guessing", tactic: "credential-access" },
  "T1110.003": { name: "Brute Force: Password Spraying", tactic: "credential-access" },
  T1552: { name: "Unsecured Credentials", tactic: "credential-access" },
  "T1552.001": {
    name: "Unsecured Credentials: Credentials In Files",
    tactic: "credential-access",
  },
  T1555: { name: "Credentials from Password Stores", tactic: "credential-access" },

  // ── Discovery ────────────────────────────────────────────────────────────
  T1033: { name: "System Owner/User Discovery", tactic: "discovery" },
  T1057: { name: "Process Discovery", tactic: "discovery" },
  T1082: { name: "System Information Discovery", tactic: "discovery" },
  T1083: { name: "File and Directory Discovery", tactic: "discovery" },
  T1087: { name: "Account Discovery", tactic: "discovery" },

  // ── Lateral Movement ─────────────────────────────────────────────────────
  T1021: { name: "Remote Services", tactic: "lateral-movement" },
  "T1021.001": { name: "Remote Services: Remote Desktop Protocol", tactic: "lateral-movement" },
  "T1021.002": { name: "Remote Services: SMB/Windows Admin Shares", tactic: "lateral-movement" },
  "T1021.004": { name: "Remote Services: SSH", tactic: "lateral-movement" },
  T1550: { name: "Use Alternate Authentication Material", tactic: "lateral-movement" },
  "T1550.002": {
    name: "Use Alternate Authentication Material: Pass the Hash",
    tactic: "lateral-movement",
  },

  // ── Collection ───────────────────────────────────────────────────────────
  T1005: { name: "Data from Local System", tactic: "collection" },

  // ── Command and Control ──────────────────────────────────────────────────
  T1071: { name: "Application Layer Protocol", tactic: "command-and-control" },
  "T1071.001": {
    name: "Application Layer Protocol: Web Protocols",
    tactic: "command-and-control",
  },
  "T1071.004": {
    name: "Application Layer Protocol: DNS",
    tactic: "command-and-control",
  },
  T1090: { name: "Proxy", tactic: "command-and-control" },
  T1102: { name: "Web Service", tactic: "command-and-control" },
  "T1102.002": { name: "Web Service: Bidirectional Communication", tactic: "command-and-control" },
  T1568: { name: "Dynamic Resolution", tactic: "command-and-control" },
  "T1568.002": {
    name: "Dynamic Resolution: Domain Generation Algorithms",
    tactic: "command-and-control",
  },
  T1571: { name: "Non-Standard Port", tactic: "command-and-control" },
  T1572: { name: "Protocol Tunneling", tactic: "command-and-control" },

  // ── Exfiltration ─────────────────────────────────────────────────────────
  T1048: { name: "Exfiltration Over Alternative Protocol", tactic: "exfiltration" },
  "T1048.003": {
    name: "Exfiltration Over Alternative Protocol: Exfiltration Over Unencrypted Non-C2 Protocol",
    tactic: "exfiltration",
  },
  T1567: { name: "Exfiltration Over Web Service", tactic: "exfiltration" },

  // ── Impact ───────────────────────────────────────────────────────────────
  T1486: { name: "Data Encrypted for Impact", tactic: "impact" },
  T1496: { name: "Resource Hijacking", tactic: "impact" },
  T1565: { name: "Data Manipulation", tactic: "impact" },
  "T1565.001": { name: "Data Manipulation: Stored Data Manipulation", tactic: "impact" },

  // ── Reconnaissance ───────────────────────────────────────────────────────
  T1595: { name: "Active Scanning", tactic: "reconnaissance" },
  "T1595.002": { name: "Active Scanning: Vulnerability Scanning", tactic: "reconnaissance" },

  // ── Resource Development ─────────────────────────────────────────────────
  T1587: { name: "Develop Capabilities", tactic: "resource-development" },
  T1588: { name: "Obtain Capabilities", tactic: "resource-development" },
  "T1588.001": { name: "Obtain Capabilities: Malware", tactic: "resource-development" },
};

/**
 * Resolve a MITRE technique id (case-insensitive) to its
 * {name, tactic} record. Returns null for unknown ids — callers
 * should render the bare token as a safe fallback.
 */
export function getTechnique(id: string): MitreTechnique | null {
  if (!id) return null;
  const key = id.toUpperCase();
  return MITRE_TECHNIQUES[key] ?? null;
}

/**
 * Convenience wrapper around {@link getTechnique} that returns just the
 * published technique name, or null on miss.
 */
export function getTechniqueName(id: string): string | null {
  return getTechnique(id)?.name ?? null;
}
