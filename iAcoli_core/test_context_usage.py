#!/usr/bin/env python3
"""
Teste específico para verificar se o agente usa corretamente o contexto fornecido
"""

import requests
import json

def test_context_usage():
    """Testa se o agente usa o contexto dinâmico corretamente"""
    print("=== TESTE: Uso do Contexto Dinâmico ===")
    
    api_url = "http://localhost:8000/api/agent/interact"
    
    test_queries = [
        "Quantos acólitos temos registrados?",
        "Quais são os nomes dos acólitos?", 
        "Quantos eventos temos agendados?",
        "Qual é o próximo evento?"
    ]
    
    for query in test_queries:
        print(f"\n📋 Query: '{query}'")
        
        payload = {"prompt": query}
        
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
                executed_actions = result.get("executed_actions", [])
                
                print(f"✅ Status: 200 OK")
                print(f"📄 Resposta: {response_text[:200]}{'...' if len(response_text) > 200 else ''}")
                print(f"🔧 Ações executadas: {len(executed_actions)}")
                
                # Verifica se o agente usou o contexto
                if "não tenho acesso" in response_text.lower():
                    print("❌ PROBLEMA: Agente diz que não tem acesso aos dados")
                elif "erro" in response_text.lower():
                    print("⚠️  PROBLEMA: Há erros na resposta")
                elif any(nome in response_text for nome in ["Emanuelly", "Fábio", "Maria Clara", "Maria Fernanda", "Pedro"]):
                    print("✅ SUCESSO: Agente usou dados específicos do contexto")
                elif any(num in response_text for num in ["5", "3", "cinco", "três"]):
                    print("✅ SUCESSO: Agente usou números corretos do contexto")
                else:
                    print("⚠️  INCERTO: Resposta não confirma uso do contexto")
                    
            else:
                print(f"❌ Erro HTTP {response.status_code}")
                print(f"   Resposta: {response.text[:200]}")
                
        except Exception as e:
            print(f"❌ Erro: {e}")
    
    return True

if __name__ == "__main__":
    print("TESTE: Verificação do Uso do Contexto pelo Agente")
    print("=" * 60)
    
    success = test_context_usage()
    
    print(f"\n{'='*60}")
    if success:
        print("✅ Teste executado com sucesso")
        print("Verifique as respostas acima para confirmar se o agente")
        print("está usando corretamente o contexto dinâmico fornecido.")
    else:
        print("❌ Falhas durante o teste")