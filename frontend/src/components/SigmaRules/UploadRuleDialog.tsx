// S-151: Upload custom Sigma rule via Sheet (right-side drawer).
//
// Uses Sheet rather than a modal Dialog because the YAML editor needs more
// vertical room than a centred dialog comfortably affords. Validate (dry-run)
// is required before Save is enabled — this catches typos before disk write.
import { useState } from "react";

import { uploadSigmaRule, validateSigmaRule } from "@/lib/sigmaRulesApi";
import type { SigmaRuleValidationResult } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { MonacoYamlEditor } from "./MonacoYamlEditor";

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: (ruleId: string) => void;
}

export function UploadRuleDialog({ open, onClose, onSaved }: Props): JSX.Element {
  const [yamlText, setYamlText] = useState("");
  const [result, setResult] = useState<SigmaRuleValidationResult | null>(null);
  const [busy, setBusy] = useState(false);

  function reset(): void {
    setYamlText("");
    setResult(null);
    setBusy(false);
  }

  function handleClose(): void {
    reset();
    onClose();
  }

  async function handleValidate(): Promise<void> {
    setBusy(true);
    try {
      const r = await validateSigmaRule(yamlText);
      setResult(r);
    } catch (err) {
      setResult({
        valid: false,
        stage: "compile",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  async function handleSave(): Promise<void> {
    setBusy(true);
    try {
      const detail = await uploadSigmaRule(yamlText);
      onSaved(detail.rule_id);
      reset();
      onClose();
    } catch (err) {
      setResult({
        valid: false,
        stage: "compile",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  const canSave = !busy && yamlText.trim().length > 0 && result?.valid === true;

  return (
    <Sheet open={open} onOpenChange={(v) => !v && handleClose()}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-2xl flex flex-col gap-3"
        data-testid="sigma-upload-sheet"
      >
        <SheetHeader>
          <SheetTitle>Upload Sigma rule</SheetTitle>
        </SheetHeader>

        <div className="flex-1 min-h-[360px] rounded border">
          <MonacoYamlEditor
            value={yamlText}
            onChange={setYamlText}
            height="100%"
          />
        </div>

        {result && (
          <div
            // S-349: the valid branch's fixed green fill (no brand var) was
            // migrated to `bg-info/10 text-info` (--info), which flips per theme.
            // The invalid branch already used the `--destructive` brand token — kept.
            className={
              "rounded p-2 text-sm " +
              (result.valid ? "bg-info/10 text-info" : "bg-destructive/10 text-destructive")
            }
            data-testid="sigma-upload-result"
          >
            {result.valid ? (
              <span>
                Valid — title <code>{result.title}</code>, id{" "}
                <code className="font-mono">{result.rule_id}</code>
              </span>
            ) : (
              <span>
                [{result.stage}] {result.message}
                {result.line ? (
                  <>
                    {" "}
                    (line {result.line}
                    {result.column ? `, col ${result.column}` : ""})
                  </>
                ) : null}
              </span>
            )}
          </div>
        )}

        <SheetFooter className="flex flex-row justify-end gap-2">
          <Button variant="ghost" onClick={handleClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="outline"
            onClick={handleValidate}
            disabled={busy || yamlText.trim().length === 0}
          >
            Validate
          </Button>
          <Button onClick={handleSave} disabled={!canSave}>
            Save
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
