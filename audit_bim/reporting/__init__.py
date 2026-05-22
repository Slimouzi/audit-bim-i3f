"""Reporters : Word + XLSX."""
from .word_report import write_word_report
from .xlsx_annex import write_xlsx_annex

__all__ = ["write_word_report", "write_xlsx_annex"]
