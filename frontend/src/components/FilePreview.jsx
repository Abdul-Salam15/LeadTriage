import React from "react";

export default function FilePreview({ preview }) {
  if (!preview) return null;
  return (
    <div className="preview-section">
      <h2>File Preview</h2>
      <div className="stat-grid">
        <div className="stat">
          <span className="stat-value">{preview.size_mb} MB</span>
          <span className="stat-label">File Size</span>
        </div>
        <div className="stat">
          <span className="stat-value">{preview.row_count}</span>
          <span className="stat-label">Rows</span>
        </div>
        <div className="stat">
          <span className="stat-value">{preview.detected_columns.length}</span>
          <span className="stat-label">Columns</span>
        </div>
        <div className="stat">
          <span className="stat-value">{preview.encoding}</span>
          <span className="stat-label">Encoding</span>
        </div>
      </div>

      {preview.sample_rows && preview.sample_rows.length > 0 && (
        <div className="sample-table-wrap">
          <h3>Sample Data</h3>
          <table className="sample-table">
            <thead>
              <tr>
                {preview.detected_columns.map((col, i) => (
                  <th key={i}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.sample_rows.slice(0, 3).map((row, ri) => (
                <tr key={ri}>
                  {preview.detected_columns.map((_, ci) => (
                    <td key={ci}>{row[ci] ?? ""}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
