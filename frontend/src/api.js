import axios from "axios";

const client = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
});

export function uploadCsv(file) {
  const form = new FormData();
  form.append("file", file);
  return client.post("/leads/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export function getJob(jobId) {
  return client.get(`/jobs/${jobId}`);
}

export function confirmMapping(jobId, mapping) {
  return client.post(`/jobs/${jobId}/mapping`, { mapping });
}

export function processJob(jobId, useLlm) {
  return client.post(`/jobs/${jobId}/process`, { use_llm: useLlm });
}

export function getJobResults(jobId) {
  return client.get(`/jobs/${jobId}/results`);
}

export function getLeads(jobId, params = {}) {
  return client.get(`/jobs/${jobId}/leads`, { params });
}

export function getLead(jobId, leadId) {
  return client.get(`/jobs/${jobId}/leads/${leadId}`);
}

export function getClusters(jobId) {
  return client.get(`/jobs/${jobId}/clusters`);
}

export function getCluster(jobId, clusterId) {
  return client.get(`/jobs/${jobId}/clusters/${clusterId}`);
}

export function getLeadStatuses(jobId) {
  return client.get(`/jobs/${jobId}/lead-status`);
}

export function setLeadStatus(jobId, leadId, status) {
  return client.post(`/jobs/${jobId}/leads/${leadId}/status`, { status });
}

export function getLeadOverrides(jobId) {
  return client.get(`/jobs/${jobId}/lead-overrides`);
}

export function setLeadOverride(jobId, leadId, field, value) {
  return client.post(`/jobs/${jobId}/leads/${leadId}/override`, { field, value });
}

export function exportCsvUrl(jobId, params = {}) {
  const qs = new URLSearchParams(params).toString();
  return `/api/v1/jobs/${jobId}/export/csv${qs ? `?${qs}` : ""}`;
}

export function exportJsonUrl(jobId) {
  return `/api/v1/jobs/${jobId}/export/json`;
}

export default client;
