import type { ReactNode } from "react";
import { HelpTip } from "./HelpTip";

interface Props {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  help?: string;
}

export function Metric({ label, value, hint, help }: Props) {
  return (
    <div className="metric">
      <span className="metric-label">
        {label}
        {help ? <HelpTip label={`${label} help`} text={help} /> : null}
      </span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}
