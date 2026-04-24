import { FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ErrorPanel } from "../../components/ErrorPanel";
import { LoadingBlock } from "../../components/LoadingBlock";
import { LogoStacked } from "../../components/Logo";
import { useBootstrapAdminMutation, useBootstrapStatusQuery } from "../../lib/api/hooks";
import { useSession } from "./AuthProvider";
import { APP_ROUTES } from "../../lib/utils/routes";

type LocationState = {
  from?: string;
};

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, isAuthenticated, ready } = useSession();
  const bootstrapStatusQuery = useBootstrapStatusQuery(ready);
  const bootstrapAdminMutation = useBootstrapAdminMutation();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!ready) {
    return <LoadingBlock label="Preparing sign-in" fullScreen />;
  }

  if (isAuthenticated) {
    return <Navigate to={APP_ROUTES.dashboard} replace />;
  }

  if (bootstrapStatusQuery.isLoading) {
    return <LoadingBlock label="Checking first-run setup" fullScreen />;
  }

  if (bootstrapStatusQuery.isError) {
    const message = bootstrapStatusQuery.error instanceof Error
      ? bootstrapStatusQuery.error.message
      : "Unable to determine whether first-run setup is required.";

    return (
      <main className="login-shell">
        <section className="login-panel">
          <LogoStacked className="logo-stacked login-logo" />
          <h1>Unable to load sign-in state</h1>
          <p className="section-copy">
            Encodr could not confirm whether a first admin user needs to be created. Check API access and refresh the page.
          </p>
          <p className="login-version">Encodr v{__ENCODR_VERSION__}</p>
          <ErrorPanel title="Unable to load first-run status" message={message} />
        </section>
      </main>
    );
  }

  const state = (location.state ?? {}) as LocationState;
  const bootstrapRequired = bootstrapStatusQuery.data?.first_user_setup_required ?? false;
  const displayedVersion = bootstrapStatusQuery.data?.version ?? __ENCODR_VERSION__;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      await login(username, password);
      navigate(state.from ?? APP_ROUTES.dashboard, { replace: true });
    } catch (submissionError) {
      setError(
        submissionError instanceof Error
          ? submissionError.message
          : "Sign-in failed. Please check your details and try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleBootstrapSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      await bootstrapAdminMutation.mutateAsync({ username, password });
      await login(username, password);
      navigate(APP_ROUTES.dashboard, { replace: true });
    } catch (submissionError) {
      setError(
        submissionError instanceof Error
          ? submissionError.message
          : "Unable to create the first admin user.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <LogoStacked className="logo-stacked login-logo" />
        <h1>{bootstrapRequired ? "Set up the first admin user" : "Sign in to the operator console"}</h1>
        <p className="section-copy">
          {bootstrapRequired
            ? "No users exist yet. Create the first admin account to finish setup. You can mount your media library later if it is not ready yet."
            : "Sign in to manage your library, jobs, review queue, and system status."}
        </p>
        <p className="login-version">Encodr v{displayedVersion}</p>
        <form className="form-grid" onSubmit={bootstrapRequired ? handleBootstrapSubmit : handleSubmit}>
          <label className="field">
            <span>Username</span>
            <input
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="admin"
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              autoComplete={bootstrapRequired ? "new-password" : "current-password"}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter your password"
            />
          </label>
          {bootstrapRequired ? (
            <label className="field">
              <span>Confirm password</span>
              <input
                autoComplete="new-password"
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                placeholder="Re-enter your password"
              />
            </label>
          ) : null}
          {error ? <ErrorPanel title="Unable to sign in" message={error} /> : null}
          <button className="button button-primary" type="submit" disabled={submitting}>
            {submitting
              ? (bootstrapRequired ? "Creating admin…" : "Signing in…")
              : (bootstrapRequired ? "Create first admin" : "Sign in")}
          </button>
        </form>
      </section>
    </main>
  );
}
