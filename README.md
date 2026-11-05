# Paper Graph Assistant (GraphRAG)
1. `python -m venv venv && source venv/bin/activate` (Windows: `venv\Scripts\activate`)
2. `pip install -r requirements.txt`
3. `cp .env.example .env` and set Neo4j password. Run Neo4j 5.x (`docker run -p7474:7474 -p7687:7687 -e NEO4J_AUTH=neo4j/change_me neo4j:5`)
4. LLM: `ollama pull llama3.1` (or set LLM_PROVIDER=openai + key)
5. `python download_papers.py` (30 arXiv papers) then `python ingest_dataset.py`
6. `python app.py` -> http://localhost:5000
