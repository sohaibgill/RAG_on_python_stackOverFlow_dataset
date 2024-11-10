import logging
import pandas as pd
from data_cleaning import DataPreprocessor
from logging_classes import CSVFileHandler
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import sqlite3
import concurrent.futures
from typing import List,Dict,Any
import json
import re
from tqdm import tqdm
from data_cleaning import DataPreprocessor
from logging_classes import CSVFileHandler


# Data Ingestion pipeline.
class DataIngestionPipeline:
    def __init__(self, db_path: str = 'stackoverflow.db', chunk_size: int = 10000, log_file: str = 'pipeline_logs.csv'):
        """Initialize the pipeline with configurable chunk size and logging."""
        self.db_path = db_path
        self.chunk_size = chunk_size
        self.preprocessor = DataPreprocessor()

        # Setup logging
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            # Console handler with standard formatting
            console_handler = logging.StreamHandler()
            console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_formatter)

            # CSV file handler
            csv_handler = CSVFileHandler(log_file)

            # Add both handlers
            self.logger.addHandler(console_handler)
            self.logger.addHandler(csv_handler)
            self.logger.setLevel(logging.INFO)

        # Configure the number of workers based on CPU cores
        self.max_workers = max(1, 2)
        self.logger.info(f"Initialized pipeline with {self.max_workers} workers")

    def create_database_schema(self):
        """Create database schema with optimized settings."""
        self.logger.info("Creating database schema")
        with sqlite3.connect(self.db_path) as conn:
            # Enable WAL mode for better concurrent access
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=100000')
            conn.execute('PRAGMA temp_store=MEMORY')

            conn.execute("""
                CREATE TABLE IF NOT EXISTS stackoverflow_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL,
                    title TEXT,
                    question_body TEXT,
                    question_score INTEGER,
                    question_date TEXT,
                    tags TEXT,
                    answers TEXT,  -- Store answers as JSON array
                    answer_ids TEXT,  -- Store answer IDs as JSON array
                    question_body_cleaned TEXT,
                    question_body_code_blocks TEXT,
                    question_body_url_count INTEGER,
                    question_body_length INTEGER,
                    preprocessing_metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        self.logger.info("Database schema created successfully")

    def create_indices(self, conn):
        """Create indices separately for better insertion performance."""
        self.logger.info("Creating database indices")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_question_id ON stackoverflow_posts(question_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_question_date ON stackoverflow_posts(question_date)")
        self.logger.info("Database indices created successfully")

    def transform_and_clean_chunk(self, chunk: pd.DataFrame) -> pd.DataFrame:
        """Transform and clean a chunk of data in one pass."""
        try:
            chunk_size = len(chunk)
            self.logger.debug(f"Processing chunk of size {chunk_size}")

            # First transform the data to group by questions
            transformed_df = self.preprocessor.transform_stackoverflow_data(chunk)

            # Clean the transformed data
            processed_df = transformed_df.copy()

            # Process in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor() as executor:
                # Clean question body HTML
                cleaned_results = list(executor.map(
                    self.preprocessor.clean_html,
                    processed_df['question_body']
                ))

                processed_df['question_body_cleaned'] = [result[0] for result in cleaned_results]
                processed_df['question_body_code_blocks'] = [result[1] for result in cleaned_results]

            # Calculate metrics and process remaining fields
            processed_df['question_body_url_count'] = processed_df['question_body'].apply(
                lambda x: len(self.preprocessor.url_pattern.findall(x))
            )
            processed_df['question_body_length'] = processed_df['question_body_cleaned'].str.len()

            # Convert dates
            processed_df['question_date'] = pd.to_datetime(
                processed_df['question_date'],
                errors='coerce'
            )

            # Store answers and answer_ids as JSON strings
            processed_df['answers'] = processed_df['answers'].apply(json.dumps)
            processed_df['answer_ids'] = processed_df['answer_ids'].apply(json.dumps)

            # Create preprocessing metadata
            processed_df['preprocessing_metadata'] = processed_df.apply(
                lambda row: json.dumps({
                    'question_urls': row['question_body_url_count'],
                    'question_length': row['question_body_length'],
                    'has_code': bool(row['question_body_code_blocks']),
                    'num_answers': len(json.loads(row['answers'])),
                }), axis=1
            )

            self.logger.debug(f"Successfully processed chunk of {chunk_size} rows")
            return processed_df

        except Exception as e:
            self.logger.error(f"Error processing chunk: {str(e)}")
            raise

    def bulk_insert_chunk(self, conn: sqlite3.Connection, chunk: pd.DataFrame):
        """Efficiently insert a processed chunk into the database."""
        try:
            chunk_size = len(chunk)
            self.logger.debug(f"Inserting chunk of {chunk_size} rows into database")

            # Prepare data for insertion
            data = [
                (
                    int(row['question_id']),
                    str(row['title']),
                    str(row['question_body']),
                    int(row['question_score']),
                    str(row['question_date']),
                    str(row['tags']),
                    str(row['answers']),
                    str(row['answer_ids']),
                    str(row['question_body_cleaned']),
                    json.dumps(row['question_body_code_blocks']),
                    int(row['question_body_url_count']),
                    int(row['question_body_length']),
                    str(row['preprocessing_metadata'])
                )
                for _, row in chunk.iterrows()
            ]

            # Bulk insert using executemany
            conn.executemany("""
                INSERT INTO stackoverflow_posts (
                    question_id, title, question_body, question_score,
                    question_date, tags, answers, answer_ids,
                    question_body_cleaned, question_body_code_blocks,
                    question_body_url_count, question_body_length,
                    preprocessing_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)

            self.logger.debug(f"Successfully inserted {chunk_size} rows into database")

        except Exception as e:
            self.logger.error(f"Error inserting chunk: {str(e)}")
            raise

    def ingest_data(self, csv_path: str):
        """Optimized data ingestion method using parallel processing."""
        try:
            self.logger.info(f"Starting data ingestion from {csv_path}")

            # Create database schema
            self.create_database_schema()

            # Create connection pool
            self.logger.info(f"Creating database connection pool with {self.max_workers} connections")
            db_pool = []
            for _ in range(self.max_workers):
                conn = sqlite3.connect(self.db_path)
                conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA synchronous=NORMAL')
                db_pool.append(conn)

            # Get total number of chunks for progress bar
            total_chunks = sum(1 for _ in pd.read_csv(csv_path, chunksize=self.chunk_size))
            self.logger.info(f"Found {total_chunks} total chunks to process")

            # Process chunks in parallel
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                chunks = pd.read_csv(csv_path, chunksize=self.chunk_size)

                # Submit all chunks for processing
                future_to_chunk = {
                    executor.submit(self.transform_and_clean_chunk, chunk): i
                    for i, chunk in enumerate(chunks)
                }

                # Process results as they complete
                with tqdm(total=total_chunks, desc="Processing chunks") as pbar:
                    for future in concurrent.futures.as_completed(future_to_chunk):
                        chunk_idx = future_to_chunk[future]
                        try:
                            processed_chunk = future.result()
                            # Get a connection from the pool
                            conn = db_pool[chunk_idx % len(db_pool)]
                            # Insert the processed chunk
                            self.bulk_insert_chunk(conn, processed_chunk)
                            conn.commit()
                            pbar.update(1)
                        except Exception as e:
                            self.logger.error(f"Error processing chunk {chunk_idx}: {str(e)}")

            # Close all connections
            self.logger.info("Closing database connections")
            for conn in db_pool:
                conn.close()

            # Create indices after all data is loaded
            self.logger.info("Creating final database indices")
            with sqlite3.connect(self.db_path) as conn:
                self.create_indices(conn)

            self.logger.info("Completed data ingestion successfully")

        except Exception as e:
            self.logger.error(f"Fatal error during data ingestion: {str(e)}")
            raise

    def query_data(self, query: str) -> pd.DataFrame:
        """Execute a query and return results as DataFrame."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                return pd.read_sql_query(query, conn)
        except Exception as e:
            self.logger.error(f"Error executing query: {str(e)}")
            raise

    def get_post_statistics(self) -> Dict[str, Any]:
        """Get basic statistical summary of posts."""
        query = """
            SELECT
                COUNT(*) as total_posts,
                AVG(question_score) as avg_score,
                COUNT(DISTINCT question_id) as unique_questions,
                AVG(question_body_length) as avg_question_body_length
            FROM stackoverflow_posts
        """
        return self.query_data(query).iloc[0].to_dict()

    def connect_db(self) -> sqlite3.Connection:
        """Create and return a database connection."""
        return sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    

if __name__ == "__main__":
    import os
    if os.path.exists('stackoverflow.db'):
        os.remove('stackoverflow.db')

    # Initialize with log file
    data_ingestion_pipeline = DataIngestionPipeline(
        db_path='stackoverflow.db',
        chunk_size=10000,
        log_file='data_ingestion_logs.csv'
    )
    dataset_file_path = "python_stackover_flow_dataset.csv"
    data_ingestion_pipeline.ingest_data(dataset_file_path)
    data_ingestion_pipeline.get_post_statistics()