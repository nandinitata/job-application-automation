#!/usr/bin/env python3
"""Convert tailored resume/cover letter markdown to PDF via LaTeX.

Usage:
    python3 scripts/md_to_pdf.py <input.md> [output.pdf]

For resumes: parses markdown, fills LaTeX template, compiles to PDF.
For cover letters: generates a simple LaTeX letter and compiles.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "resume_template.tex"


def escape_latex(text):
    """Escape special LaTeX characters."""
    replacements = [
        ("\\", "\\textbackslash{}"),
        ("&", "\\&"),
        ("%", "\\%"),
        ("$", "\\$"),
        ("#", "\\#"),
        ("_", "\\_"),
        ("{", "\\{"),
        ("}", "\\}"),
        ("~", "\\textasciitilde{}"),
        ("^", "\\textasciicircum{}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    # Restore intentional LaTeX commands that got double-escaped
    text = text.replace("\\\\textbackslash\\{\\}", "\\textbackslash{}")
    text = text.replace("\\\\&", "\\&")
    return text


def md_links_to_latex(text):
    """Convert [text](url) markdown links to LaTeX \\href before escaping."""
    # Extract links first, replace with placeholders, then restore after escaping
    links = []
    def replace_link(m):
        links.append((m.group(1), m.group(2)))
        return f"LINKPLACEHOLDER{len(links)-1}ENDLINK"
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, text)
    return text, links


def restore_links(text, links):
    """Restore link placeholders with LaTeX href commands."""
    for i, (label, url) in enumerate(links):
        latex_link = f"\\href{{{url}}}{{{label}}}"
        text = text.replace(f"LINKPLACEHOLDER{i}ENDLINK", latex_link)
    return text


def md_to_latex_rich(text):
    """Convert markdown formatting to LaTeX: links, bold, italic."""
    # 1. Extract links before escaping
    text, links = md_links_to_latex(text)
    # 2. Escape LaTeX special chars
    text = escape_latex(text)
    # 3. Convert bold/italic
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)
    # 4. Restore links (already have correct LaTeX, no escaping needed)
    text = restore_links(text, links)
    return text


def md_bold_italic_to_latex(text):
    """Convert **bold** and *italic* to LaTeX (legacy, use md_to_latex_rich for new code)."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"\*(.+?)\*", r"\\textit{\1}", text)
    return text


def parse_resume_md(lines):
    """Parse resume markdown into structured sections."""
    sections = {}
    current_section = None
    current_content = []

    for line in lines:
        line = line.rstrip()
        if line.startswith("# ") and not line.startswith("## "):
            sections["name"] = line[2:].strip()
            continue
        if line.startswith("## "):
            if current_section:
                sections[current_section] = current_content
            current_section = line[3:].strip().lower()
            current_content = []
            continue
        if current_section is None and "|" in line and "name" in sections:
            sections["contact"] = line.strip()
            continue
        current_content.append(line)

    if current_section:
        sections[current_section] = current_content

    return sections


def build_work_entries(lines):
    """Build LaTeX work experience entries from parsed lines."""
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Entry header: **Company**, *Role* | Dates
        if line.startswith("**"):
            parts = line.split("|", 1)
            raw = parts[0].strip()
            dates = parts[1].strip() if len(parts) > 1 else ""
            # Re-parse for bold company and italic role
            match = re.match(r"\*\*(.+?)\*\*,?\s*\*(.+?)\*", raw)
            if match:
                company = escape_latex(match.group(1))
                role = escape_latex(match.group(2))
                left = f"\\textbf{{{company}}}, \\textit{{{role}}}"
            else:
                left = md_to_latex_rich(raw)
            dates = escape_latex(dates)
            entries.append(f"\\entry{{{left}}}{{{dates}}}")
            i += 1
            continue

        # Italic sub-line: *Location*
        if line.startswith("*") and not line.startswith("**") and line.endswith("*"):
            location = escape_latex(line.strip("* "))
            entries.append(f"\\subentry{{{location}}}")
            i += 1
            continue

        # Bullet point
        if line.startswith("- "):
            text = line[2:]
            while i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt and not nxt.startswith(("-", "**", "*", "#")):
                    text += " " + nxt
                    i += 1
                else:
                    break
            text = md_to_latex_rich(text)
            entries.append(f"\\begin{{itemize}}\n\\item {text}\n\\end{{itemize}}")
            i += 1
            continue

        i += 1

    return "\n".join(entries)


def split_entry_line(line):
    """Split a **Title (Link)** | Dates line, handling markdown links in the title.

    Returns (title_latex, dates_latex).
    """
    # First extract markdown links to avoid | inside URLs causing bad splits
    line_no_links, links = md_links_to_latex(line)

    # Now split on the last | to separate title from dates
    if "|" in line_no_links:
        # Find the last | which separates title from date
        idx = line_no_links.rfind("|")
        raw_title = line_no_links[:idx].strip()
        raw_dates = line_no_links[idx+1:].strip()
    else:
        raw_title = line_no_links.strip()
        raw_dates = ""

    # Strip ** from title (remove all leading/trailing * characters)
    raw_title = re.sub(r"^\*+|\*+$", "", raw_title).strip()
    # Also remove any stray ** that might appear mid-string from markdown
    raw_title = raw_title.replace("**", "")

    # Escape and restore links
    title = escape_latex(raw_title)
    title = restore_links(title, links)
    dates = escape_latex(raw_dates)

    return title, dates


def build_project_entries(lines):
    """Build LaTeX project entries."""
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if line.startswith("**"):
            title, dates = split_entry_line(line)
            entries.append(f"\\entry{{{title}}}{{{dates}}}")
            i += 1
            continue

        if line.startswith("- "):
            text = line[2:]
            while i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt and not nxt.startswith(("-", "**", "#")):
                    text += " " + nxt
                    i += 1
                else:
                    break
            text = md_to_latex_rich(text)
            entries.append(f"\\begin{{itemize}}\n\\item {text}\n\\end{{itemize}}")
            i += 1
            continue

        i += 1

    return "\n".join(entries)


def build_award_entries(lines):
    """Build LaTeX award entries."""
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        if line.startswith("**"):
            title, dates = split_entry_line(line)
            entries.append(f"\\entry{{{title}}}{{{dates}}}")
            i += 1
            continue

        if line.startswith("- "):
            text = line[2:]
            while i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt and not nxt.startswith(("-", "**", "#")):
                    text += " " + nxt
                    i += 1
                else:
                    break
            text = md_to_latex_rich(text)
            entries.append(f"\\begin{{itemize}}\n\\item {text}\n\\end{{itemize}}")
            i += 1
            continue

        i += 1

    return "\n".join(entries)


def build_skills(lines):
    """Build LaTeX skill items."""
    items = []
    for line in lines:
        line = line.strip()
        if line.startswith("- "):
            text = line[2:]
            text = md_to_latex_rich(text)
            items.append(f"\\item {text}")
    return "\n".join(items)


def resume_md_to_latex(md_path):
    """Convert resume markdown to LaTeX string."""
    with open(md_path) as f:
        lines = f.readlines()

    sections = parse_resume_md(lines)
    template = TEMPLATE_PATH.read_text()

    # Contact parsing
    contact = sections.get("contact", "")
    contact_parts = [p.strip() for p in contact.split("|")]
    email = contact_parts[1] if len(contact_parts) > 1 else ""
    linkedin = contact_parts[2] if len(contact_parts) > 2 else ""

    # Portfolio is optional in older tailored resumes; fall back to user_profile.json so
    # legacy markdown still renders without leaving an orphaned @@PORTFOLIO@@ placeholder.
    portfolio = contact_parts[3] if len(contact_parts) >= 5 else ""
    if not portfolio:
        profile_path = PROJECT_ROOT / "config" / "user_profile.json"
        if profile_path.exists():
            try:
                with open(profile_path) as f:
                    profile = json.load(f)
                url = profile.get("personal", {}).get("portfolio_url", "")
                portfolio = url.replace("https://", "").replace("http://", "").rstrip("/")
            except (json.JSONDecodeError, OSError):
                portfolio = ""

    location = contact_parts[-1] if len(contact_parts) > 3 else ""

    template = template.replace("@@EMAIL@@", escape_latex(email))
    template = template.replace("@@LINKEDIN@@", escape_latex(linkedin))
    template = template.replace("@@PORTFOLIO@@", escape_latex(portfolio))
    template = template.replace("@@LOCATION@@", escape_latex(location))

    # Education
    edu_lines = sections.get("education", [])
    edu_entries = []
    for line in edu_lines:
        line = line.strip()
        if line.startswith("**") and "|" in line:
            edu_entries.append(line)
        elif line.startswith("*") and not line.startswith("**"):
            edu_entries.append(line)
        elif line.startswith("Coursework"):
            edu_entries.append(line)

    # Each education entry needs exactly 3 lines: header (**Degree** | Dates),
    # university (*University, GPA*), and Coursework. Malformed inputs used to
    # leave raw @@EDU*@@ markers in the PDF.
    if len(edu_entries) not in (0, 3, 6):
        raise ValueError(
            f"Education section has {len(edu_entries)} entries; expected 0, 3, or 6 "
            "(each degree needs a header line, a university line, and a Coursework line). "
            f"Parsed entries: {edu_entries}"
        )

    if len(edu_entries) >= 3:
        parts1 = edu_entries[0].split("|", 1)
        template = template.replace("@@EDU1DATES@@", escape_latex(parts1[1].strip()) if len(parts1) > 1 else "")
        template = template.replace("@@EDU1UNIVERSITY@@", escape_latex(edu_entries[1].strip("* ")))
        template = template.replace("@@EDU1COURSEWORK@@", escape_latex(edu_entries[2]))
    if len(edu_entries) >= 6:
        parts2 = edu_entries[3].split("|", 1)
        template = template.replace("@@EDU2DATES@@", escape_latex(parts2[1].strip()) if len(parts2) > 1 else "")
        template = template.replace("@@EDU2UNIVERSITY@@", escape_latex(edu_entries[4].strip("* ")))
        template = template.replace("@@EDU2COURSEWORK@@", escape_latex(edu_entries[5]))

    # Skills
    template = template.replace("@@SKILLS@@", build_skills(sections.get("skills", [])))

    # Work Experience
    template = template.replace("@@WORKENTRIES@@", build_work_entries(sections.get("work experience", [])))

    # Projects
    project_entries = build_project_entries(sections.get("projects", []))
    template = template.replace("@@PROJECTENTRIES@@", project_entries)
    if not project_entries.strip():
        template = re.sub(r"%==== PROJECTS ====%\s*\\ressection\{Projects\}\s*", "", template)

    # Awards
    award_entries = build_award_entries(sections.get("awards", []))
    template = template.replace("@@AWARDENTRIES@@", award_entries)
    if not award_entries.strip():
        template = re.sub(r"%==== AWARDS ====%\s*\\ressection\{Awards\}\s*", "", template)

    leftover = re.findall(r"@@[A-Z0-9_]+@@", template)
    if leftover:
        raise ValueError(
            f"Unsubstituted placeholders would be rendered in the PDF: {sorted(set(leftover))}. "
            "Check that the markdown supplies the expected fields for each section."
        )

    return template


def cover_letter_md_to_latex(md_path):
    """Convert cover letter markdown to a simple LaTeX document."""
    with open(md_path) as f:
        text = f.read()

    # Remove markdown headers
    text = re.sub(r"^#+ .*$", "", text, flags=re.MULTILINE)

    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    body = "\n\n".join(md_to_latex_rich(p) for p in paragraphs)

    return f"""\\documentclass[11pt,letterpaper]{{article}}
\\usepackage[top=0.75in, bottom=0.75in, left=0.85in, right=0.85in]{{geometry}}
\\usepackage[T1]{{fontenc}}
\\usepackage{{lmodern}}
\\usepackage[colorlinks=true,urlcolor=blue,linkcolor=blue]{{hyperref}}
\\pagestyle{{empty}}
\\setlength{{\\parindent}}{{0pt}}
\\setlength{{\\parskip}}{{10pt}}

\\begin{{document}}

{body}

\\end{{document}}
"""


def compile_latex(tex_content, output_path):
    """Compile LaTeX to PDF using pdflatex."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "document.tex")
        with open(tex_path, "w") as f:
            f.write(tex_content)

        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-output-directory", tmpdir, tex_path],
            capture_output=True, text=True, timeout=30
        )

        pdf_path = os.path.join(tmpdir, "document.pdf")
        if os.path.exists(pdf_path):
            import shutil
            shutil.copy2(pdf_path, output_path)
            return True
        else:
            print("LaTeX compilation failed:", file=sys.stderr)
            print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout, file=sys.stderr)
            return False


def md_to_pdf(input_path, output_path=None):
    if output_path is None:
        output_path = input_path.rsplit(".", 1)[0] + ".pdf"

    is_cover = "cover_letter" in input_path.lower() or "cover" in input_path.lower()

    if is_cover:
        tex = cover_letter_md_to_latex(input_path)
    else:
        tex = resume_md_to_latex(input_path)

    if compile_latex(tex, output_path):
        return output_path
    else:
        print(f"Failed to generate PDF for {input_path}", file=sys.stderr)
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/md_to_pdf.py <input.md> [output.pdf]")
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    result = md_to_pdf(inp, out)
    if result:
        print(f"PDF generated: {result}")
    else:
        sys.exit(1)
