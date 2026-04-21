import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { useLayoutStore } from "@/stores/layout";

export function ResetLayoutButton(): JSX.Element {
  const [open, setOpen] = useState(false);
  const reset = useLayoutStore((s) => s.resetToDefault);
  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm" aria-label="Reset layout">
          <RotateCcw className="mr-1 h-4 w-4" /> Reset layout
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Reset dashboard layout?</AlertDialogTitle>
          <AlertDialogDescription>
            This restores the default layout and removes any widgets you added.
            This action cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel aria-label="Cancel">Cancel</AlertDialogCancel>
          <AlertDialogAction
            aria-label="Confirm"
            onClick={() => {
              reset();
              setOpen(false);
            }}
          >
            Reset
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
