import React, { useCallback, useRef, useState } from "react";
import { uploadCsv } from "../api.js";

const CANONICAL_FIELDS = [
  "lead_id",
  "created_date",
  "name",
  "email",
  "company",
  "employees",
  "website",
  "title",
  "source",
  "monthly_budget",
  "notes",
];

export default function UploadZone({ onUploaded }) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const inputRef = useRef(null);

  const handleFiles = useCallback((files) => {
    const file = files && files[0];
    if (!file) return;
    setError(null);
    setSelectedFile(file);
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragActive(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    setDragActive(false);
  }, []);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragActive(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;
    setUploading(true);
    setError(null);
    try {
      const { data } = await uploadCsv(selectedFile);
      onUploaded(data);
    } catch (err) {
      const detail =
        err?.response?.data?.error || "Upload failed. Please try again.";
      setError(detail);
    } finally {
      setUploading(false);
    }
  }, [selectedFile, onUploaded]);

  return (
    <div className="upload-section">
      <h2>Upload Leads CSV</h2>
      <div
        className={`dropzone${dragActive ? " drag-active" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          hidden
          onChange={(e) => handleFiles(e.target.files)}
        />
        <p className="dropzone-icon">📄</p>
        <p>
          <strong>Drag &amp; drop</strong> your CSV here, or{" "}
          <span className="link">click to browse</span>
        </p>
        <p className="hint">Max file size: 50MB</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {selectedFile && (
        <div className="file-card">
          <div className="file-row">
            <span className="file-name">{selectedFile.name}</span>
            <span className="file-size">
              {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </span>
          </div>
          <button
            className="btn primary"
            onClick={handleUpload}
            disabled={uploading}
          >
            {uploading ? "Uploading…" : "Upload & Analyze"}
          </button>
        </div>
      )}
    </div>
  );
}

export { CANONICAL_FIELDS };
