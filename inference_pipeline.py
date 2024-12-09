import json
import logging
from datetime import datetime
from logging_classes import CSVFileHandler
from vector_database_ingestion_pipeline import VectorIngestion
from data_ingestion_pipeline import DataIngestionPipeline

class InferenceClass(VectorIngestion):
    def __init__(self, ingestion_pipeline, open_source_mode, log_file: str = 'logs/inference_logs.csv'):
        """Initialize the inference pipeline with logging."""
        super().__init__(open_source_mode)

        # Setup logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)  # Set level before adding handlers

        # Remove any existing handlers to avoid duplicates
        if self.logger.handlers:
            for handler in self.logger.handlers:
                self.logger.removeHandler(handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)

        # CSV file handler
        csv_handler = CSVFileHandler(log_file)
        csv_handler.setLevel(logging.INFO)

        # Add both handlers
        self.logger.addHandler(console_handler)
        self.logger.addHandler(csv_handler)

        self.ingestion_pipeline = ingestion_pipeline
        self.model_name = "mistralai/Mixtral-8x7B-Instruct-v0.1"  #"mistralai/Mistral-Nemo-Instruct-2407", 
        self.logger.info(f"Initialized inference pipeline with model: {self.model_name}")


        self.sql_query = f"""
        SELECT answers
        FROM stackoverflow_posts
        WHERE question_id IN (_question_ids_);
        """

        self.prompt = """You are a helpful assistant. Your task is to answer the user's query related to Python based on the provided context. The context consists of answers from developers to questions asked on Stack Overflow.

Instructions:
Cohesive and Clear Response: Ensure your answer is well-organized, easy to understand, and directly addresses the user's query.
Include Code Examples: If a relevant code example is available in the provided context, include it in your response.
Contextual Limitation: If the answer to the query is not present in the provided context or context is empty, must respond with: "Sorry, the provided context does not contain an answer to the query."

If the answer to the query is not present in the provided context, do not add anything from your knowledge.
Your answer should be less than 500 words.

Query:
__query__

Context:
__context__
"""

    def retriever(self, query, verbose):
        """Retrieve relevant context from vector store."""
        try:
            self.logger.info(f"Starting retrieval for query: {query[:100]}...")  # Log first 100 chars of query

            question_ids = []
            titles = []
            tags = []
            question_bodies = []
            s_scores = []
            answer_ids = []
            relevant_context = []

            self.logger.info("Querying chromaDB vector stores...")
            results = self.vector_store.similarity_search(query, k=3)

            for res in results:
                metadata = res.metadata
                question_ids.append(metadata['question_id'])
                titles.append(metadata['title'])
                question_bodies.append(metadata['question_body'])
                tags.append(metadata['tags'])

            self.logger.debug(f"Retrieved {len(question_ids)} documents from vector store")

            sql_query = self.sql_query.replace("_question_ids_", str(','.join([f'{i}' for i in question_ids])))
            self.logger.debug("Executing SQL query to fetch answers")

            answers = self.ingestion_pipeline.query_data(sql_query)['answers'].to_list()
            relevant_context = "\n\n".join([ans['answer_body'] for answer in answers for ans in json.loads(answer)[:2]])

            total_inputs_vectors = len(question_ids)
            self.logger.info(f"Retrieved {total_inputs_vectors} relevant documents")

            if verbose:
                self.logger.info(f"Question IDs: {question_ids}")
                self.logger.debug(f"Titles: {titles}")
                self.logger.debug(f"Context length: {len(relevant_context)} characters")
                self.logger.debug(f"Context: {relevant_context}")
                print(f"\n\nContext: {relevant_context}\n\n")

            return question_ids, titles, tags, question_bodies, s_scores, answer_ids, relevant_context

        except Exception as e:
            self.logger.error(f"Error in retriever: {str(e)}")
            raise

    def llm_call(self, query, verbose, stream):
        """Make LLM API call with retrieved context."""
        try:
            self.logger.info("Starting LLM call process")

            # Get retrieved context
            retrieval_start = datetime.now()
            question_ids, titles, tags, question_bodies, s_scores, answer_ids, relevant_answers = self.retriever(query, verbose)
            retrieval_time = (datetime.now() - retrieval_start).total_seconds()
            self.logger.info(f"Context retrieval completed in {retrieval_time:.2f} seconds")

            # Prepare prompt
            prompt = self.prompt.replace("__query__", query).replace("__context__", str(relevant_answers))
            messages = [
                {"role": "user", "content": prompt}
            ]

            # Make LLM call
            self.logger.info(f"Making LLM API call to {self.model_name}")
            llm_start = datetime.now()
            response = self.hf_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=600,
                stream=stream
            )

            print("\n\n")
            print("-"*180)
            print(f"\n\n\nQuestion: {query}\n\nAnswer: ")

            # Handle streaming vs non-streaming response
            if stream:
                response_text = ""
                for chunk in response:
                    chunk_text = chunk.choices[0].delta.content
                    response_text += chunk_text
                    print(chunk_text, end="")
            else:
                response_text = response.choices[0].message.content
                print(response_text)

            llm_time = (datetime.now() - llm_start).total_seconds()
            self.logger.info(f"LLM response completed in {llm_time:.2f} seconds")

            # Log response metadata
            self.logger.debug({
                "query_length": len(query),
                "context_length": len(relevant_answers),
                "response_length": len(response_text),
                "retrieval_time": retrieval_time,
                "llm_time": llm_time
            })

            print("\n")
            print("-"*180)

        except Exception as e:
            self.logger.error(f"Error in LLM call: {str(e)}")
            raise


if __name__ == "__main__":
    #Initialize the inference class
    data_ingestion_pipeline = DataIngestionPipeline()
    inference_instance = InferenceClass(
    ingestion_pipeline=data_ingestion_pipeline,
    open_source_mode=True,
    log_file='inference_logs.csv'
)
    # query = "What is python's list comprehension?"
    # query = "how to sort python dictionary on the basis of values?"
    # query = "what are the generators in python?"
    # query = "what are the OOP concepts in python?"
    # query = "what is the difference between lists and tuples?"
    query = "what GIL lock in python?"
    # query = "How to reverse a list in Python?"
    # query = "what the whether like in new york"

    # verbose = True
    # stream = True
    # inference_instance.llm_call(query,verbose,stream)


    verbose = True
    stream = True

    # response_df = inference.retriever(query,verbose)
    while True:
        query = input("Please enter your python related query....\n")
        inference_instance.llm_call(query,verbose,stream)