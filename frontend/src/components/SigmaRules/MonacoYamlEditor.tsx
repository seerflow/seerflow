// S-151: Lazy Monaco YAML editor wrapper.
//
// Why dynamic import: monaco-editor ships ~500KB minified. Lazy-loading
// keeps it out of the main bundle so users who never open the Sigma rules
// page don't pay for it (S-057 risk register: bundle >1MB target).
import { lazy, Suspense } from "react";
import type { ComponentType } from "react";

interface MonacoEditorProps {
  height?: string | number;
  defaultLanguage?: string;
  value?: string;
  onChange?: (value: string | undefined) => void;
  options?: Record<string, unknown>;
}

const Editor = lazy(async () => {
  const mod = await import("@monaco-editor/react");
  return { default: mod.default as unknown as ComponentType<MonacoEditorProps> };
});

interface Props {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  height?: string;
}

export function MonacoYamlEditor({
  value,
  onChange,
  readOnly = false,
  height = "320px",
}: Props): JSX.Element {
  return (
    <Suspense
      fallback={
        <div
          data-testid="monaco-loading"
          className="flex items-center justify-center text-sm text-muted-foreground"
          style={{ height }}
        >
          Loading editor…
        </div>
      }
    >
      <Editor
        height={height}
        defaultLanguage="yaml"
        value={value}
        onChange={(v: string | undefined) => onChange?.(v ?? "")}
        options={{
          readOnly,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 13,
          wordWrap: "on",
        }}
      />
    </Suspense>
  );
}
