import logging
import csv
import os   
from datetime import datetime

class LogsCSVFormatter(logging.Formatter):
    """Custom formatter to output logs in CSV format"""
    def __init__(self):
        super().__init__()
        self.output_fields = ['timestamp', 'level', 'module', 'function', 'message']

    def format(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')
        return {
            'timestamp': timestamp,
            'level': record.levelname,
            'module': record.module,
            'function': record.funcName,
            'message': record.getMessage()
        }

class CSVFileHandler(logging.FileHandler):
    """Custom file handler to write logs to CSV file"""
    def __init__(self, filename, mode='a'):
        super().__init__(filename, mode)
        self.formatter = LogsCSVFormatter()

        # Create CSV file with headers if it doesn't exist
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            with open(filename, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.formatter.output_fields)
                writer.writeheader()

    def emit(self, record):
        try:
            with open(self.baseFilename, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.formatter.output_fields)
                writer.writerow(self.formatter.format(record))
        except Exception:
            self.handleError(record)