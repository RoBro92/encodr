import type { ScheduleWindow } from "../lib/types/api";

const DAY_OPTIONS: Array<{ value: string; label: string; name: string }> = [
  { value: "mon", label: "M", name: "Monday" },
  { value: "tue", label: "T", name: "Tuesday" },
  { value: "wed", label: "W", name: "Wednesday" },
  { value: "thu", label: "Th", name: "Thursday" },
  { value: "fri", label: "F", name: "Friday" },
  { value: "sat", label: "S", name: "Saturday" },
  { value: "sun", label: "Su", name: "Sunday" },
];

const DEFAULT_WINDOW: ScheduleWindow = {
  days: ["mon", "tue", "wed", "thu", "fri"],
  start_time: "23:00",
  end_time: "07:00",
};

type ScheduleWindowsEditorProps = {
  label: string;
  value: ScheduleWindow[];
  onChange: (value: ScheduleWindow[]) => void;
  disabled?: boolean;
  concurrencyValue?: number | null;
  onConcurrencyChange?: (value: number) => void;
};

export function ScheduleWindowsEditor({
  label,
  value,
  onChange,
  disabled = false,
  concurrencyValue,
  onConcurrencyChange,
}: ScheduleWindowsEditorProps) {
  const showConcurrency = typeof concurrencyValue === "number" && Boolean(onConcurrencyChange);

  return (
    <div className="schedule-editor">
      <div className="schedule-editor-header">
        <div>
          <strong>{label}</strong>
          <p>When should this schedule run?</p>
        </div>
        <button
          className="button button-primary button-small schedule-add-button"
          type="button"
          onClick={() => onChange([...value, { ...DEFAULT_WINDOW }])}
          disabled={disabled}
        >
          Add window
        </button>
      </div>

      {value.length === 0 ? (
        <p className="muted-copy">Any time. Add a window to limit when this worker or watcher may run.</p>
      ) : (
        <div className="schedule-window-list">
          {value.map((window, index) => (
            <div
              key={`${window.start_time}-${window.end_time}-${index}`}
              className={`schedule-window-row${showConcurrency ? " schedule-window-row-with-concurrency" : ""}`}
            >
              <div className="schedule-window-days">
                <span className="schedule-window-label">Days</span>
                <div className="schedule-day-grid">
                  {DAY_OPTIONS.map((day) => {
                    const checked = window.days.includes(day.value);
                    return (
                      <button
                        key={day.value}
                        className={`schedule-day-pill${checked ? " schedule-day-pill-active" : ""}`}
                        type="button"
                        aria-label={`${checked ? "Remove" : "Add"} ${day.name} for schedule window ${index + 1}`}
                        aria-pressed={checked}
                        onClick={() => {
                          const selectedDays = new Set(window.days);
                          if (checked) {
                            selectedDays.delete(day.value);
                          } else {
                            selectedDays.add(day.value);
                          }
                          const nextDays = DAY_OPTIONS
                            .filter((item) => selectedDays.has(item.value))
                            .map((item) => item.value);
                          if (nextDays.length === 0) {
                            return;
                          }
                          onChange(
                            value.map((item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, days: nextDays }
                                : item,
                            ),
                          );
                        }}
                        disabled={disabled}
                      >
                        {day.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <label className="schedule-window-field">
                <span className="schedule-window-label">Start time</span>
                <input
                  aria-label={`Schedule window ${index + 1} start time`}
                  type="time"
                  value={window.start_time}
                  disabled={disabled}
                  onChange={(event) => {
                    onChange(
                      value.map((item, itemIndex) =>
                        itemIndex === index
                          ? { ...item, start_time: event.target.value }
                          : item,
                      ),
                    );
                  }}
                />
              </label>

              <label className="schedule-window-field">
                <span className="schedule-window-label">End time</span>
                <input
                  aria-label={`Schedule window ${index + 1} end time`}
                  type="time"
                  value={window.end_time}
                  disabled={disabled}
                  onChange={(event) => {
                    onChange(
                      value.map((item, itemIndex) =>
                        itemIndex === index
                          ? { ...item, end_time: event.target.value }
                          : item,
                      ),
                    );
                  }}
                />
              </label>

              {showConcurrency ? (
                <label className="schedule-window-field schedule-window-concurrency">
                  <span className="schedule-window-label">Concurrency</span>
                  <input
                    aria-label={`Schedule window ${index + 1} concurrency`}
                    type="number"
                    min={1}
                    max={8}
                    value={concurrencyValue ?? 1}
                    disabled={disabled}
                    onChange={(event) => onConcurrencyChange?.(Number(event.target.value) || 1)}
                  />
                </label>
              ) : null}

              <button
                className="schedule-window-remove"
                type="button"
                aria-label={`Remove schedule window ${index + 1}`}
                onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))}
                disabled={disabled}
              >
                <svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">
                  <path d="M3 6h18" />
                  <path d="M8 6V4h8v2" />
                  <path d="m9 10 .5 8" />
                  <path d="m15 10-.5 8" />
                  <path d="M6 6l1 15h10l1-15" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
