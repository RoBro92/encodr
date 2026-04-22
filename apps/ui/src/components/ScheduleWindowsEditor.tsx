import type { ScheduleWindow } from "../lib/types/api";

const DAY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "mon", label: "Mon" },
  { value: "tue", label: "Tue" },
  { value: "wed", label: "Wed" },
  { value: "thu", label: "Thu" },
  { value: "fri", label: "Fri" },
  { value: "sat", label: "Sat" },
  { value: "sun", label: "Sun" },
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
};

export function ScheduleWindowsEditor({
  label,
  value,
  onChange,
  disabled = false,
}: ScheduleWindowsEditorProps) {
  return (
    <div className="field field-schedule-editor">
      <div className="field-label-row">
        <span>{label}</span>
        <button
          className="button button-secondary button-small"
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
            <div key={`${window.start_time}-${window.end_time}-${index}`} className="schedule-window-card">
              <div className="field-label-row">
                <strong>Window {index + 1}</strong>
                <button
                  className="button button-secondary button-small"
                  type="button"
                  onClick={() => onChange(value.filter((_, itemIndex) => itemIndex !== index))}
                  disabled={disabled}
                >
                  Remove
                </button>
              </div>

              <div className="schedule-day-grid">
                {DAY_OPTIONS.map((day) => {
                  const checked = window.days.includes(day.value);
                  return (
                    <label key={day.value} className={`schedule-day-pill${checked ? " schedule-day-pill-active" : ""}`}>
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={(event) => {
                          const nextDays = event.target.checked
                            ? [...window.days, day.value]
                            : window.days.filter((item) => item !== day.value);
                          onChange(
                            value.map((item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, days: nextDays }
                                : item,
                            ),
                          );
                        }}
                      />
                      <span>{day.label}</span>
                    </label>
                  );
                })}
              </div>

              <div className="schedule-time-grid">
                <label className="field">
                  <span>Start</span>
                  <input
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
                <label className="field">
                  <span>End</span>
                  <input
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
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
