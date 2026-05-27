import React from "react";
import { cn } from "@/lib/utils";

export interface AiExplanationProps {
  /** LLM-generated narrative text. Empty string during loading or when unavailable. */
  narrative: string;
  /** Technique/tactic IDs used as provenance sources (e.g. ["T1003.001", "TA0006"]). */
  provenance: string[];
  /** Show skeleton placeholder instead of content. */
  loading?: boolean;
  className?: string;
}

/**
 * AI Explanation block — narrative text + provenance chip row.
 * Renders a skeleton when loading=true.
 */
export const AiExplanation: React.FC<AiExplanationProps> = ({
  narrative,
  provenance,
  loading = false,
  className,
}) => (
  <section
    aria-label="AI explanation"
    className={cn("flex flex-col gap-2", className)}
  >
    {loading ? (
      <>
        <div
          data-testid="ai-explanation-skeleton"
          className="h-3 w-full animate-pulse bg-surface-2 border border-line"
        />
        <div
          data-testid="ai-explanation-skeleton"
          className="h-3 w-4/5 animate-pulse bg-surface-2 border border-line"
        />
        <div
          data-testid="ai-explanation-skeleton"
          className="h-3 w-3/5 animate-pulse bg-surface-2 border border-line"
        />
      </>
    ) : (
      <p className="text-sm text-text-2 leading-relaxed">{narrative}</p>
    )}

    {!loading && provenance.length > 0 && (
      <div className="flex flex-wrap gap-1">
        {provenance.map((tag) => (
          <span
            key={tag}
            data-testid="provenance-tag"
            className="sf-mono border border-line bg-surface-2 text-text-3 px-[5px] py-[1px] text-[10px] leading-none"
          >
            {tag}
          </span>
        ))}
      </div>
    )}
  </section>
);
