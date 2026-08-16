import React, { useMemo, useState } from "react";
import { confirmMapping } from "../api.js";
import { CANONICAL_FIELDS } from "./UploadZone.jsx";

const OPTIONS = [...CANONICAL_FIELDS, "__ignore__", "__metadata__"];

function friendlyLabel(value) {
  switch (value) {
    case "__ignore__":
      return "— Ignore this column";
    case "__metadata__":
      return "— Keep as metadata";
    default:
      return value;
  }
}

export default function ColumnMapping({ jobId, mapping, onConfirmed }) {
  const [overrides, setOverrides] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  const needsReview = useMemo(
    () =>
      mapping.mappings.filter(
        (m) => m.requires_confirmation || !m.mapped_to
      ),
    [mapping]
  );

  const handleChange = (header, value) => {
    setOverrides((prev) => ({ ...prev, [header]: value }));
  };

  const handleConfirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const { data } = await confirmMapping(jobId, overrides);
      onConfirmed(data);
    } catch (err) {
      setError(err?.response?.data?.error || "Failed to confirm mapping.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mapping-section">
      <h2>Confirm Column Mapping</h2>
      <p className="hint">
        We detected the following columns. Review any that need attention, then
        confirm to continue.
      </p>

      {needsReview.length > 0 && (
        <div className="notice">
          {needsReview.length} column(s) need your input before processing.
        </div>
      )}

      <table className="mapping-table">
        <thead>
          <tr>
            <th>CSV Column</th>
            <th>Detected As</th>
            <th>Confidence</th>
            <th>Override</th>
          </tr>
        </thead>
        <tbody>
          {mapping.mappings.map((m) => {
            const needsInput =
              m.requires_confirmation ||
              !m.mapped_to ||
              overrides[m.header] !== undefined;
            return (
              <tr key={m.header} className={needsInput ? "row-attention" : ""}>
                <td className="col-name">{m.header}</td>
                <td>
                  <span className={`badge match-${m.match_type.toLowerCase()}`}>
                    {m.mapped_to ? friendlyLabel(m.mapped_to) : "No match"}
                  </span>
                  {m.match_type === "FUZZY" && (
                    <span className="similarity">
                      {Math.round(m.similarity * 100)}%
                    </span>
                  )}
                </td>
                <td>{m.confidence}</td>
                <td>
                  <select
                    value={overrides[m.header] ?? ""}
                    onChange={(e) => handleChange(m.header, e.target.value)}
                  >
                    <option value="">— no override —</option>
                    {OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>
                        {friendlyLabel(opt)}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {error && <div className="error-banner">{error}</div>}

      <div className="mapping-actions">
        <button className="btn primary" onClick={handleConfirm} disabled={submitting}>
          {submitting ? "Confirming…" : "Confirm Mapping & Continue"}
        </button>
      </div>
    </div>
  );
}
