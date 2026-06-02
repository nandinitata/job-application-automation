#!/usr/bin/env python3
"""Simple dashboard server for reviewing job pipeline results."""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = 8420
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DASHBOARD_DIR = Path(__file__).resolve().parent


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.serve_file(DASHBOARD_DIR / "index.html", "text/html")
        elif path == "/api/jobs_found":
            self.serve_json(DATA_DIR / "jobs_found.json")
        elif path == "/api/jobs_scored":
            self.serve_json(DATA_DIR / "jobs_scored.json")
        elif path == "/api/company_careers":
            self.serve_json(DATA_DIR / "company_careers.json")
        elif path == "/api/applications":
            self.serve_json(DATA_DIR / "applications_submitted.json")
        elif path == "/api/verified":
            self.serve_json(DATA_DIR / "applications_verified.json")
        elif path == "/api/tailored":
            self.serve_tailored_index()
        elif path.startswith("/api/tailored_file/"):
            rel = path[len("/api/tailored_file/"):]
            filepath = DATA_DIR / "tailored_materials" / rel
            if filepath.suffix == ".pdf":
                self.serve_binary(filepath, "application/pdf")
            else:
                self.serve_file(filepath, "text/plain")
        elif path == "/api/stats":
            self.serve_stats()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/update_status":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len))
            self.update_job_status(body)
        else:
            self.send_error(404)

    def serve_file(self, filepath, content_type):
        try:
            with open(filepath, "r") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode())
        except FileNotFoundError:
            self.send_error(404)

    def serve_json(self, filepath):
        try:
            with open(filepath, "r") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode())
        except FileNotFoundError:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"metadata":{},"jobs":[],"scored_jobs":[],"companies":[],"applications":[],"verifications":[]}')

    def serve_stats(self):
        stats = {}
        for name, key in [
            ("jobs_found", "jobs"),
            ("jobs_scored", "scored_jobs"),
            ("applications_submitted", "applications"),
        ]:
            filepath = DATA_DIR / f"{name}.json"
            try:
                with open(filepath) as f:
                    data = json.load(f)
                stats[name] = len(data.get(key, []))
                stats[f"{name}_metadata"] = data.get("metadata", {})
            except (FileNotFoundError, json.JSONDecodeError):
                stats[name] = 0
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(stats).encode())

    def update_job_status(self, body):
        """Update application_status for a job in jobs_scored.json."""
        job_id = body.get("job_id")
        new_status = body.get("status")
        if not job_id or not new_status:
            self.send_error(400, "Missing job_id or status")
            return

        filepath = DATA_DIR / "jobs_scored.json"
        try:
            with open(filepath) as f:
                data = json.load(f)
            for job in data.get("scored_jobs", []):
                if job.get("job_id") == job_id:
                    job["application_status"] = new_status
                    break
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
        except FileNotFoundError:
            self.send_error(404, "jobs_scored.json not found")

    def serve_binary(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404)

    def serve_tailored_index(self):
        """List all tailored materials organized by company/role."""
        tailored_dir = DATA_DIR / "tailored_materials"
        result = {}
        if tailored_dir.exists():
            for company_dir in sorted(tailored_dir.iterdir()):
                if not company_dir.is_dir() or company_dir.name.startswith("."):
                    continue
                company_files = []
                # Check for role subdirectories (new structure)
                for item in sorted(company_dir.iterdir()):
                    if item.is_dir():
                        # New structure: company/role/files
                        for f in sorted(item.iterdir()):
                            if f.suffix == ".md":
                                pdf_candidates = [
                                    p for p in item.iterdir()
                                    if p.suffix == ".pdf" and (
                                        ("resume" in f.name and "Cover" not in p.name) or
                                        ("cover" in f.name and "Cover" in p.name)
                                    )
                                ]
                                pdf = pdf_candidates[0] if pdf_candidates else None
                                entry = {
                                    "name": f.name,
                                    "path": f"{company_dir.name}/{item.name}/{f.name}",
                                    "role": item.name,
                                    "type": "resume" if "resume" in f.name else "cover_letter",
                                    "size": f.stat().st_size,
                                    "has_pdf": pdf is not None,
                                }
                                if pdf:
                                    entry["pdf_path"] = f"{company_dir.name}/{item.name}/{pdf.name}"
                                    entry["pdf_size"] = pdf.stat().st_size
                                company_files.append(entry)
                    elif item.suffix == ".md":
                        # Old structure: company/files (backward compat)
                        pdf_path = item.with_suffix(".pdf")
                        # Also check for Sai_Nandini_Tata_*.pdf
                        pdf_matches = [p for p in company_dir.iterdir() if p.suffix == ".pdf" and (
                            p.stem == item.stem or
                            ("resume" in item.name and "Cover" not in p.name and p.suffix == ".pdf") or
                            ("cover" in item.name and "Cover" in p.name)
                        )]
                        pdf = pdf_matches[0] if pdf_matches else (pdf_path if pdf_path.exists() else None)
                        entry = {
                            "name": item.name,
                            "path": f"{company_dir.name}/{item.name}",
                            "role": "",
                            "type": "resume" if "resume" in item.name else "cover_letter",
                            "size": item.stat().st_size,
                            "has_pdf": pdf is not None,
                        }
                        if pdf:
                            entry["pdf_path"] = f"{company_dir.name}/{pdf.name}"
                            entry["pdf_size"] = pdf.stat().st_size
                        company_files.append(entry)
                if company_files:
                    result[company_dir.name] = company_files
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())

    def log_message(self, format, *args):
        pass  # Suppress request logs


if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), DashboardHandler)
    print(f"Dashboard running at http://localhost:{PORT}")
    print(f"Reading data from: {DATA_DIR}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
