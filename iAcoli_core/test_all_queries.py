#!/usr/bin/env python3
"""
Test script para verificar se o bypass direto funciona para diferentes queries
"""

import requests
import json

def test_queries():
    url = "http://127.0.0.1:8000/api/agent/interact"
    
    queries = [
        "quantos acólitos temos registrados?",
        "liste todos acólitos",
        "quais são os nomes dos acólitos?",
        "todos os acólitos"
    ]
    
    for query in queries:
        print(f"\n🔄 Testando: {query}")
        payload = {"prompt": query}
        
        try:
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Resposta: {data['response_text'][:100]}...")
                print(f"🔧 Ações: {len(data['executed_actions'])}")
                
                if len(data['executed_actions']) == 0:
                    print("✅ BYPASS DIRETO!")
                else:
                    print("❌ Usou LLM")
            else:
                print(f"❌ Erro {response.status_code}")
                
        except Exception as e:
            print(f"❌ Erro: {e}")

if __name__ == "__main__":
    test_queries()