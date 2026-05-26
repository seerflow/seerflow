/**
 * S-318: App entry point — replaced with sidebar-nav shell.
 *
 * The full shell logic (routing, sidebar, topbar, screen registry) lives in
 * AppShell. This file is intentionally thin — its only job is to mount the
 * shell. Do not add logic here; add it to AppShell or the relevant screen file.
 */
import { AppShell } from "@/components/chrome/AppShell";

export default function App() {
  return <AppShell />;
}
