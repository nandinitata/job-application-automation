#!/bin/bash
# Reset pipeline data for a fresh run
# Usage: ./scripts/reset_pipeline.sh

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$PROJECT_DIR/data"

echo "Resetting pipeline data in $DATA_DIR..."

# Remove pipeline output files
rm -f "$DATA_DIR/jobs_found.json"
rm -f "$DATA_DIR/jobs_scored.json"
rm -f "$DATA_DIR/applications_submitted.json"
rm -f "$DATA_DIR/applications_verified.json"
rm -f "$DATA_DIR/pipeline_log.json"
rm -f "$DATA_DIR/run_summary.md"
rm -f "$DATA_DIR/verification_summary.md"

# Clear tailored materials
rm -rf "$DATA_DIR/tailored_materials/"
mkdir -p "$DATA_DIR/tailored_materials"

# Clear screenshots
rm -rf "$DATA_DIR/screenshots/"
mkdir -p "$DATA_DIR/screenshots"

echo "Pipeline data reset complete. Ready for a fresh run."
