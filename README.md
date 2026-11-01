Step 1
conda create -n shortcraft-ai python=3.13 -y

Step 2
conda activate shortcraft-ai

frontend
python -m streamlit run frontend/app.py

backend
python -m uvicorn backend.main:app --reload --port 8000