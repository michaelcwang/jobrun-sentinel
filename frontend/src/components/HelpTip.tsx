import { HelpCircle } from "lucide-react";

interface Props {
  label: string;
  text: string;
}

export function HelpTip({ label, text }: Props) {
  return (
    <span className="help-tip">
      <button className="help-trigger" aria-label={label} type="button">
        <HelpCircle size={15} aria-hidden />
      </button>
      <span className="help-bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}

