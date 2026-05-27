// S-151: Lazy Monaco YAML editor wrapper.
//
// Why dynamic import: monaco-editor ships ~3 MB minified. Lazy-loading
// keeps it out of the main bundle so users who never open the Sigma rules
// page don't pay for it (S-057 risk register: bundle >1MB target).
//
// S-154 Task 7 (airgap): point @monaco-editor/react's loader at the
// locally-bundled monaco instance. Without this call the loader fetches
// monaco from a jsdelivr CDN at component-mount time, which breaks
// airgapped / strict-CSP deployments. `loader.config` is idempotent —
// we call it inside the lazy chunk's factory so the heavy `monaco-editor`
// module stays out of the main bundle and only loads on first mount.
import { lazy, Suspense } from "react";
import type { ComponentType } from "react";
import { loader } from "@monaco-editor/react";

import { SEERFLOW_MONACO_THEME, buildMonacoTheme } from "./monacoTheme";

// S-327 (AC1): the @monaco-editor/react lifecycle hooks receive the live
// `monaco` namespace. We only touch `editor.defineTheme` / `editor.setTheme`,
// so a structural type keeps this wrapper free of a hard monaco-editor type
// import (the heavy module stays in the lazy chunk).
interface MonacoNamespace {
  editor: {
    defineTheme: (name: string, data: unknown) => void;
    setTheme: (name: string) => void;
  };
}

interface MonacoEditorProps {
  height?: string | number;
  defaultLanguage?: string;
  value?: string;
  onChange?: (value: string | undefined) => void;
  options?: Record<string, unknown>;
  theme?: string;
  beforeMount?: (monaco: MonacoNamespace) => void;
  onMount?: (editor: unknown, monaco: MonacoNamespace) => void;
}

const Editor = lazy(async () => {
  const [mod, monaco] = await Promise.all([
    import("@monaco-editor/react"),
    import("monaco-editor"),
  ]);
  loader.config({ monaco });
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
        theme={SEERFLOW_MONACO_THEME}
        beforeMount={(monaco: MonacoNamespace) =>
          monaco.editor.defineTheme(SEERFLOW_MONACO_THEME, buildMonacoTheme())
        }
        onMount={(_editor: unknown, monaco: MonacoNamespace) =>
          monaco.editor.setTheme(SEERFLOW_MONACO_THEME)
        }
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
