import { BriefcaseBusiness, Database, Headphones } from "lucide-react";

import { HelpTip } from "./HelpTip";
import { useRole } from "../context/RoleContext";

export function RoleGuide() {
  const { role, config } = useRole();
  const Icon = role === "executive" ? BriefcaseBusiness : role === "dba" ? Database : Headphones;

  return (
    <div className={`role-guide role-guide-${role}`}>
      <Icon size={18} aria-hidden />
      <div>
        <span className="eyebrow">{config.label} view</span>
        <strong>{config.headline}</strong>
        <small>{config.primaryQuestion}</small>
      </div>
      <HelpTip label={`${config.label} view help`} text={config.help} />
    </div>
  );
}

