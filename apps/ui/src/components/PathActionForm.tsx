import { FormEvent, useState } from "react";

export function PathActionForm({
  label,
  placeholder,
  submitLabel,
  submittingLabel,
  onSubmit,
}: {
  label: string;
  placeholder: string;
  submitLabel: string;
  submittingLabel: string;
  onSubmit: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!value.trim()) {
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit(value.trim());
      setValue("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="inline-form" onSubmit={handleSubmit}>
      <label className="field field-inline">
        <span>{label}</span>
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder={placeholder}
        />
      </label>
      <button className="button button-primary" type="submit" disabled={submitting}>
        {submitting ? submittingLabel : submitLabel}
      </button>
    </form>
  );
}
