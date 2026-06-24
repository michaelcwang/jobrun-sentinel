import type { RuntimeState, Severity } from "../types";

interface Props {
  state: RuntimeState | Severity | string | null | undefined;
}

export function StatusPill({ state }: Props) {
  const normalized = (state ?? "unknown").toString().toLowerCase().replace("_", "-");
  return (
    <span className={`status-pill status-${normalized}`} title={stateDescriptions[normalized] ?? undefined}>
      {state ?? "unknown"}
    </span>
  );
}

const stateDescriptions: Record<string, string> = {
  normal: "Within expected runtime.",
  complete: "Finished run.",
  watch: "Approaching a warning threshold or mild ETA risk.",
  warning: "Above warning threshold; review next action.",
  critical: "Above critical threshold or severe risk signal.",
  "unknown-baseline": "No reliable baseline yet; learning mode.",
  info: "Informational observation.",
  healthy: "Connector is responding.",
  active: "Record or monitor is enabled.",
  inactive: "Record or monitor is disabled."
};
