import React, { useEffect, useRef, useState } from "react";
import UploadZone from "./components/UploadZone.jsx";
import FilePreview from "./components/FilePreview.jsx";
import ColumnMapping from "./components/ColumnMapping.jsx";
import Dashboard from "./components/Dashboard.jsx";
import LeadDetail from "./components/LeadDetail.jsx";
import ClustersView from "./components/ClustersView.jsx";
import DisqualifiedView from "./components/DisqualifiedView.jsx";
import { getJob, getJobResults, getLeadOverrides, getLeadStatuses, processJob, setLeadOverride, setLeadStatus } from "./api.js";

export default function App() {
  const [job, setJob] = useState(null); // { job_id, preview, column_mapping }
  const [mappingConfirmed, setMappingConfirmed] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [processError, setProcessError] = useState(null);
  const [useLlm, setUseLlm] = useState(true);
  const [report, setReport] = useState(null); // full pipeline results
  const [view, setView] = useState("dashboard"); // dashboard | detail | clusters | disqualified
  const [selectedLeadId, setSelectedLeadId] = useState(null);
  const [leadStatuses, setLeadStatuses] = useState({});
  const [overrides, setOverrides] = useState({});
  const [progress, setProgress] = useState({ percent: 0, message: "" });
  const pollRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  useEffect(() => {
    if (!report) return;
    getLeadStatuses(job.job_id)
      .then((resp) => setLeadStatuses(resp.data.statuses || {}))
      .catch(() => {});
    getLeadOverrides(job.job_id)
      .then((resp) => setOverrides(resp.data.overrides || {}))
      .catch(() => {});
  }, [report]);

  const updateLeadStatus = async (leadId, status) => {
    try {
      const resp = await setLeadStatus(job.job_id, leadId, status);
      setLeadStatuses(resp.data.statuses || {});
    } catch (err) {
      // surface via console; UI stays usable
    }
  };

  const updateOverride = async (leadId, field, value) => {
    try {
      const resp = await setLeadOverride(job.job_id, leadId, field, value);
      setOverrides((prev) => ({ ...prev, [leadId]: resp.data.overrides || {} }));
      return true;
    } catch (err) {
      return false;
    }
  };

  const handleUploaded = (data) => {
    setJob(data);
    setMappingConfirmed(false);
    setReport(null);
    setProcessError(null);
    setView("dashboard");
    setSelectedLeadId(null);
  };

  const handleMappingConfirmed = () => {
    setMappingConfirmed(true);
  };

  const runProcess = async () => {
    setProcessing(true);
    setProcessError(null);
    setProgress({ percent: 5, message: "Starting pipeline..." });

    let procFailed = false;
    let procErrorMsg = null;
    // Fire the blocking process call in the background; it resolves when done.
    processJob(job.job_id, useLlm).catch((err) => {
      procFailed = true;
      procErrorMsg = err.response?.data?.error || "Processing failed.";
    });

    try {
      while (true) {
        if (procFailed) {
          setProcessError(procErrorMsg);
          break;
        }
        await new Promise((r) => setTimeout(r, 2000));
        let state = null;
        try {
          state = (await getJob(job.job_id)).data;
        } catch (e) {
          continue; // transient read error, keep polling
        }
        setProgress({
          percent: state.progress_percent || 0,
          message: state.message || "Processing...",
        });
        if (state.status === "completed") {
          const resp = await getJobResults(job.job_id);
          setReport(resp.data);
          setView("dashboard");
          break;
        }
        if (state.status === "failed") {
          setProcessError(state.message || "Processing failed.");
          break;
        }
      }
    } catch (err) {
      setProcessError("Could not fetch job progress.");
    } finally {
      setProcessing(false);
    }
  };

  const refreshResults = async () => {
    try {
      const resp = await getJobResults(job.job_id);
      setReport(resp.data);
    } catch (err) {
      // results not ready
    }
  };

  const handleSelectLead = (leadId) => {
    setSelectedLeadId(leadId);
    setView("detail");
  };

  let selectedLead = null;
  if (view === "detail" && report) {
    selectedLead = (report.qualified || []).find((l) => l.lead_id === selectedLeadId) || null;
  }

  const step = (label, active, done) => (
    <span className={`step ${done ? "done" : ""} ${active ? "active" : ""}`}>
      {label}
    </span>
  );

  return (
    <div className="app">
      <header className="app-header">
        <h1>Lead Triage System</h1>
        <p className="subtitle">
          Upload a messy CSV and the pipeline will detect, clean, analyze,
          cluster, and score your leads.
        </p>
      </header>

      <main className="app-main">
        {!job && <UploadZone onUploaded={handleUploaded} />}

        {job && !report && (
          <>
            <div className="flow-steps">
              {step("1. Upload & Preview", !mappingConfirmed, !mappingConfirmed)}
              {step("2. Column Mapping", mappingConfirmed, mappingConfirmed)}
              {step("3. Clean & Analyze", false, false)}
            </div>

            <FilePreview preview={job.preview} />

            {!mappingConfirmed ? (
              <ColumnMapping
                jobId={job.job_id}
                mapping={job.column_mapping}
                onConfirmed={handleMappingConfirmed}
              />
            ) : (
              <div className="notice success">
                <p>✅ Mapping confirmed. Ready to process {job.preview.row_count} leads.</p>
                <label className="toggle-row">
                  <span className="toggle-label">Analysis mode:</span>
                  <button
                    type="button"
                    className={`toggle ${useLlm ? "on" : ""}`}
                    onClick={() => setUseLlm(!useLlm)}
                    aria-pressed={useLlm}
                  >
                    <span className="toggle-track" />
                    <span className="toggle-thumb" />
                  </button>
                  <span className="toggle-mode">
                    {useLlm ? "LLM (OpenAI) — richer analysis, ~5 min" : "Heuristics — instant, zero cost"}
                  </span>
                </label>
                {processError && <p className="error">{processError}</p>}
                {processing ? (
                  <div className="progress-box">
                    <div className="progress-track">
                      <div
                        className="progress-fill"
                        style={{ width: `${Math.min(100, Math.max(0, progress.percent))}%` }}
                      />
                    </div>
                    <p className="progress-message">
                      {progress.message || "Processing..."} ({Math.round(progress.percent)}%)
                    </p>
                    <p className="progress-hint">
                      {useLlm
                        ? "Running OpenAI analysis — this can take a few minutes."
                        : "Running heuristic analysis — usually instant."}
                    </p>
                  </div>
                ) : (
                  <button className="btn primary" onClick={runProcess} disabled={processing}>
                    Run Pipeline
                  </button>
                )}
              </div>
            )}
          </>
        )}

        {report && processing && (
          <div className="card">
            <div className="progress-box">
              <div className="progress-track">
                <div
                  className="progress-fill"
                  style={{ width: `${Math.min(100, Math.max(0, progress.percent))}%` }}
                />
              </div>
              <p className="progress-message">
                {progress.message || "Processing..."} ({Math.round(progress.percent)}%)
              </p>
              <p className="progress-hint">
                {useLlm
                  ? "Running OpenAI analysis — this can take a few minutes."
                  : "Running heuristic analysis — usually instant."}
              </p>
            </div>
          </div>
        )}

        {report && view === "dashboard" && (
          <Dashboard
            report={report}
            jobId={job.job_id}
            leadStatuses={leadStatuses}
            onSetLeadStatus={updateLeadStatus}
            onSelectLead={handleSelectLead}
            onViewClusters={() => setView("clusters")}
            onViewDisqualified={() => setView("disqualified")}
            onReprocess={runProcess}
            processing={processing}
          />
        )}

        {report && view === "detail" && (
          <LeadDetail
            jobId={job.job_id}
            lead={selectedLead}
            status={leadStatuses[selectedLead?.lead_id] || null}
            onSetLeadStatus={updateLeadStatus}
            overrides={overrides[selectedLead?.lead_id] || {}}
            onSetOverride={updateOverride}
            onReprocess={runProcess}
            processing={processing}
            onBack={() => setView("dashboard")}
          />
        )}

        {report && view === "clusters" && (
          <ClustersView report={report} onBack={() => setView("dashboard")} />
        )}

        {report && view === "disqualified" && (
          <DisqualifiedView report={report} onBack={() => setView("dashboard")} />
        )}
      </main>
    </div>
  );
}
