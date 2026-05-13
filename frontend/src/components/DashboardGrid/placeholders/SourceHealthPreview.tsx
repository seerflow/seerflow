import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function SourceHealthPreview(): JSX.Element {
  return (
    <Card className="h-full min-h-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          Source health
          <span className="rounded bg-muted px-1.5 py-0.5 text-xs uppercase tracking-wide text-muted-foreground">
            Preview
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Live source health coming in a later story.
      </CardContent>
    </Card>
  );
}
