"""Spreadsheet adapter module."""

from mercadolivre_upload.adapters.spreadsheet.parser import SpreadsheetParser
from mercadolivre_upload.adapters.spreadsheet.header_detector import HeaderDetector

__all__ = ["SpreadsheetParser", "HeaderDetector"]
