#!/usr/bin/env python3
"""
Test script para verificar se o bypass direto ainda funciona
"""

import requests
import json

def test_simple_query():
    url = "http://127.0.0.1:8000/api/agent/interact"
    
    # Query simples que deveria usar bypass direto
    payload = {
        "prompt": "quantos acólitos temos registrados?"
    }
    
    try:
        print("🔄 Testando query simples...")
        print(f"📝 Query: {payload['prompt']}")
        
        response = requests.post(url, json=payload, timeout=30)
        
        print(f"✅ Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📋 Resposta: {data['response_text']}")
            print(f"🔧 Ações executadas: {len(data['executed_actions'])}")
            
            if len(data['executed_actions']) == 0:
                print("✅ BYPASS DIRETO FUNCIONANDO!")
            else:
                print("❌ Não usou bypass direto")
                
        else:
            print(f"❌ Erro HTTP: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == "__main__":
    test_simple_query()