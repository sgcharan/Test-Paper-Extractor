"""Read-only verification of extracted CBSE paper JSON against the source PDFs.

Nothing in here modifies cbse_extract or its output. It reads out/<run>/chemistry-*.json plus the PDFs and
writes findings, a report and a human review pack to a separate folder.
"""
