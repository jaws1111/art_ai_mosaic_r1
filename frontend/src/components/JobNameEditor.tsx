import { useEffect, useRef, useState } from "react";
import { renameJob } from "../api";

interface Props {
  jobId: string;
  displayName: string;
  fallbackId: string;
  onRenamed?: (name: string) => void;
}

export default function JobNameEditor({ jobId, displayName, fallbackId, onRenamed }: Props) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(displayName || fallbackId);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setValue(displayName || fallbackId);
  }, [displayName, fallbackId]);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  async function commit() {
    const trimmed = value.trim();
    if (!trimmed || trimmed === displayName) {
      setEditing(false);
      setValue(displayName || fallbackId);
      return;
    }
    setSaving(true);
    try {
      const updated = await renameJob(jobId, trimmed);
      onRenamed?.(updated.display_name || trimmed);
      setEditing(false);
    } catch (err) {
      alert(String(err));
      setValue(displayName || fallbackId);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        className="text-sm font-medium bg-neutral-900 border border-accent rounded px-2 py-0.5 w-full max-w-xs text-neutral-100"
        value={value}
        disabled={saving}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === "Enter") void commit();
          if (e.key === "Escape") {
            setValue(displayName || fallbackId);
            setEditing(false);
          }
        }}
      />
    );
  }

  return (
    <button
      type="button"
      className="text-sm font-medium text-neutral-200 truncate max-w-xs text-left hover:text-white"
      title="Double-click to rename"
      onDoubleClick={() => setEditing(true)}
    >
      {displayName || fallbackId}
    </button>
  );
}
