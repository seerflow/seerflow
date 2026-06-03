import React from "react";

/**
 * Loading skeleton for the Overview screen.
 * Hairline shimmer blocks matching the 2-column layout.
 */
export const OverviewSkeleton: React.FC = () => (
  <div data-testid="overview-skeleton" style={{ height: "100%", overflow: "hidden" }}>
    <div
      className="animate-pulse"
      style={{
        display: "grid",
        gridTemplateColumns: "1.7fr 1fr",
        height: "100%",
      }}
    >
      {/* Left column skeleton */}
      <div style={{ borderRight: "1px solid var(--line)" }}>
        {/* KPI strip skeleton */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            borderBottom: "1px solid var(--line)",
          }}
        >
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              style={{
                padding: "18px 20px 16px",
                borderRight: i < 3 ? "1px solid var(--line)" : 0,
              }}
            >
              <div
                data-testid="skeleton-block"
                style={{
                  height: 10,
                  width: "60%",
                  background: "var(--surface-2)",
                  marginBottom: 8,
                }}
              />
              <div
                data-testid="skeleton-block"
                style={{
                  height: 26,
                  width: "80%",
                  background: "var(--surface-2)",
                }}
              />
            </div>
          ))}
        </div>

        {/* Chart skeleton */}
        <div style={{ padding: "20px 24px", borderBottom: "1px solid var(--line)" }}>
          <div
            data-testid="skeleton-block"
            style={{ height: 10, width: "40%", background: "var(--surface-2)", marginBottom: 12 }}
          />
          <div
            data-testid="skeleton-block"
            style={{ height: 180, background: "var(--surface-2)" }}
          />
        </div>

        {/* Alerts skeleton */}
        <div>
          <div style={{ padding: "14px 24px", borderBottom: "1px solid var(--line)" }}>
            <div
              data-testid="skeleton-block"
              style={{ height: 14, width: "30%", background: "var(--surface-2)" }}
            />
          </div>
          {[0, 1, 2, 3, 4].map((i) => (
            <div
              key={i}
              style={{ padding: "11px 24px", borderBottom: "1px solid var(--line)" }}
            >
              <div
                data-testid="skeleton-block"
                style={{ height: 12, width: "80%", background: "var(--surface-2)" }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Right column skeleton */}
      <div>
        <div style={{ padding: "18px 24px", borderBottom: "1px solid var(--line)" }}>
          <div
            data-testid="skeleton-block"
            style={{ height: 14, width: "50%", background: "var(--surface-2)" }}
          />
        </div>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} style={{ padding: "12px 24px", borderBottom: "1px solid var(--line)" }}>
            <div
              data-testid="skeleton-block"
              style={{ height: 36, width: "100%", background: "var(--surface-2)" }}
            />
          </div>
        ))}
      </div>
    </div>
  </div>
);
