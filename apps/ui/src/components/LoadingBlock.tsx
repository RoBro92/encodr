export function LoadingBlock({
  label,
  fullScreen = false,
}: {
  label?: string;
  fullScreen?: boolean;
}) {
  return (
    <div className={fullScreen ? "loading-screen" : "loading-block"} role="status" aria-live="polite">
      <span className="loading-dot" />
      <span>{label ?? "Loading"}</span>
    </div>
  );
}
