import React from "react";

export default function ClustersView({ report, onBack }) {
  const clusters = report.clusters || [];
  const byId = {};
  (report.qualified || []).forEach((l) => {
    byId[l.lead_id] = l;
  });

  return (
    <div>
      <button className="btn" onClick={onBack}>← Back to Dashboard</button>
      <h2>Clusters ({clusters.length})</h2>
      {clusters.map((cluster) => {
        const analysis = cluster.llm_analysis || {};
        const overall = analysis.overall_assessment || {};
        const reps = (cluster.representative_lead_ids || []).map((id) => byId[id]).filter(Boolean);
        const cost = cluster.analysis_cost_usd ?? analysis.analysis_cost_usd;
        return (
          <div key={cluster.cluster_id} className="card">
            <h3>
              {cluster.cluster_name}{" "}
              <span className={`badge ${analysis.analysis_source === "openai" ? "success" : "warning"}`}>
                {analysis.analysis_source === "openai" ? "LLM (OpenAI)" : "Heuristic"}
              </span>
              {cost > 0 && <span className="badge">~${cost.toFixed(4)}</span>}
            </h3>
            <p className="muted">
              {cluster.cluster_id} · {cluster.lead_count} leads · Avg intel {cluster.avg_intelligence_score}
            </p>
            <p>
              <strong>Intent:</strong> {overall.intent_level || "—"} ·{" "}
              <strong>Action:</strong> {overall.recommended_action || "—"} ·{" "}
              <strong>Urgency:</strong> {analysis.urgency_assessment?.urgency_level || "—"} ·{" "}
              <strong>Fit:</strong> {analysis.fit_assessment?.overall_fit_score || "—"}
            </p>
            <p><strong>Primary pain point:</strong> {analysis.common_characteristics?.primary_pain_point || "—"}</p>
            <h4>Representatives</h4>
            <ul>
              {reps.map((lead) => {
                const cd = lead.cleaned_data || {};
                const score = lead.scoring?.final_score;
                const tier = lead.scoring?.tier;
                const budget = cd.budget_monthly ? `$${Number(cd.budget_monthly).toLocaleString()}/mo` : "No budget";
                return (
                  <li key={lead.lead_id}>
                    <strong>{cd.name || "Unknown"}</strong> ({cd.company || "?"}) — {cd.title || "No title"} · {budget}
                    {score != null && <> · <strong>{score}/100</strong> {tier && <span className={`badge tier-${tier.toLowerCase()}`}>{tier}</span>}</>}
                  </li>
                );
              })}
            </ul>
            {analysis.next_steps && analysis.next_steps.length > 0 && (
              <>
                <h4>Next Steps</h4>
                <ul>
                  {analysis.next_steps.map((s, i) => <li key={i}>{s}</li>)}
                </ul>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
