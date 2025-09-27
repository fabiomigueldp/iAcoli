# iAcoli Core

Sistema de gerenciamento de escalas e eventos para comunidades.

## Instalação

```bash
pip install -e .
```

## Uso

### API Web

Para executar a API web:

```bash
# Usando uvicorn diretamente
python -m uvicorn iacoli_core.webapp.app:app --host 0.0.0.0 --port 8000 --reload

# Ou usando o script incluído
python -m iacoli_core.webapp.serve

# Ou usando o console script (se disponível no PATH)
escala-web
```

A API estará disponível em:
- **Interface principal**: http://localhost:8000
- **Documentação (Swagger)**: http://localhost:8000/docs
- **Documentação (ReDoc)**: http://localhost:8000/redoc
- **Endpoint de saúde**: http://localhost:8000/health

### CLI (Interface de Linha de Comando)

Para usar a interface de linha de comando:

```bash
# Usando Python
python -c "from iacoli_core.cli import main; main()" --help

# Ou usando o console script (se disponível no PATH)
escala-cli --help
```

#### Comandos principais:

- `acolito` - Administração de acólitos
- `evento` - Gerenciamento de eventos  
- `escala` - Relatórios e operações de escala
- `atribuicao` - Comandos de atribuição
- `config` - Configuração do sistema
- `arquivo` - Persistência e exportação

## Estrutura do Projeto

```
iacoli_core/
├── __init__.py
├── cli.py              # Interface de linha de comando
├── config.py           # Configurações
├── core.py            # Lógica principal
├── errors.py          # Exceções personalizadas
├── localization.py    # Localização e traduções
├── models.py          # Modelos de dados
├── output.py          # Formatação de saída
├── repository.py      # Persistência de dados
├── scheduler.py       # Algoritmos de agendamento
├── service.py         # Serviços de negócio
├── utils.py          # Utilitários
└── webapp/           # Interface web
    ├── __init__.py
    ├── app.py        # Aplicação FastAPI
    ├── serve.py      # Script de execução
    ├── container.py  # Container de dependências
    ├── dependencies.py
    └── schemas.py    # Esquemas Pydantic
    └── api/          # Endpoints da API
        ├── __init__.py
        ├── config.py
        ├── events.py
        ├── people.py
        ├── schedule.py
        ├── series.py
        └── system.py
```

## Dependências

- **FastAPI** (≥0.111) - Framework web moderno e rápido
- **Pydantic** (≥2.6) - Validação de dados e serialização
- **Uvicorn** (≥0.30) - Servidor ASGI
- **PyYAML** (≥6.0) - Processamento de arquivos YAML
- **python-dateutil** (≥2.8.0) - Manipulação avançada de datas
- **pytz** (≥2023.3) - Fusos horários

## Recursos Implementados

✅ **App FastAPI** - Aplicação web principal com middlewares  
✅ **Routers API** - Endpoints organizados por funcionalidade  
✅ **Container de Serviços** - Gerenciamento de dependências thread-safe  
✅ **Middlewares** - CORS e compressão GZip  
✅ **Schemas Pydantic v2** - Validação e serialização de dados  
✅ **Scripts de execução** - Comandos prontos para uso  
✅ **Manifesto de dependências** - pyproject.toml completo  

## Configuração

O sistema usa um arquivo `config.toml` para configurações. Exemplo:

```toml
[general]
timezone = "America/Sao_Paulo"
default_view_days = 30
name_width = 20
overlap_minutes = 30
default_locale = "pt-BR"

[fairness]
fair_window_days = 90
role_rot_window_days = 30
workload_tolerance = 2

[weights]
load_balance = 1.0
recency = 0.5
role_rotation = 0.3
morning_pref = 0.2
solene_bonus = 0.1
```

## Estado do Sistema

O estado é persistido em `state.json` e inclui:
- Lista de pessoas/acólitos
- Eventos programados
- Atribuições de escalas
- Bloqueios de disponibilidade
- Histórico para desfazer operações

## Licença

MIT License