import os
from dotenv import load_dotenv
from pinecone import Pinecone
from openai import OpenAI
import anthropic

load_dotenv()

pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
index = pc.Index(os.getenv("PINECONE_INDEX_NAME"))

def get_embedding(text):
    response = openai_client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def retrieve(query, top_k=5):
    embedding = get_embedding(query)
    results = index.query(vector=embedding, top_k=top_k, include_metadata=True)
    return results.matches

def ask(query):
    matches = retrieve(query)
    context = "\n\n---\n\n".join([m.metadata["text"] for m in matches])
    categories = list(set([m.metadata["category"] for m in matches]))

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system="""You are a Studio Lou Interiors knowledge assistant. 
Answer questions using ONLY the retrieved context provided. 
Be specific and actionable. If the context doesn't cover the question fully, say so.
Never invent facts not present in the context.""",
        messages=[{
            "role": "user",
            "content": f"Retrieved context:\n\n{context}\n\n---\n\nQuestion: {query}"
        }]
    )

    print(f"\nSources: {', '.join(categories)}")
    print(f"\n{response.content[0].text}\n")

if __name__ == "__main__":
    print("Studio Lou RAG — ready to query.")
    print("Type your question and hit Enter. Type 'quit' to exit.\n")
    while True:
        query = input("Question: ").strip()
        if query.lower() in ["quit", "exit", "q"]:
            break
        if query:
            ask(query)