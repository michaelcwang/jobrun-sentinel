import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("JobRun Sentinel view error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    // This is a last-resort route guard. Data fetch errors are handled by
    // LoadingState near the page, but render-time bugs still need a safe way
    // back to the dashboard so browser back/forward does not strand the user.
    return (
      <div className="state-panel state-error app-error-boundary">
        <strong>Something went wrong while rendering this view.</strong>
        <p>The application state is preserved. Return to the dashboard or reload the page.</p>
        <div className="button-row">
          <button className="small-button" type="button" onClick={() => window.location.reload()}>
            Reload
          </button>
          <a className="small-button" href="/dashboard">
            Dashboard
          </a>
        </div>
      </div>
    );
  }
}
