import { useMemo, useState } from "react";
import { FileSummary } from "../../../lib/types/api";
import { formatTrackedFileOption } from "../jobUtils";

export function TrackedFilePicker({
      label,
      items,
      selectedId,
      query,
      placeholder,
      onQueryChange,
      onSelectedIdChange,
      onClear,
    }: {
          label: string;
          items: FileSummary[];
          selectedId: string;
          query: string;
          placeholder: string;
          onQueryChange: (value: string) => void;
          onSelectedIdChange: (value: string, label: string) => void;
          onClear: () => void;
        }) {
    const [open, setOpen] = useState(false);
    const matches = useMemo(() => {
            const search = query.trim().toLowerCase();
            if (!search) {
              return items.slice(0, 8);
            }
            return items
              .filter((item) => {
                const labelText = formatTrackedFileOption(item).toLowerCase();
                return labelText.includes(search) || item.id.toLowerCase().includes(search) || item.source_path.toLowerCase().includes(search);
              })
              .slice(0, 8);
          }, [items, query]);
    return (
    <label className="field file-search-field">
      <span>{label}</span>
      <div className="combobox">
        <input
          aria-label={label}
          value={query}
          placeholder={placeholder}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            window.setTimeout(() => setOpen(false), 120);
          }}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        {selectedId ? (
          <button className="button button-secondary button-small" type="button" onClick={onClear}>
            Clear
          </button>
        ) : null}
        {open && matches.length > 0 ? (
          <div className="combobox-menu" role="listbox" aria-label={`${label} options`}>
            {matches.map((item) => {
              const optionLabel = formatTrackedFileOption(item);
              return (
                <button
                  key={item.id}
                  className={`combobox-option${item.id === selectedId ? " combobox-option-active" : ""}`}
                  type="button"
                  role="option"
                  aria-selected={item.id === selectedId}
                  onMouseDown={(event) => {
                    event.preventDefault();
                  }}
                  onClick={() => {
                    onSelectedIdChange(item.id, optionLabel);
                    setOpen(false);
                  }}
                >
                  <strong>{item.source_filename}</strong>
                  <span>{item.source_directory}</span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </label>
    );
}
