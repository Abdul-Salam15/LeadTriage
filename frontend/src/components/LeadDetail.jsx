import React, { useState } from "react";

function formatMoney(value) {
  if (value == null || isNaN(value)) return "N/A";
  return `$${Number(value).toLocaleString()}`;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    return false;
  }
}

async function shareText(text, title = "Lead") {
  if (navigator.share) {
    try {
      await navigator.share({ title, text });
      return true;
    } catch (err) {
      return false;
    }
  }
  return copyText(text);
}

function ScoreBar({ value, max = 1, label }) {
  const pct = Math.round((Math.min(value, max) / max) * 100);
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="score-value">{value != null ? value.toFixed(2) : "—"}</span>
    </div>
  );
}

const EDITABLE_FIELDS = [
  { key: "name", label: "Name", cleanedKey: "name", type: "text" },
  { key: "company", label: "Company", cleanedKey: "company", type: "text" },
  { key: "title", label: "Title", cleanedKey: "title", type: "text" },
  { key: "email", label: "Email", cleanedKey: "email", type: "text" },
  { key: "website", label: "Website", cleanedKey: "website", type: "text" },
  { key: "source", label: "Source", cleanedKey: "source", type: "text" },
  { key: "monthly_budget", label: "Budget (monthly $)", cleanedKey: "budget_monthly", type: "number" },
  { key: "employees", label: "Employees", cleanedKey: "employees", type: "number" },
];

function EditableRow({ label, displayValue, defaultValue, fieldKey, type, onSave, hasOverride }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);

  const startEdit = () => {
    setValue(defaultValue == null ? "" : String(defaultValue));
    setEditing(true);
  };
  const cancel = () => setEditing(false);
  const save = () => {
    const trimmed = value.trim();
    onSave(fieldKey, trimmed === "" ? null : trimmed);
    setEditing(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="editable-row">
      <strong>{label}:</strong>
      {editing ? (
        <>
          <input
            className="field-input"
            type={type}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") cancel(); }}
            autoFocus
          />
          <button className="btn btn-sm" onClick={save}>Save</button>
          <button className="btn btn-sm" onClick={cancel}>Cancel</button>
        </>
      ) : (
        <>
          <span className="editable-value">{displayValue}</span>
          {hasOverride && <span className="badge status-contacted">edited</span>}
          <button className="btn btn-sm" onClick={startEdit}>{saved ? "Saved ✓" : "Edit"}</button>
        </>
      )}
    </div>
  );
}

export default function LeadDetail({ jobId, lead, status = null, onSetLeadStatus, overrides = {}, onSetOverride, onReprocess, processing, onBack }) {
  const [copied, setCopied] = useState(false);
  if (!lead) return null;
  const cleaned = lead.cleaned_data || {};
  const intel = lead.intelligence_features || {};
  const scoring = lead.scoring || {};
  const analysis = lead.analysis_summary || {};
  const strategy = lead.sales_strategy || {};
  const cluster = lead.cluster_assignment || {};
  const notes = cleaned.notes_analysis || {};
  const adjustments = scoring.individual_adjustments || {};

  const handleCopyEmail = async () => {
    if (await copyText(cleaned.email || "")) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleShare = () => {
    const text = `${cleaned.name} | ${cleaned.company} | ${cleaned.title} | Score ${scoring.final_score}/100 | ${scoring.tier} | ${formatMoney(cleaned.budget_monthly)}/mo`;
    const subject = encodeURIComponent(`Lead: ${cleaned.name}`);
    const body = encodeURIComponent(text);
    window.open(`mailto:?subject=${subject}&body=${body}`, "_self");
  };

  const toggleStatus = (target) => {
    if (onSetLeadStatus) onSetLeadStatus(lead.lead_id, status === target ? null : target);
  };

  const handleOverride = (field, value) => {
    if (onSetOverride) onSetOverride(lead.lead_id, field, value);
  };

  const overriddenCount = EDITABLE_FIELDS.filter((f) => overrides[f.key] != null).length;

  return (
    <div className="lead-detail">
      <button className="btn" onClick={onBack}>← Back to Dashboard</button>

      <header className="card">
        <h2>{cleaned.name} - {cleaned.company}</h2>
        <p>
          <span className={`badge tier-${(scoring.tier || "tier5").toLowerCase()}`}>{scoring.tier}</span>{" "}
          Score: <strong>{scoring.final_score}/100</strong> · {cluster.cluster_name}
          {status && <span className={`badge status-${status.toLowerCase()}`}>{status}</span>}
        </p>
        <div className="dashboard-actions">
          <button className="btn" onClick={handleCopyEmail}>{copied ? "Copied ✓" : "Copy Email"}</button>
          <button className="btn" onClick={handleShare}>Share</button>
          <button className="btn" onClick={() => toggleStatus("CONTACTED")}>
            {status === "CONTACTED" ? "Mark Uncontacted" : "Mark Contacted"}
          </button>
          <button className="btn" onClick={() => toggleStatus("SKIPPED")}>
            {status === "SKIPPED" ? "Unskip" : "Skip"}
          </button>
          {onReprocess && (
            <button className="btn primary" onClick={onReprocess} disabled={processing}>
              {processing ? "Reprocessing..." : "Re-run Pipeline"}
            </button>
          )}
        </div>
      </header>

      <section className="card">
        <h3>Contact Information</h3>
        {overriddenCount > 0 && (
          <div className="notice">
            <p>
              {overriddenCount} field(s) edited. Re-run the pipeline to apply edits to
              scoring, analysis, and exports.
            </p>
            {onReprocess && (
              <button className="btn btn-sm" onClick={onReprocess} disabled={processing} style={{ marginTop: "0.5rem" }}>
                {processing ? "Reprocessing..." : "Re-run Pipeline"}
              </button>
            )}
          </div>
        )}
        <div className="kv-grid editable-grid">
          {EDITABLE_FIELDS.map((f) => {
            const overrideVal = overrides[f.key];
            const baseVal = cleaned[f.cleanedKey];
            const display =
              f.key === "monthly_budget"
                ? formatMoney(overrideVal ?? baseVal) + "/mo"
                : String(overrideVal ?? baseVal ?? "—");
            return (
              <EditableRow
                key={f.key}
                label={f.label}
                displayValue={display}
                defaultValue={overrideVal ?? baseVal}
                fieldKey={f.key}
                type={f.type}
                onSave={handleOverride}
                hasOverride={overrideVal != null}
              />
            );
          })}
          <div className="editable-row"><strong>Days since contact:</strong> <span className="editable-value">{cleaned.days_since_created}</span></div>
        </div>
      </section>

      <section className="card">
        <h3>Analysis & Scoring</h3>
        <ScoreBar label="Cluster Base Score" value={(scoring.cluster_base_score || 0) / 100} max={1} />
        {Object.entries(adjustments).map(([key, val]) => (
          <div key={key} className="adjustment-row">
            <span>{key.replace(/_/g, " ")}</span>
            <span className={val > 0 ? "pos" : val < 0 ? "neg" : "muted"}>
              {val > 0 ? `+${val}` : val}
            </span>
          </div>
        ))}
        <p className="muted">{scoring.score_calculation_transparency}</p>
      </section>

      <section className="card">
        <h3>Intelligence Breakdown</h3>
        <ScoreBar label="Budget Intent" value={intel.budget_signals?.budget_seriousness_score} />
        <ScoreBar label="Timeline Urgency" value={intel.timeline_signals?.combined_timeline_score} />
        <ScoreBar label="Authority Level" value={intel.authority_signals?.combined_authority_score} />
        <ScoreBar label="Use Case Clarity" value={intel.use_case_signals?.clarity_score} />
        <ScoreBar label="Company Fit" value={intel.company_fit_signals?.combined_fit_score} />
        <ScoreBar label="Notes Quality" value={intel.notes_quality_signals?.quality_score} />
      </section>

      <section className="card">
        <h3>Detailed Analysis</h3>
        <p><strong>Intent Level:</strong> {analysis.intent_level} ({analysis.intent_confidence ? (analysis.intent_confidence * 100).toFixed(0) + "% confidence" : "—"})</p>
        <p><strong>Primary Pain Point:</strong> {analysis.primary_pain_point || "—"}</p>
        <p><strong>Urgency:</strong> {analysis.urgency || "—"}</p>
        <p><strong>Fit Assessment:</strong> {analysis.fit_assessment || "—"}</p>
        <p><strong>Est. Deal Probability:</strong> {analysis.estimated_deal_probability ? (analysis.estimated_deal_probability * 100).toFixed(0) + "%" : "—"}</p>
        <p><strong>Est. Sales Cycle:</strong> {analysis.estimated_sales_cycle_weeks ? analysis.estimated_sales_cycle_weeks + " weeks" : "—"}</p>
        <p><strong>Recommendation:</strong> {analysis.recommendation || "—"}</p>
      </section>

      <section className="card">
        <h3>Sales Strategy</h3>
        <h4>Conversation Starters</h4>
        <ul>
          {(strategy.conversation_starters || []).map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
        <h4>Potential Objections</h4>
        <ul>
          {(strategy.potential_objections || []).map((o, i) => (
            <li key={i}>{o}</li>
          ))}
        </ul>
        <h4>Next Steps</h4>
        <ul>
          {(strategy.next_steps || []).map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3>Original Notes</h3>
        <p className="quote">"{notes.notes || cleaned.notes_cleaned || "—"}"</p>
        {notes.flagged_as && notes.flagged_as.length > 0 && (
          <p className="muted">Flags: {notes.flagged_as.join(", ")}</p>
        )}
      </section>
    </div>
  );
}
