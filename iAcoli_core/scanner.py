#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scanner.py — Snapshot de projeto otimizado para IA (clipboard-first)

Requisitos do usuário atendidos:
- Mantém o nome scanner.py.
- Inteligente para NÃO se auto-escancear (não inclui o próprio arquivo em nenhuma hipótese).
- Não cria arquivos por padrão: sempre envia TUDO para o clipboard.
- Só cria um arquivo (project_snapshot.txt) SE e SOMENTE SE for impossível garantir que
  **todo** o conteúdo foi copiado (ou se o clipboard não estiver disponível).

Extras úteis (opcionais via flags):
- --respect-gitignore (usa pathspec se instalado) para ignorar padrões do .gitignore
- --redact-secrets (redige possíveis segredos/tokens/.env)
- --binary-policy [skip|metadata] (padrão: metadata)
- --max-file-size BYTES (trunca leitura de arquivos muito grandes)
- Suporte a .ipynb (extrai células de código/markdown)
- Árvore bonitinha (├──, └──, │) + cabeçalho com métricas

Dependências opcionais:
- pyperclip (clipboard). Se ausente/sem suporte, cai no fallback de arquivo.
- pathspec (respeitar .gitignore)
- chardet (detectar encoding de texto)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# ---------------- Imports opcionais ----------------
try:
    import pyperclip  # type: ignore
except Exception:  # pragma: no cover
    pyperclip = None  # type: ignore

try:
    from pathspec import PathSpec  # type: ignore
except Exception:  # pragma: no cover
    PathSpec = None  # type: ignore

try:
    import chardet  # type: ignore
except Exception:  # pragma: no cover
    chardet = None  # type: ignore

# ---------------- Configurações padrão ----------------
TARGET_EXTENSIONS = (
    ".py", ".pyw", ".ipynb", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs",
    ".js", ".ts", ".jsx", ".tsx", ".vue",
    ".html", ".htm", ".css", ".scss", ".sass", ".less",
    ".php", ".rb", ".swift", ".kt", ".kts",
    ".json", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".md", ".txt", ".rtf",
    ".sql", ".sh", ".bat", ".ps1",
    ".env", ".env.example",
)

EXACT_FILENAMES = (
    "Dockerfile", "docker-compose.yml", "Makefile", "Jenkinsfile", "requirements.txt",
    ".gitignore", ".dockerignore", ".editorconfig", "package.json", "README", "LICENSE",
    "pyproject.toml", "setup.py", "Pipfile", "Pipfile.lock", "poetry.lock",
    "go.mod", "go.sum", "composer.json", "Gemfile", "Gemfile.lock",
    "tsconfig.json", "webpack.config.js", "babel.config.js"
)

EXCLUDE_DIRS = {
    "__pycache__", "node_modules", ".git", ".vscode", ".idea", "venv", ".venv", ".env",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".cache", "coverage", "target", "out",
    "bin", "obj", ".gradle"
}

# Binários tratados como metadados/skip
BINARY_EXTS = {".docx", ".doc", ".pdf", ".xlsx", ".xls", ".pptx", ".ppt",
               ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".tar", ".gz"}

# Arquivos que nunca devem ser incluídos (fallbacks, etc.)
NEVER_INCLUDE = {"project_snapshot.txt", "snapshot.txt"}

# Linguagem para fences
LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".java": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".go": "go", ".rs": "rust", ".sh": "bash", ".ps1": "powershell", ".sql": "sql",
    ".rb": "ruby", ".php": "php", ".kt": "kotlin", ".kts": "kotlin", ".swift": "swift",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".md": "md", ".html": "html", ".htm": "html", ".css": "css",
}

# Regex de segredos (heurístico – prefira usar com --redact-secrets)
SECRET_REGEXES = [
    re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PGP) PRIVATE KEY-----[\s\S]*?-----END .*? PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\./+]{12,})"),
    re.compile(r"(?m)^[A-Z0-9_]{3,}=(.*)$"),
]
REDACTION = "<REDACTED>"

# ---------------- Utilitários ----------------

def human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.1f} {u}" if u != "B" else f"{int(size)} {u}"
        size /= 1024
    return f"{n} B"


def detect_encoding(data: bytes) -> str:
    if chardet is None:
        return "utf-8"
    info = chardet.detect(data)
    enc = info.get("encoding") or "utf-8"
    return enc


def guess_lang(path: Path) -> str:
    return LANG_BY_EXT.get(path.suffix.lower(), "")


def redact(text: str) -> str:
    out = text
    for rx in SECRET_REGEXES:
        out = rx.sub(REDACTION, out)
    return out


def normalize_for_compare(s: str) -> str:
    """Normaliza para comparar clipboard vs original (quebra-de-linha e fim)."""
    return s.replace("\r\n", "\n").replace("\r", "\n")

# ---------------- Núcleo ----------------

def build_tree_and_filelist(root: Path, respect_gitignore: bool, follow_symlinks: bool,
                            include_exts: Iterable[str], include_names: Iterable[str],
                            exclude_dirs: Iterable[str], script_path: Path) -> tuple[list[Path], list[str], int, int, int]:
    files: list[Path] = []
    lines: list[str] = []

    # .gitignore matcher (opcional)
    spec = None
    if respect_gitignore and PathSpec is not None:
        gi = root / ".gitignore"
        if gi.exists():
            with gi.open("r", encoding="utf-8", errors="replace") as f:
                patterns = f.read().splitlines()
            spec = PathSpec.from_lines("gitwildmatch", patterns)

    def ignored_by_git(rel: Path) -> bool:
        if not spec:
            return False
        return spec.match_file(rel.as_posix())

    include_exts = set(e.lower() for e in include_exts)
    include_names = set(include_names)
    exclude_dirs = set(exclude_dirs)

    lines.append("DIRECTORY STRUCTURE\n-------------------\n")

    n_dirs = 0
    n_files = 0
    total_size = 0

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=follow_symlinks):
        # limpa dirs
        dirnames[:] = sorted([d for d in dirnames if d not in exclude_dirs], key=str.lower)
        # aplica .gitignore
        dirnames[:] = [d for d in dirnames if not ignored_by_git((Path(dirpath)/d).relative_to(root))]

        rel = Path(dirpath).relative_to(root)
        depth = 0 if rel == Path('.') else len(rel.parts)
        if depth == 0:
            lines.append(f"{root.name}/\n")
        else:
            lines.append(f"{('│   ' * (depth - 1))}├── {rel.name}/\n")
        n_dirs += 1

        filenames = sorted(filenames, key=str.lower)
        for i, fn in enumerate(filenames):
            p = Path(dirpath, fn)
            # nunca inclua o próprio script, nem arquivos reservados
            try:
                if p.resolve() == script_path.resolve():
                    continue
            except Exception:
                pass
            if fn in NEVER_INCLUDE:
                continue

            relp = p.relative_to(root)
            if spec and ignored_by_git(relp):
                continue

            # critérios de inclusão
            if fn in include_names or p.suffix.lower() in include_exts:
                files.append(p)
                branch = "└── " if i == len(filenames) - 1 else "├── "
                lines.append(f"{'│   ' * (depth + 1)}{branch}{fn}\n")
                n_files += 1
                try:
                    total_size += p.stat().st_size
                except Exception:
                    pass

    return files, lines, n_dirs, n_files, total_size


def read_text_file(p: Path, max_file_size: int, binary_policy: str) -> tuple[str, bool]:
    """Retorna (conteúdo, truncado)."""
    try:
        size = p.stat().st_size
    except OSError as e:
        return f"!!! Could not stat file: {e} !!!", False

    if p.suffix.lower() in BINARY_EXTS:
        if binary_policy == "skip":
            return "[BINARY SKIPPED]", False
        return f"[BINARY FILE {p.suffix.upper()}] Size: {human_bytes(size)}", False

    if size > max_file_size:
        return f"[TRUNCATED: {human_bytes(size)} > limit {human_bytes(max_file_size)}]", True

    # .ipynb: extrair células
    if p.suffix.lower() == ".ipynb":
        try:
            raw = p.read_bytes()
            j = json.loads(raw.decode("utf-8", errors="replace"))
            cells = j.get("cells", [])
            parts: list[str] = []
            for c in cells:
                cell_type = c.get("cell_type")
                src = "".join(c.get("source", []))
                if cell_type == "code":
                    parts.append("```python\n" + src + "\n```")
                elif cell_type == "markdown":
                    parts.append(src)
            return "\n\n".join(parts), False
        except Exception as e:
            return f"!!! Could not parse ipynb: {e} !!!", False

    try:
        raw = p.read_bytes()
        enc = detect_encoding(raw)
        text = raw.decode(enc, errors="replace")
        return text, False
    except Exception as e:
        try:
            return p.read_text(encoding="utf-8", errors="replace"), False
        except Exception as e2:
            return f"!!! Could not read file: {e} / {e2} !!!", False


def render_markdown_header(root: Path, n_dirs: int, n_files: int, total_bytes: int) -> str:
    title = "PROJECT SCAN SNAPSHOT"
    return (
        f"# {title}\n\n"
        f"**Root:** `{root}`  \\\n**Dirs:** {n_dirs}  \\\n**Files:** {n_files}  \\\n**Total size (selected):** {human_bytes(total_bytes)}  \\\n**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )


def render_file_block_md(relpath: Path, content: str) -> str:
    lang = LANG_BY_EXT.get(relpath.suffix.lower(), "")
    fence = f"```{lang}" if lang else "```"
    return f"\n---\n\n**{relpath.as_posix()}**\n\n{fence}\n{content}\n```\n"

# ---------------- Execução principal ----------------

def generate_snapshot(options) -> str:
    root = options.root.resolve()
    script_path = Path(__file__).resolve()

    files, tree_lines, n_dirs, n_files, total_bytes = build_tree_and_filelist(
        root,
        options.respect_gitignore,
        options.follow_symlinks,
        options.include_exts,
        options.include_names,
        options.exclude_dirs,
        script_path,
    )

    out_parts: list[str] = []
    out_parts.append(render_markdown_header(root, n_dirs, n_files, total_bytes))
    out_parts.append("".join(tree_lines))
    out_parts.append("\n---\n\n## FILE CONTENTS\n\n")

    for p in sorted(files, key=lambda x: x.as_posix().lower()):
        rel = p.relative_to(root)
        text, _trunc = read_text_file(p, options.max_file_size, options.binary_policy)
        if options.redact_secrets:
            text = redact(text)
        out_parts.append(render_file_block_md(rel, text))

    out_parts.append("\n--- END OF SNAPSHOT ---\n")
    return "".join(out_parts)


def copy_strict_to_clipboard(content: str) -> bool:
    """
    Copia e verifica se **todo** o conteúdo foi realmente para o clipboard.
    Retorna True se bateu 100% (com normalização de quebras de linha), False caso contrário.
    """
    if pyperclip is None:
        return False
    try:
        pyperclip.copy(content)
        pasted = pyperclip.paste()
        if pasted is None:
            return False
        return normalize_for_compare(pasted) == normalize_for_compare(content)
    except Exception:
        return False

# ---------------- CLI ----------------

def parse_args(argv: Optional[List[str]] = None):
    ap = argparse.ArgumentParser(description="Gera snapshot do projeto e envia ao clipboard (fallback em arquivo se necessário)")
    ap.add_argument("root", nargs="?", default=".", help="Diretório raiz a escanear (padrão: .)")
    ap.add_argument("--include-ext", nargs="*", default=list(TARGET_EXTENSIONS), help="Extensões a incluir (.py .js ...)")
    ap.add_argument("--include-name", nargs="*", default=list(EXACT_FILENAMES), help="Nomes exatos a incluir")
    ap.add_argument("--exclude-dir", nargs="*", default=list(EXCLUDE_DIRS), help="Diretórios a excluir")
    ap.add_argument("--respect-gitignore", action="store_true", help="Respeita padrões do .gitignore (se pathspec instalado)")
    ap.add_argument("--follow-symlinks", action="store_true", help="Seguir symlinks")
    ap.add_argument("--binary-policy", choices=["skip", "metadata"], default="metadata", help="Tratamento de binários")
    ap.add_argument("--max-file-size", type=int, default=500_000, help="Tamanho máximo por arquivo (bytes)")
    ap.add_argument("--redact-secrets", action="store_true", help="Redigir segredos (.env/tokens)")
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    class Opts:  # struct simples
        root = Path(args.root)
        include_exts = args.include_ext
        include_names = args.include_name
        exclude_dirs = args.exclude_dir
        respect_gitignore = bool(args.respect_gitignore)
        follow_symlinks = bool(args.follow_symlinks)
        binary_policy = args.binary_policy
        max_file_size = int(args.max_file_size)
        redact_secrets = bool(args.redact_secrets)

    print("🔎 Gerando snapshot…")
    snapshot = generate_snapshot(Opts)

    print("📋 Copiando para o clipboard (verificação estrita)…")
    ok = copy_strict_to_clipboard(snapshot)
    if ok:
        print("✅ Snapshot copiado com sucesso (100% verificado). Cole onde quiser.")
        return 0

    # Fallback: criar arquivo SOMENTE se o clipboard falhar em 100%
    print("❌ Não foi possível garantir 100% no clipboard. Salvando fallback em arquivo…")
    out_file = Path.cwd() / "project_snapshot.txt"
    try:
        out_file.write_text(snapshot, encoding="utf-8")
        print(f"📄 Fallback salvo em: {out_file}")
        print("ℹ️ Motivo: clipboard indisponível ou conteúdo não bateu byte-a-byte.")
        return 0
    except Exception as e:
        print(f"💥 Falha também ao salvar arquivo de fallback: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
