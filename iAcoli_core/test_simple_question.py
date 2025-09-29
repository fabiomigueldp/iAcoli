#!/usr/bin/env python3
"""
Teste com pergunta mais específica sobre os dados para forçar uso do contexto
"""

import requests
import json

def test_specific_question():
    """Testa pergunta muito específica que deve usar o contexto"""
    print("=== TESTE: Pergunta Específica ===")
    
    api_url = "http://localhost:8000/api/agent/interact"
    
    # Pergunta que deveria trigger o contexto enhanced
    payload = {"prompt": "Quantas pessoas estão registradas no sistema?"}
    
    try:
        response = requests.post(
            api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get("response_text", "")
            
            print(f"Status: {response.status_code}")
            print(f"Response: {response_text[:500]}...")
            
            # Verifica se há indícios de contexto sendo usado
            if "5" in response_text or "cinco" in response_text.lower():
                print("\n✅ POSSÍVEL SUCESSO: Resposta contém número correto (5)")
            elif "erro" in response_text.lower() and "json" in response_text.lower():
                print("\n⚠️  PROBLEMA: Ainda há erro de JSON parsing")
            else:
                print("\n❓ Resposta inesperada")
                
        else:
            print(f"❌ Erro HTTP {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == "__main__":
    test_specific_question()