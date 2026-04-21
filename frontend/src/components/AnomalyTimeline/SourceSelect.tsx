import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const ALL = "__all__";

interface Props {
  value: string | null;
  options: string[];
  onChange: (s: string | null) => void;
}

export function SourceSelect({ value, options, onChange }: Props): JSX.Element {
  return (
    <Select
      value={value ?? ALL}
      onValueChange={(v) => onChange(v === ALL ? null : v)}
    >
      <SelectTrigger aria-label="Source filter" className="w-40 h-7 text-xs">
        <SelectValue placeholder="All sources">
          {value === null ? "All sources" : value}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {/* Radix SelectItem renders role="option" and owns aria-selected via
            its controlled state (one option's aria-selected="true" at a time),
            which is the spec-correct attribute for listbox items. The plan's
            "aria-pressed" requirement targeted button-style chips; the actual
            selection-state signal here comes from Radix + the visible
            ItemIndicator checkmark. */}
        <SelectItem value={ALL}>All sources</SelectItem>
        {options.map((o) => (
          <SelectItem key={o} value={o}>
            {o}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
