#!/usr/bin/env python3
"""
Debug específico para ver exatamente qual JSON está sendo retornado pelo LLM
"""

import requests
import json

def debug_raw_response():
    """Debug do JSON retornado pelo LLM"""
    print("=== DEBUG: JSON Response Raw ===")
    
    api_url = "http://localhost:8000/api/agent/interact"
    payload = {"prompt": "Quantos acólitos temos?"}
    
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
            print(f"Response completa: {json.dumps(result, indent=2, ensure_ascii=False)}")
            
            # Extrai o JSON raw da mensagem de erro
            if "Raw: '" in response_text:
                raw_start = response_text.find("Raw: '") + 6
                raw_end = response_text.find("'", raw_start)
                if raw_end != -1:
                    raw_json = response_text[raw_start:raw_end]
                    print(f"\n📄 JSON Raw extraído:")
                    print(f"Tamanho: {len(raw_json)} caracteres")
                    print(f"Conteúdo: '{raw_json}'")
                    
                    # Tenta fazer o parsing manual
                    try:
                        parsed = json.loads(raw_json)
                        print(f"\n✅ JSON válido!")
                        print(json.dumps(parsed, indent=2, ensure_ascii=False))
                    except json.JSONDecodeError as e:
                        print(f"\n❌ JSON inválido: {e}")
                        print(f"Posição do erro: {e.pos}")
                        if e.pos < len(raw_json):
                            print(f"Caractere problemático: '{raw_json[e.pos]}' (#{ord(raw_json[e.pos])})")
                            print(f"Contexto: ...{raw_json[max(0, e.pos-10):e.pos+10]}...")
                        
                        # Mostra os primeiros e últimos 100 caracteres
                        print(f"\nInício: {raw_json[:100]}")
                        print(f"Final: {raw_json[-100:]}")
        else:
            print(f"❌ Erro HTTP {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"❌ Erro: {e}")

if __name__ == "__main__":
    debug_raw_response()