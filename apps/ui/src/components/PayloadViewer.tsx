import { useState } from "react";

export function PayloadViewer({ payload }: { payload: unknown }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="payload-viewer">
      <button
        className="button button-secondary button-small"
        type="button"
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Hide raw payload" : "Show raw payload"}
      </button>
      {expanded ? <pre>{JSON.stringify(payload, null, 2)}</pre> : null}
    </div>
  );
}
