"use client";

import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });
    // In production, send to error tracking (Sentry, etc.)
    console.error("[ErrorBoundary]", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex flex-col items-center justify-center min-h-[200px] p-6 text-center">
          <div className="w-10 h-10 rounded-xl bg-qa-danger-bg border border-terminal-down/40 flex items-center justify-center mb-4">
            <AlertTriangle size={18} className="text-terminal-down" />
          </div>
          <h3 className="text-sm font-semibold text-white mb-1">
            Что-то пошло не так
          </h3>
          <p className="text-xs text-qa-muted mb-4 max-w-xs">
            {this.state.error?.message || "Неизвестная ошибка компонента"}
          </p>
          <button
            onClick={this.handleReset}
            className="btn-ghost border border-qa-border-strong text-xs"
          >
            <RefreshCw size={12} />
            Попробовать снова
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

// Functional wrapper for use in Server Components / layouts
export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  fallback?: ReactNode,
) {
  return function WrappedWithErrorBoundary(props: P) {
    return (
      <ErrorBoundary fallback={fallback}>
        <Component {...props} />
      </ErrorBoundary>
    );
  };
}
