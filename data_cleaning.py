import pandas as pd # type: ignore
import numpy as np # type: ignore
import json
import re
import logging
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup # type: ignore
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Tuple


# Define possible data quality issues
class DataQualityIssue(Enum):
    MISSING_VALUE = "missing_value"
    INVALID_FORMAT = "invalid_format"
    INVALID_DATE = "invalid_date"
    HTML_PARSING_ERROR = "html_parsing_error"
    JSON_PARSING_ERROR = "json_parsing_error"


# Data structure for quality reports
@dataclass
class DataQualityReport:
    total_rows: int
    missing_values: Dict[str, int]
    invalid_formats: Dict[str, int]
    cleaning_actions: List[str]



class DataPreprocessor:
    def __init__(self):

        """Initialize the preprocessor with common regex patterns and configs."""
        self.url_pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
        self.code_block_pattern = re.compile(r'<code>(.*?)</code>', re.DOTALL)
        self.special_chars_pattern = re.compile(r'[^\w\s]')

        # Setup logging configuration
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def handle_missing_values(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Handle missing values based on column type and business rules.
        Returns DataFrame with handled missing values.
        """
        # Create copy to avoid modifying original
        df = df.copy()

        # Fill missing values based on data type
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        text_cols = df.select_dtypes(include=['object']).columns
        date_cols = [col for col in df.columns if 'date' in col.lower()]

        # Handle numeric columns
        df[numeric_cols] = df[numeric_cols].fillna(0)

        # Handle text columns
        df[text_cols] = df[text_cols].fillna("")

        # Handle date columns
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors='coerce')
            df[col] = df[col].fillna(pd.Timestamp.min)

        return df

    def clean_html(self, html_text: str) -> Tuple[str, List[str]]:
        """
        HTML cleaning with code block preservation and metadata extraction.
        Returns cleaned text and list of extracted code blocks.
        """
        if pd.isna(html_text):
            return "", []

        try:
            # Extract code blocks before cleaning
            code_blocks = self.code_block_pattern.findall(html_text)

            # Use BeautifulSoup for HTML parsing
            soup = BeautifulSoup(html_text, 'html.parser')

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Handle URLs - replace with placeholder
            text = soup.get_text()
            text = self.url_pattern.sub("[URL]", text)

            # Clean whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = ' '.join(chunk for chunk in chunks if chunk)

            return text, code_blocks

        except Exception as e:
            self.logger.error(f"HTML cleaning error: {str(e)}")
            return "", []

    def validate_dates(self, date_str: str) -> bool:
        """Validate date string format and range."""
        try:
            date = pd.to_datetime(date_str)
            min_date = pd.Timestamp('2008-01-01')
            max_date = pd.Timestamp.now()
            return min_date <= date <= max_date
        except:
            return False


    def transform_stackoverflow_data(self,df):
      """
      Transform StackOverflow data to have answers as JSON for each unique question.

      Args:
          df (pandas.DataFrame): Input DataFrame with question and answer data

      Returns:
          pandas.DataFrame: Transformed DataFrame with one row per question and answers as JSON
      """
      # Create a list to store the transformed data
      transformed_data = []

      # Group by question_id
      grouped = df.groupby('question_id')

      for question_id, group in grouped:
          # Get question details (will be same for all rows in group)
          question_data = {
              'question_id': int(question_id),
              'title': group['title'].iloc[0],
              'question_body': group['question_body'].iloc[0],
              'question_score': group['question_score'].iloc[0],
              'question_date': group['question_date'].iloc[0],
              'tags': group['tags'].iloc[0]
          }

          # Create answers list
          answers,answer_ids = [],[]
          for _, row in group.iterrows():
              answer = {
                  'answer_score': row['answer_score'],
                  'answer_id': int(row['answer_id']),
                  'answer_body': row['answer_body'],
                  'answer_date': row['answer_date']
              }
              answer_ids.append(str(row['answer_id']))
              answers.append(answer)

          # Add answers to question data
          sorted_answer = list(sorted(answers, key=lambda x: x['answer_score'], reverse=True))
          question_data['answers'] = sorted_answer[:2]
          question_data["answer_ids"] = answer_ids[:2]

          transformed_data.append(question_data)

      # Create new DataFrame from transformed data
      result_df = pd.DataFrame(transformed_data)

      # Sort by question_id for consistency
      result_df = result_df.sort_values('question_id').reset_index(drop=True)

      return result_df

    def clean_chunk(self, df_chunk: pd.DataFrame) -> pd.DataFrame:
        """Process a single chunk of data."""
        try:
            # Handle missing values
            df_chunk = self.handle_missing_values(df_chunk)

            # Process text columns in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor() as executor:
                for col in ['question_body', 'answer_body']:
                    # Clean HTML and extract code blocks

                    cleaned_results = list(executor.map(self.clean_html, df_chunk[col]))
                    df_chunk[f'{col}_cleaned'] = [result[0] for result in cleaned_results]
                    df_chunk[f'{col}_code_blocks'] = [result[1] for result in cleaned_results]

                    # Calculate metrics
                    df_chunk[f'{col}_url_count'] = df_chunk[col].str.count(self.url_pattern)
                    df_chunk[f'{col}_length'] = df_chunk[f'{col}_cleaned'].str.len()

            # Process dates
            date_cols = ['question_date', 'answer_date']
            for col in date_cols:
                df_chunk[col] = pd.to_datetime(df_chunk[col], errors='coerce')

            # Create preprocessing metadata
            df_chunk['preprocessing_metadata'] = df_chunk.apply(
                lambda row: json.dumps({
                    'question_urls': row['question_body_url_count'],
                    'answer_urls': row['answer_body_url_count'],
                    'question_length': row['question_body_length'],
                    'answer_length': row['answer_body_length'],
                    'has_code': bool(row['question_body_code_blocks'] or row['answer_body_code_blocks'])
                }), axis=1
            )

            return df_chunk

        except Exception as e:
            self.logger.error(f"Error processing chunk: {str(e)}")
            raise