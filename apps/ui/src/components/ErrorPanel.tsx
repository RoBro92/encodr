import { useState } from "react";

export function ErrorPanel({
  title = "Something went wrong",
  message,
}: {
  title?: string;
  message: string;
}) {
  const [isVisible, setIsVisible] = useState(true);

  if (!isVisible) {
    return null;
  }

  return (
    <div className="error-panel" role="alert">
      <div className="alert-content">
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
      <button
        className="alert-dismiss-button"
        type="button"
        aria-label="Dismiss"
        onClick={() => setIsVisible(false)}
      >
        <svg className="app-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M18 6 6 18M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
