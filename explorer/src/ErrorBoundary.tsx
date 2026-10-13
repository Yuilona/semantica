import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertCircle } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  retryCount: number;
}

const RETRY_SETTLE_MS = 5000;

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  private settleTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null, retryCount: 0 };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
    this.clearSettleTimer();
  }

  componentWillUnmount() {
    this.clearSettleTimer();
  }

  private clearSettleTimer() {
    if (this.settleTimer !== null) {
      clearTimeout(this.settleTimer);
      this.settleTimer = null;
    }
  }

  resetErrorBoundary = () => {
    this.clearSettleTimer();
    this.setState((prev) => ({
      hasError: false,
      error: null,
      retryCount: prev.retryCount + 1
    }));
    // Only clear the retry count once the workspace has stayed error-free for a
    // sustained period, rather than on the next committed render (which can fire
    // while Suspense is still showing its fallback) or immediately on retry
    // (which would allow an unbounded number of clicks on a deterministic crash).
    this.settleTimer = setTimeout(() => {
      this.settleTimer = null;
      this.setState({ retryCount: 0 });
    }, RETRY_SETTLE_MS);
  };

  render() {
    if (this.state.hasError) {
      const maxRetriesReached = this.state.retryCount >= 3;

      return (
        <div 
          className="workspace-loading" 
          style={{ 
            flexDirection: 'column', 
            gap: 12,
            color: 'var(--ws-red)'
          }}
        >
          <AlertCircle size={32} style={{ marginBottom: 4, opacity: 0.8 }} />
          <div style={{ fontWeight: 500, fontSize: '15px' }}>
            此视图出错了。
          </div>
          <div style={{ fontSize: '13px', opacity: 0.7, maxWidth: 450, textAlign: 'center', marginBottom: 8, lineHeight: 1.5 }}>
            {maxRetriesReached 
              ? "此视图持续出现严重错误。请切换到其他工作区，或重新加载页面。"
              : "渲染此工作区时出现意外问题。数据没有受影响，但此视图无法显示。"}
          </div>
          {!maxRetriesReached ? (
            <button 
              className="ws-btn ws-btn--ghost" 
              style={{ 
                borderColor: 'var(--ws-red-soft)',
                color: 'var(--ws-red)'
              }}
              onClick={this.resetErrorBoundary}
            >
              重试
            </button>
          ) : (
            <button 
              className="ws-btn ws-btn--ghost" 
              style={{ 
                borderColor: 'var(--ws-border)',
                color: 'var(--ws-text)'
              }}
              onClick={() => window.location.reload()}
            >
              重新加载应用
            </button>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
