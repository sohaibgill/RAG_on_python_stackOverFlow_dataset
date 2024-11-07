# Project Overview

---

This project focuses on developing a Retrieval-Augmented Generation (RAG) based AI chatbot built on top of the Python Stack Overflow Question Answering Dataset. The chatbot is designed to answer any query related to the Python programming language. It matches user input queries with questions available in the dataset, retrieves relevant questions and metadata, and then passes the retrieved answers as context to a language model (LLM) to generate accurate responses.

### Core Functionality

The bot's main functionality involves generating embeddings of cleaned questions, which are stored in a vector database. When a user asks a question related to Python, the bot generates an embedding of the input query, matches it with questions stored in the database, and retrieves the answers to the top three matched questions. These answers are then passed to the LLM as context to generate an accurate response.

### Pipelines

The project consists of three main pipelines:

1. **Data Processing Pipeline:**
   - **Cleaning and Transformation:** This pipeline is responsible for cleaning and transforming the data into the required format. It removes HTML tags to improve readability and context, handles null values, standardizes date formats, and performs text cleaning.
   - **Storage:** The cleaned data is stored in an SQLite database for persistent storage. SQLite database is selected for simplicty according to the scope of this project. For questions with multiple answers, each answer is stored in a separate row, grouped by the question, to reduce redundancy and dataset size.
   - **Optimization:** Parallel processing is used to clean and store data quickly, making the solution scalable for larger datasets. SQLite is used in WAL mode to handle data efficiently and in parallel. Indexes are created for efficient querying from the database.

2. **Vector Database Pipeline:**
   - **Embedding Generation:** This pipeline generates embeddings using an open-source small 450M parameter model and proprietary VoyageAI models. While the open-source model is good for testing, the VoyageAI model provides better results for production use.
   - **Storage:** ChromaDB is used as the vector database. Batch processing is employed for efficient and fast embedding generation and upserting vectors into the database.

3. **Inference Pipeline:**
   - **Query Processing:** This pipeline receives user queries, generates embeddings using the same model used for dataset embedding generation, and queries the vector database for the top relevant questions.
   - **Answer Retrieval:** It retrieves the question IDs from the metadata of the matched vectors and fetches the corresponding answers from the database. These answers are then passed as context to the LLM to generate the final response.

By utilizing these pipelines, the chatbot can provide accurate and relevant answers to Python programming queries, enhancing the user's experience and ensuring reliable information retrieval.
