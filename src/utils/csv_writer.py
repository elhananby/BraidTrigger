import csv
from typing import Dict, Any, List
import os


class CsvWriter:
    """
    A class for writing data to a CSV file.

    This class provides methods to write data to a CSV file, handling header writing
    and file management automatically.
    """

    def __init__(self, filename: str):
        """
        Initialize the CsvWriter.

        Args:
            filename (str): The name of the CSV file to write to.
        """
        self.filename = filename
        self.csv_file = None
        self.csv_writer = None
        self.headers_written = False

    def __enter__(self):
        """Context manager entry method."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit method."""
        self.close()

    def open(self):
        """Open the CSV file and initialize the writer."""
        mode = "a" if os.path.exists(self.filename) else "w"
        self.csv_file = open(self.filename, mode, newline="")
        self.csv_writer = csv.writer(self.csv_file)
        self.headers_written = self._check_headers()

    def _check_headers(self) -> bool:
        """
        Check if headers are already written in the file.

        Returns:
            bool: True if headers are already written, False otherwise.
        """
        if self.csv_file.tell() == 0:
            return False

        self.csv_file.seek(0)
        reader = csv.reader(self.csv_file)
        try:
            first_row = next(reader)
            return not all(str(item).isdigit() for item in first_row)
        except StopIteration:
            return False
        finally:
            self.csv_file.seek(0, 2)  # Move to the end of the file

    def write(self, data: Dict[str, Any]):
        """
        Write a row of data to the CSV file.

        Args:
            data (Dict[str, Any]): A dictionary containing the data to write.

        Raises:
            IOError: If the file is not open for writing.
        """
        if not self.csv_file or self.csv_file.closed:
            raise IOError("CSV file is not open for writing.")

        if not self.headers_written:
            self.csv_writer.writerow(data.keys())
            self.headers_written = True

        self.csv_writer.writerow(data.values())
        self.csv_file.flush()

    def write_rows(self, data: List[Dict[str, Any]]):
        """
        Write multiple rows of data to the CSV file.

        Args:
            data (List[Dict[str, Any]]): A list of dictionaries containing the data to write.

        Raises:
            IOError: If the file is not open for writing.
        """
        if not data:
            return

        if not self.csv_file or self.csv_file.closed:
            raise IOError("CSV file is not open for writing.")

        if not self.headers_written:
            self.csv_writer.writerow(data[0].keys())
            self.headers_written = True

        self.csv_writer.writerows(row.values() for row in data)
        self.csv_file.flush()

    def close(self):
        """Close the CSV file."""
        if self.csv_file and not self.csv_file.closed:
            self.csv_file.close()
            self.csv_writer = None


# Example usage
if __name__ == "__main__":
    with CsvWriter("example.csv") as writer:
        writer.write({"Name": "Alice", "Age": 30, "City": "New York"})
        writer.write({"Name": "Bob", "Age": 25, "City": "San Francisco"})
        writer.write_rows(
            [
                {"Name": "Charlie", "Age": 35, "City": "London"},
                {"Name": "David", "Age": 28, "City": "Paris"},
            ]
        )
