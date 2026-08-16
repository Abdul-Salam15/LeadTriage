import React from "react";

export default function DisqualifiedView({ report, onBack }) {
  const disqualified = report.disqualified || [];
  const lowPriority = report.low_priority || [];

  return (
    <div>
      <button className="btn" onClick={onBack}>← Back to Dashboard</button>
      <h2>Disqualified ({disqualified.length})</h2>
      {disqualified.length === 0 && <p className="muted">No disqualified leads.</p>}
      {disqualified.map((d) => {
        const cleaned = d.cleaned_data || {};
        return (
          <div key={d.lead_id} className="lead-row">
            <div className="lead-info">
              <div className="lead-name">
                {d.lead_id} <span className="muted">- {cleaned.name} · {cleaned.company}</span>
              </div>
              <div className="lead-meta">
                <span className="badge danger">DISQUALIFIED</span>{" "}
                {d.disqualification_reason} — {d.recommendation}
              </div>
            </div>
          </div>
        );
      })}

      <h2>Low Priority ({lowPriority.length})</h2>
      {lowPriority.map((d) => {
        const cleaned = d.cleaned_data || {};
        return (
          <div key={d.lead_id} className="lead-row">
            <div className="lead-info">
              <div className="lead-name">
                {d.lead_id} <span className="muted">- {cleaned.name} · {cleaned.company}</span>
              </div>
              <div className="lead-meta">
                <span className="badge warning">LOW PRIORITY</span>{" "}
                {d.disqualification_reason}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
