export function ErrorPanel({
  title = "Something went wrong",
  message,
}: {
  title?: string;
  message: string;
}) {
  return (
    <div className="error-panel" role="alert">
      <strong>{title}</strong>
      <p>{message}</p>
    </div>
  );
}
