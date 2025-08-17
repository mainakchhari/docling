"""Utilities to post-process Docling's Markdown output for payslips.

This script focuses on two recurring issues observed when converting
structured payslip PDFs to Markdown using Docling:

- Personal details in the header (e.g., Name, Designation, EmpNo, PAN,
  UAN, PF No., E.S.I. No., Date of Joining, Payable Days, Bank Name,
  Bank Account, IFS Code, Location) can be extracted out-of-order or
  occasionally bleed into the first table.
- The first data table may include a spurious row where the above
  header labels/values are merged into the table grid.

To mitigate this, the script:
1) Parses the pre-table header area to re-construct a clean set of
   key:value pairs using regex-based heuristics, optionally enriched by
   filename hints when present.
2) Replaces the original pre-table header block with a clean, ordered
   key:value list.
3) Cleans the first table by removing any rows that contain header-like
   keys so that personal details never appear inside the table.

Note: The post-processing aims to be conservative and only affects the
header area and the first table's spurious header-like rows. The main
tables are otherwise left intact.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
)
from docling.document_converter import DocumentConverter, PdfFormatOption


def extract_filename_hints(pdf_path: Path) -> Dict[str, str]:
    """Infer header fields from the input filename when possible.

    Many payroll systems export files following conventions such as
    "MT_Payslip_6_2024_First_Last_123456" where the last numeric token
    is an employee number and the preceding tokens represent the full
    name. This function extracts such hints to help correct noisy header
    extractions.

    Parameters
    ----------
    pdf_path: Path
        Path to the input PDF.

    Returns
    -------
    Dict[str, str]
        A dictionary containing optional keys such as "EmpNo" and
        "Name" when these can be reliably inferred from the filename.
    """
    hints: Dict[str, str] = {}
    stem = pdf_path.stem
    parts = stem.split("_")
    # Heuristic for files like: MT_Payslip_6_2024_Mainak_Chhari_527564
    if len(parts) >= 3:
        last = parts[-1]
        prev = parts[-2]
        # EmpNo is often the last numeric suffix
        if re.fullmatch(r"\d{4,}", last or ""):
            hints["EmpNo"] = last
        # Name may be just before EmpNo; try combining two prior tokens if they look like a name
        if re.fullmatch(r"[A-Za-z]+", prev or "") and len(parts) >= 4:
            maybe_name = parts[-3] + " " + parts[-2]
            if re.fullmatch(r"[A-Z][a-zA-Z]+ [A-Z][a-zA-Z]+", maybe_name):
                hints["Name"] = maybe_name
    return hints


def parse_header_pairs(md_text: str, pdf_path: Path) -> Dict[str, str]:
    """Extract a clean mapping of header key:value pairs from Markdown.

    The function limits itself to the pre-table portion of the Markdown
    output and uses regex heuristics to find values for standard
    payslip fields (e.g., PAN, UAN, PF No., IFS Code, Date of Joining,
    Payable Days, Bank Account, Bank Name, Location). It also applies
    filename hints when beneficial and attempts a best-effort guess for
    "Name", "Designation", and "EmpNo".

    Parameters
    ----------
    md_text: str
        The full Markdown content exported by Docling.
    pdf_path: Path
        Path to the original PDF; used for filename-based hints.

    Returns
    -------
    Dict[str, str]
        A dictionary mapping header field names to their detected
        values. Only fields that are confidently detected are included.
    """
    header_map: Dict[str, str] = {}

    # Limit parsing to the pre-table header block (before first markdown table or first heading)
    cut_idx = len(md_text)
    for marker in ["\n| ", "\n## ", "\n# "]:
        i = md_text.find(marker)
        if i != -1:
            cut_idx = min(cut_idx, i)
    header_block = md_text[:cut_idx]
    lines = [ln.strip() for ln in header_block.splitlines() if ln.strip()]

    # Regex patterns
    pan_re = re.compile(r"\b[A-Z]{5}[A-Z0-9]{4}[A-Z]\b")
    uan_re = re.compile(r"\b\d{12}\b")
    pf_re = re.compile(r"\b[A-Z]{1,3}/\d+/\d+\b")
    ifsc_re = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
    date_re = re.compile(r"\b\d{2}-\d{2}-\d{4}\b")
    long_digits_re = re.compile(r"\b\d{10,}\b")  # bank account typically >= 10 digits

    # Scan entire header block for unique identifiers
    pan = pan_re.search(header_block)
    if pan:
        header_map["PAN"] = pan.group(0)

    # UAN: prefer 12-digit unique
    uan = None
    for m in uan_re.finditer(header_block):
        # Avoid capturing the bank account if 12 digits could appear there; we'll remove later if conflicts
        uan = m.group(0)
    if uan:
        header_map["UAN"] = uan

    # PF No.
    pf = pf_re.search(header_block)
    if pf:
        header_map["PF No."] = pf.group(0)

    # Extract the combined labels/values row for joining, days, bank, account, ifsc, location
    # Find the line that contains these labels (or just try to parse values from any line with a date and IFSC)
    join_line: Optional[str] = None
    for ln in lines:
        if date_re.search(ln) and ifsc_re.search(ln):
            join_line = ln
            break
    if join_line:
        date_m = date_re.search(join_line)
        if date_m:
            header_map["Date of Joining"] = date_m.group(0)

        # Remaining after date
        rest = join_line[date_m.end() :] if date_m else join_line
        # Payable days: first small integer (<= 3 digits)
        days_m = re.search(r"\b\d{1,3}\b", rest)
        if days_m:
            header_map["Payable Days"] = days_m.group(0)
            rest2 = rest[days_m.end() :]
        else:
            rest2 = rest

        # IFSC and account
        ifsc_m = ifsc_re.search(rest2)
        acct_m = None
        for m in long_digits_re.finditer(rest2):
            # choose the longest digit span before IFSC
            if ifsc_m and m.start() < ifsc_m.start():
                if not acct_m or len(m.group(0)) > len(acct_m.group(0)):
                    acct_m = m
        if acct_m:
            header_map["Bank Account"] = acct_m.group(0)
        if ifsc_m:
            header_map["IFS Code"] = ifsc_m.group(0)

        # Bank Name: text between payable days and account digits
        bank_name = None
        if days_m and acct_m:
            between = rest2[days_m.end() : acct_m.start()]
            bank_name = between.strip()
            # collapse multiple spaces
            bank_name = re.sub(r"\s+", " ", bank_name)
        if bank_name:
            header_map["Bank Name"] = bank_name

        # Location: text after IFSC
        if ifsc_m:
            after_ifsc = rest2[ifsc_m.end() :].strip()
            after_ifsc = re.sub(r"\s+", " ", after_ifsc)
            if after_ifsc:
                header_map["Location"] = after_ifsc

    # Try to find Designation (look for common role keywords)
    role_keywords = (
        "Engineer",
        "Manager",
        "Director",
        "Analyst",
        "Developer",
        "Consultant",
        "Associate",
        "Lead",
        "Specialist",
        "Architect",
    )
    for ln in lines:
        if any(k in ln for k in role_keywords) and len(ln.split()) <= 5:
            header_map.setdefault("Designation", ln)
            break

    # Name: choose a likely person name (Title Case words) not equal to designation
    if "Name" not in header_map:
        for ln in lines:
            if ln == header_map.get("Designation"):
                continue
            if re.fullmatch(r"[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+){1,2}", ln):
                header_map["Name"] = ln
                break

    # EmpNo: prefer filename hint else choose a small integer not used elsewhere
    hints = extract_filename_hints(pdf_path)
    if "EmpNo" in hints:
        header_map["EmpNo"] = hints["EmpNo"]
    else:
        used_nums = set()
        for k in ("UAN", "Bank Account", "Payable Days"):
            v = header_map.get(k)
            if v and v.isdigit():
                used_nums.add(v)
        for ln in lines:
            m = re.fullmatch(r"\d{4,8}", ln)
            if m and m.group(0) not in used_nums:
                header_map["EmpNo"] = m.group(0)
                break

    # Prefer filename hint for Name if available
    if "Name" in hints:
        header_map["Name"] = hints["Name"]

    return header_map


def rewrite_header(md_text: str, header_map: Dict[str, str]) -> str:
    """Replace the original pre-table header with a clean key:value list.

    Parameters
    ----------
    md_text: str
        The full Markdown content exported by Docling.
    header_map: Dict[str, str]
        The cleaned header mapping produced by :func:`parse_header_pairs`.

    Returns
    -------
    str
        Markdown text with a normalized key:value header section at the
        top (before any table or heading markers).
    """
    # Build a clean header section
    order = [
        "Name",
        "Designation",
        "EmpNo",
        "PAN",
        "UAN",
        "PF No.",
        "E.S.I. No.",  # may remain missing
        "Date of Joining",
        "Payable Days",
        "Bank Name",
        "Bank Account",
        "IFS Code",
        "Location",
    ]
    lines = []
    for key in order:
        val = header_map.get(key)
        if val:
            lines.append(f"**{key}**: {val}")

    clean_header = "\n".join(lines) + "\n\n"

    # Replace the original header block (before first table/heading) with the clean header
    cut_idx = len(md_text)
    for marker in ["\n| ", "\n## ", "\n# "]:
        i = md_text.find(marker)
        if i != -1:
            cut_idx = min(cut_idx, i)
    rest = md_text[cut_idx:]
    return clean_header + rest


def _clean_first_table(md_text: str, header_keys: Dict[str, str]) -> str:
    """Remove spurious header-like rows from the first Markdown table.

    Some conversions occasionally merge header labels/values into the
    first table. This function removes any rows in the first table that
    clearly contain personal header keys such as "PAN", "UAN", etc.,
    while preserving the rest of the table intact.

    Parameters
    ----------
    md_text: str
        The full Markdown content exported by Docling, possibly already
        modified by :func:`rewrite_header`.
    header_keys: Dict[str, str]
        A dictionary of header field keys to check for (values are
        ignored). Keys should be canonical names, e.g. "PAN", "UAN".

    Returns
    -------
    str
        Markdown text with the first table cleaned of any header-like
        rows.
    """
    lines = md_text.splitlines(keepends=True)

    # find first table block
    start = None
    for idx, ln in enumerate(lines):
        if ln.lstrip().startswith("|"):
            start = idx
            break
    if start is None:
        return md_text

    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1

    table_lines = lines[start:end]

    # Build a set of lowercase keys to detect
    key_tokens = set(k.lower() for k in header_keys.keys())
    # Also include combined label string often merged into a row
    key_tokens.update(
        [
            "date of joining",
            "payable days",
            "bank name",
            "bank account",
            "ifs code",
            "location",
        ]
    )

    def is_alignment_row(s: str) -> bool:
        """Check whether a Markdown table row is an alignment separator.

        Considers rows like "| --- | :---: | ---: |" as alignment rows
        that should not be removed.
        """
        body = s.strip()
        return body.startswith("|") and set(body.replace("|", "").strip()) <= {
            "-",
            ":",
            " ",
        }

    filtered: list[str] = []
    for ln in table_lines:
        ln_lower = ln.lower()
        if is_alignment_row(ln):
            filtered.append(ln)
            continue
        # keep header row and data rows unless they contain any header key token
        if any(tok in ln_lower for tok in key_tokens):
            continue
        filtered.append(ln)

    if filtered == table_lines:
        return md_text

    new_text = "".join(lines[:start]) + "".join(filtered) + "".join(lines[end:])
    return new_text


def convert_with_fix(pdf_path: Path, out_dir: Path) -> Path:
    """Convert a PDF with Docling and apply header/table corrections.

    This is a convenience wrapper that runs Docling's PDF conversion
    with table structure enabled (no OCR by default), then normalizes
    the header section and removes any spurious header-like rows from
    the first table.

    Parameters
    ----------
    pdf_path: Path
        Path to the input PDF.
    out_dir: Path
        Output directory where the corrected ``.fixed.md`` file will be
        written. The directory is created if it does not exist.

    Returns
    -------
    Path
        The path to the written ``.fixed.md`` file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    opts = PdfPipelineOptions()
    opts.do_ocr = False
    opts.do_table_structure = True
    opts.table_structure_options.mode = TableFormerMode.ACCURATE
    # Keep default cell matching; header fix operates on markdown, not tables

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    conv_res = converter.convert(pdf_path)
    md_text = conv_res.document.export_to_markdown()

    header_map = parse_header_pairs(md_text, pdf_path)
    fixed_md = rewrite_header(md_text, header_map)
    # Clean spurious header-like rows accidentally merged into the first table
    fixed_md = _clean_first_table(
        fixed_md,
        {
            "Name": "",
            "Designation": "",
            "EmpNo": "",
            "PAN": "",
            "UAN": "",
            "PF No.": "",
            "E.S.I. No.": "",
            "Date of Joining": "",
            "Payable Days": "",
            "Bank Name": "",
            "Bank Account": "",
            "IFS Code": "",
            "Location": "",
        },
    )

    out_path = out_dir / (pdf_path.stem + ".fixed.md")
    out_path.write_text(fixed_md)
    return out_path


def main() -> None:
    """CLI entrypoint.

    Usage:
        uv run python examples/fix_payslip_header.py INPUT.pdf --out ./.ungit
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Fix payslip header pairing in Markdown output."
    )
    parser.add_argument("pdf", type=Path, help="Input PDF path")
    parser.add_argument(
        "--out", type=Path, default=Path("./.ungit"), help="Output directory"
    )
    args = parser.parse_args()

    out_path = convert_with_fix(args.pdf, args.out)
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
