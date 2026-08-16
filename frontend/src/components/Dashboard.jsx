import React, { useState } from "react";

const TIER_ORDER = ["TIER1", "TIER2", "TIER3", "TIER4", "TIER5"];
const TIER_SHORT = { TIER1: "Hot", TIER2: "Warm", TIER3: "Interested", TIER4: "Exploratory", TIER5: "Low Priority" };

function formatMoney(value) {
  if (value == null || isNaN(value)) return "$0";
  return `$${Number(value).toLocaleString()}`;
}

function formatBudget(value) {
  return value == null || isNaN(value) ? "—" : `$${Number(value).toLocaleString()}/mo`;
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
      // user cancelled — treat as not-shared, no fallback needed
      return false;
    }
  }
  return copyText(text);
}

export default function Dashboard({ report, onSelectLead, onViewClusters, onViewDisqualified, jobId, leadStatuses = {}, onSetLeadStatus, onReprocess, processing }) {
  const summary = report.summary || {};
  const tiers = summary.tier_summary || {};
  const qualified = report.qualified || [];
  const [tierFilter, setTierFilter] = useState(null);
  const [copiedId, setCopiedId] = useState(null);

  const allLeads = [...qualified].sort((a, b) => (a.rank || 0) - (b.rank || 0));
  const leads = tierFilter ? allLeads.filter((l) => (l.scoring?.tier) === tierFilter) : allLeads;

  const handleCopy = async (e, lead) => {
    e.stopPropagation();
    const cleaned = lead.cleaned_data || {};
    const ok = await copyText(cleaned.email || "");
    if (ok) {
      setCopiedId(lead.lead_id);
      setTimeout(() => setCopiedId((id) => (id === lead.lead_id ? null : id)), 2000);
    }
  };

  const handleShare = async (e, lead) => {
    e.stopPropagation();
    const cleaned = lead.cleaned_data || {};
    const scoring = lead.scoring || {};
    const text = `${cleaned.name} | ${cleaned.company} | ${cleaned.title} | Score ${scoring.final_score}/100 | ${scoring.tier} | ${formatBudget(cleaned.budget_monthly)}`;
    await shareText(text, `Lead: ${cleaned.name}`);
  };

  const handleStatus = async (e, lead, status) => {
    e.stopPropagation();
    if (onSetLeadStatus) await onSetLeadStatus(lead.lead_id, status);
  };

  return (
    <div className="dashboard">
      {/* Processing status */}
      <section className="card">
        <h2>Processing Status</h2>
        <div className="status-line">
          <span className="badge success">Processing Complete</span>
          <span>
            {summary.total} leads uploaded · {summary.qualified} qualified ·{" "}
            {summary.disqualified} disqualified · {summary.low_priority} low priority
          </span>
          <span className="muted">
            {summary.clusters_created} clusters · {summary.llm_calls_made} LLM calls ·{" "}
            {summary.processing_duration_seconds}s
          </span>
          <span className="muted">
            LLM Cost: {formatMoney(summary.processing_cost_usd)}
          </span>
        </div>
      </section>

      {/* Tier cards — clickable to filter */}
      <section className="tier-grid">
        {TIER_ORDER.map((tier) => {
          const t = tiers[tier];
          if (!t) return null;
          const active = tierFilter === tier;
          return (
            <div
              key={tier}
              className={`tier-card tier-${tier.toLowerCase()} ${active ? "tier-active" : ""}`}
              onClick={() => setTierFilter(active ? null : tier)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") setTierFilter(active ? null : tier); }}
            >
              <h3>{tier} · {t.label}</h3>
              <p className="tier-count">{t.count} leads</p>
              <p>Avg score: <strong>{t.avg_score}/100</strong></p>
              <p>Pipeline value: <strong>{formatMoney(t.total_pipeline_value_monthly)}/mo</strong></p>
              <p className="muted">{t.action}</p>
            </div>
          );
        })}
      </section>

      <div className="dashboard-actions">
        <button onClick={onViewClusters} className="btn">View Clusters ({summary.clusters_created || 0})</button>
        <button onClick={onViewDisqualified} className="btn">View Disqualified ({summary.disqualified || 0})</button>
        {onReprocess && (
          <button onClick={onReprocess} className="btn" disabled={processing}>
            {processing ? "Reprocessing..." : "Re-run Pipeline"}
          </button>
        )}
        <a href={`/api/v1/jobs/${jobId}/export/csv`} download className="btn">Export CSV</a>
        <a href={`/api/v1/jobs/${jobId}/export/json`} download className="btn">Export JSON</a>
      </div>

      {/* Ranked leads */}
      <section className="card">
        <div className="leads-header">
          <h2>Ranked Leads ({leads.length})</h2>
          <div className="tier-filter-bar">
            <button
              className={`tier-filter-pill ${tierFilter === null ? "active" : ""}`}
              onClick={() => setTierFilter(null)}
            >
              All ({allLeads.length})
            </button>
            {TIER_ORDER.filter((t) => tiers[t]).map((tier) => (
              <button
                key={tier}
                className={`tier-filter-pill tier-pill-${tier.toLowerCase()} ${tierFilter === tier ? "active" : ""}`}
                onClick={() => setTierFilter(tierFilter === tier ? null : tier)}
              >
                {TIER_SHORT[tier]} ({tiers[tier].count})
              </button>
            ))}
          </div>
        </div>
        {leads.length === 0 && <p className="muted">No qualified leads in this tier.</p>}
        {leads.map((lead) => {
          const cleaned = lead.cleaned_data || {};
          const scoring = lead.scoring || {};
          const intel = lead.intelligence_features || {};
          const timeline = intel.timeline_signals || {};
          const useCases = intel.use_case_signals?.extracted_use_cases || [];
          const status = leadStatuses[lead.lead_id] || null;
          return (
            <div
              key={lead.lead_id}
              className={`lead-row ${status ? `lead-row-${status.toLowerCase()}` : ""}`}
              onClick={() => onSelectLead(lead.lead_id)}
            >
              <div className="lead-rank">#{lead.rank}</div>
              <div className="lead-info">
                <div className="lead-name">
                  {cleaned.name} <span className="muted">- {cleaned.company}</span>
                  <span className={`badge tier-${(scoring.tier || "tier5").toLowerCase()}`}>{scoring.tier}</span>
                  {status && <span className={`badge status-${status.toLowerCase()}`}>{status}</span>}
                </div>
                <div className="lead-meta">
                  {cleaned.title} · {cleaned.email} · {formatBudget(cleaned.budget_monthly)} ·{" "}
                  {timeline.timeline_urgency_level || "UNKNOWN"} timeline ·{" "}
                  {useCases[0] || "General automation"}
                </div>
              </div>
              <div className="lead-score">
                <strong>{scoring.final_score}</strong>/100
              </div>
              <div className="lead-actions">
                <button className="btn btn-sm" onClick={(e) => handleCopy(e, lead)}>
                  {copiedId === lead.lead_id ? "Copied ✓" : "Copy Email"}
                </button>
                <button className="btn btn-sm" onClick={(e) => handleShare(e, lead)}>Share</button>
                <button
                  className="btn btn-sm"
                  onClick={(e) => handleStatus(e, lead, status === "CONTACTED" ? null : "CONTACTED")}
                >
                  {status === "CONTACTED" ? "Mark Uncontacted" : "Mark Contacted"}
                </button>
                <button
                  className="btn btn-sm"
                  onClick={(e) => handleStatus(e, lead, status === "SKIPPED" ? null : "SKIPPED")}
                >
                  {status === "SKIPPED" ? "Unskip" : "Skip"}
                </button>
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}