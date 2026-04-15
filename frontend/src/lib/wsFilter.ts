import type { WsFilter, AlertType } from "./types";

type WidgetId = "alerts" | "events";
type Intent = {
  sources?: string[];
  alert_types?: AlertType[];
  template_ids?: number[];
  min_severity?: number;
};

const intents: Record<WidgetId, Intent> = { alerts: {}, events: {} };

function unionStr(a?: string[], b?: string[]): string[] | undefined {
  const set = new Set<string>([...(a ?? []), ...(b ?? [])]);
  return set.size ? [...set] : undefined;
}
function unionAt(a?: AlertType[], b?: AlertType[]): AlertType[] | undefined {
  const set = new Set<AlertType>([...(a ?? []), ...(b ?? [])]);
  return set.size ? [...set] : undefined;
}
function unionNum(a?: number[], b?: number[]): number[] | undefined {
  const set = new Set<number>([...(a ?? []), ...(b ?? [])]);
  return set.size ? [...set] : undefined;
}

function merged(): WsFilter {
  const a = intents.alerts;
  const e = intents.events;
  const sources = unionStr(a.sources, e.sources);
  const alert_types = unionAt(a.alert_types, e.alert_types);
  const template_ids = unionNum(a.template_ids, e.template_ids);
  const sevs = [a.min_severity, e.min_severity].filter(
    (n): n is number => typeof n === "number",
  );
  const out: WsFilter = { type: "filter" };
  if (sources) out.sources = sources;
  if (alert_types) out.alert_types = alert_types;
  if (template_ids) out.template_ids = template_ids;
  if (sevs.length) out.min_severity = Math.min(...sevs);
  return out;
}

export function setIntent(widget: WidgetId, partial: Intent): WsFilter {
  intents[widget] = partial;
  return merged();
}

export function clearIntent(widget: WidgetId): WsFilter {
  intents[widget] = {};
  return merged();
}

export function _resetForTests(): void {
  intents.alerts = {};
  intents.events = {};
}
