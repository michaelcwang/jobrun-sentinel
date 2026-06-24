import { Link } from "react-router-dom";

interface Props {
  loading: boolean;
  error: string | null;
  empty?: boolean;
  emptyText?: string;
}

export function LoadingState({ loading, error, empty, emptyText = "No records found." }: Props) {
  if (loading) return <div className="state-panel">Loading...</div>;
  if (error) {
    return (
      <div className="state-panel state-error">
        <strong>Unable to load this view.</strong>
        <p>{error}</p>
        <div className="button-row">
          <button className="small-button" type="button" onClick={() => window.location.reload()}>
            Retry
          </button>
          <Link className="small-button" to="/dashboard">
            Dashboard
          </Link>
        </div>
      </div>
    );
  }
  if (empty) return <div className="state-panel">{emptyText}</div>;
  return null;
}
