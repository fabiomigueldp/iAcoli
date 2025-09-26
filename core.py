#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Escala CLI – Núcleo (v3)

Objetivo
--------
Núcleo de escala com algoritmo de seleção que:
1) **Prioriza SEMPRE** candidatos da comunidade do evento.
2) Só escala alguém de outra comunidade quando **não houver local válido**,
   isto é, quando todos os locais causarem **desequilíbrio considerável** na carga,
   ou estiverem indisponíveis (conflito, bloqueio, inativos, sem qualificação).
3) **Promove rotatividade**: balanceia carga total e também a rotação de funções.
4) Opera sempre a partir do **dia real atual** (agora), com períodos padrão de 30 dias.
5) Inclui novos comandos úteis (CLEAR, PRUNE, FREE, RESETASSIGN, A ADD/DEL, NOW).
6) Novo HELP objetivo e enxuto.

Princípios do algoritmo
-----------------------
- Janela de justiça (FAIR_WINDOW_DAYS): conta atribuições recentes por pessoa até a data do evento.
- Limite de carga (WORKLOAD_TOLERANCE): um candidato é **válido** se, ao receber mais uma função,
  sua contagem na janela não ultrapassar (média do grupo + tolerância).
- Preferência local é um **passo de filtro**, não só um bônus:
  1) Considera apenas candidatos da comunidade do evento que sejam válidos e sem impedimentos.
  2) Se não houver, considera candidatos de outras comunidades válidos.
  3) Se ainda não houver, escolhe quem tiver **menor excesso** acima do limite (primeiro locais; se não, globais).
- Rotatividade de função (ROLE_ROT_WINDOW_DAYS): penaliza repetir a mesma função com muita frequência recente.
- Recência (último serviço): favorece quem está há mais tempo sem servir.
- Regras duras: inativo, bloqueado, choque de horário e falta de qualificação (TUR) eliminam o candidato.

Observações
-----------
- O modo *ESCALA* sem período mostra os próximos DEFAULT_VIEW_DAYS dias a partir de hoje.
- L sem período lista do **hoje** até o fim do mês atual.
- CHK/STATS sem período usam os próximos DEFAULT_VIEW_DAYS dias.
"""

import re, sys, json, os
import unicodedata
import calendar
from datetime import datetime, timedelta, date
from collections import defaultdict
from statistics import pstdev, mean

# =================== Configurações e Pesos ===================
DEFAULT_RECURRENCE_MONTHS = 3   # CR curto: meses à frente
NO_OVERLAP_MINUTES = 110        # Janela anti-choque entre missas (~1h50)
NAME_MAX_CHARS = 18             # Largura de nomes na tabela

# Janela e tolerâncias de fairness/rotação
FAIR_WINDOW_DAYS = 90           # Janela de justiça de carga (dias)
ROLE_ROT_WINDOW_DAYS = 45       # Janela para rotatividade de função (dias)
WORKLOAD_TOLERANCE = 2          # Limite: média + tolerância (em número de atribuições)
DEFAULT_VIEW_DAYS = 30          # Período padrão “a partir de hoje” para listagens/checagens

# Pesos (usados no desempate/ranking dentro do agrupamento válido)
W_LOAD_BAL = 80.0       # favorece quem tem menor carga na janela
W_RECENCY  = 1.2        # mais dias sem servir = melhor
W_ROLE_ROT = 6.0        # penalidade por repetir a mesma função recentemente
W_MORNING  = 1.0        # leve bônus por preferência de manhã
W_SOLENE   = 0.8        # pequeno bônus em solenes
# Penalidades duras (eliminatórias / muito altas)
PENAL_CONFLICT   = 10_000.0
PENAL_BLOCKED    = 1_000_000.0
PENAL_INACTIVE   = 2_000_000.0

# =================== Dados fixos e iniciais ===================
COMM_ALIASES = {"DIV": "DES"}
COMMS = {"MAT","STM","SJT","SJB","DES","NSL"}
COMM_NAMES = {
    "MAT": "Matriz (Paróquia Nossa Senhora Medianeira de Todas as Graças)",
    "STM": "São Tiago Maior",
    "SJT": "São Judas Tadeu",
    "SJB": "São João Batista",
    "DES": "Divino Espírito Santo",
    "NSL": "Nossa Senhora de Lourdes",
}
PACKS = {
    1: ["LIB"],
    2: ["LIB", "CRU"],
    3: ["LIB", "CRU", "MIC"],
    4: ["LIB", "CRU", "TUR", "NAV"],
    5: ["LIB", "CRU", "MIC", "TUR", "NAV"],
    6: ["LIB", "CRU", "MIC", "TUR", "NAV", "CAM"],
    7: ["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2"],
    8: ["LIB", "CRU", "MIC", "TUR", "NAV", "CER1", "CER2", "CAM"],
}

# ===== Capacitação por função (skills) =====
def all_roles():
    # Define ordem básica das funções inline para evitar dependência circular
    role_order_base = ["LIB","CRU","MIC","TUR","NAV","CER1","CER2","CAM"]
    base = set()
    for arr in PACKS.values():
        base.update(arr)
    # ordena pelas bases conhecidas
    return sorted(base, key=lambda r: (role_order_base.index(r) if r in role_order_base else 999, r))

ALL_ROLES = all_roles()

ROLE_ALIASES = {
    "CERO1":"CER1", "CERO2":"CER2", "CEROFERARIO1":"CER1", "CEROFERARIO2":"CER2",
    "CRUCIFERARIO":"CRU", "LIBRIFERO":"LIB", "MICROFONARIO":"MIC",
    "NAVETEIRO":"NAV", "TURIFERARIO":"TUR", "CAMPANARIO":"CAM"
}

def norm_role(token: str) -> str:
    r = token.strip().upper()
    r = ROLE_ALIASES.get(r, r)
    if r not in ALL_ROLES:
        raise ValueError(f"Função inválida: {token}")
    return r

def parse_roles_arg(arg: str):
    """Aceita 'ALL'|'*'|'TUDO' ou lista separada por vírgulas/espaços."""
    up = arg.strip().upper()
    if up in ("ALL","*","TUDO"):
        return set(ALL_ROLES)
    parts = [p for p in re.split(r"[,\s]+", arg) if p]
    roles = {norm_role(p) for p in parts}
    return roles
DEFAULT_MORNING_PREF = set()

DEFAULT_ACOLITOS = [
    (1,  "Fábio Miguel",   "STM"),
    (2,  "Maria Fernanda", "STM"),
    (3,  "Pedro Miguel",   "STM"),
    (4,  "Melissa Martins","STM"),
    (5,  "Nuno",           "STM"),
    (6,  "Melissa Paes",   "MAT"),
    (7,  "Heloa",          "MAT"),
    (8,  "Mariana",        "MAT"),
    (9,  "Sara",           "MAT"),
    (10, "Kalynda",        "MAT"),
    (11, "Manuela",        "MAT"),
    (12, "Heloísa",        "MAT"),
    (13, "Lucca",          "MAT"),
    (14, "Danilo",         "SJT"),
    (15, "Luiz Fernando",  "SJT"),
    (16, "Leandro",        "SJT"),
    (17, "Pedro",          "NSL"),
    (18, "Emanuelly",      "NSL"),
    (19, "Davi",           "DES"),
    (20, "Eloá",           "DES"),
    (21, "Maria Clara",    "SJB"),
    (22, "Mickael Enzo",   "SJB"),
]

# =================== Estruturas em memória ===================
class Event:
    def __init__(self, com, dt, qty, series_id=None, kind="REG"):
        self.com = com
        self.dt = dt
        self.qty = qty
        self.kind = kind           # REG | SOLENE
        self.series_id = series_id
        self.funcs = compose_functions(qty)
        self.meta = {}
        self.id = event_id_from(com, dt)

    def update_from(self, other):
        self.com = other.com
        self.dt = other.dt
        self.qty = other.qty
        self.funcs = compose_functions(other.qty)
        self.id = event_id_from(self.com, self.dt)

# Estado
EVENTS = {}               # id -> Event
SERIES_INDEX = {}         # series_id -> [event_id, ...]
ASSIGNMENTS = {}          # event_id -> [(func, ac_id), ...]

# Acolitos + prefs/flags
AC_DATA = {}
BLOCKS = defaultdict(list)  # aid -> list de {'start': dt, 'end': dt, 'note': str}

# Histórico para UNDO
HISTORY = []  # pilha de estados anteriores (to_json)
MAX_HISTORY = 50

# =================== Sistema de Histórico para UNDO ===================
def push_history(label=""):
    snap = {
        "label": label,
        "ts": datetime.now().isoformat(),
        "state": to_json()
    }
    HISTORY.append(snap)
    if len(HISTORY) > MAX_HISTORY:
        HISTORY.pop(0)

def undo_last():
    if not HISTORY:
        print("∅ Nada para desfazer."); return
    snap = HISTORY.pop()
    from_json(snap["state"])
    print(f"↩️  UNDO aplicado ({snap.get('label','')}).")

# =================== Inicialização de acólitos ===================
def init_acolitos():
    global AC_DATA
    AC_DATA = {}
    for aid, name, home in DEFAULT_ACOLITOS:
        AC_DATA[aid] = {
            "name": name,
            "home": normalize_com(home),
            "skills": set(ALL_ROLES),   # << todos qualificados por padrão
            "manha": (aid in DEFAULT_MORNING_PREF),
            "ativo": True,
        }

# =================== Utilidades ===================
def now_dt():
    # sempre usa o tempo real do SO
    return datetime.now()

def today_date():
    return now_dt().date()

def noacc(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn').upper()

def shorten(txt, maxlen=18):
    if txt is None: return ""
    if len(txt) <= maxlen: return txt
    return txt[:maxlen-1] + "…"

def normalize_com(com):
    com = com.upper()
    if com in COMM_ALIASES: com = COMM_ALIASES[com]
    if com not in COMMS: raise ValueError(f"Comunidade inválida: {com}")
    return com

def event_id_from(com, dtm):
    return f"{com}{dtm.strftime('%d%m%Y%H%M')}"

def infer_year(day, month, year_opt):
    today = now_dt()
    if year_opt:
        y = int(year_opt)
        if y < 100:
            y += 2000 if y < 70 else 1900
        return y
    y = today.year
    try_dt = datetime(y, month, day)
    if try_dt.date() < today.date():
        y += 1
    return y

EVK_RE = re.compile(r"^(?P<com>[A-Za-z]{3})(?P<dd>\d{2})(?P<mm>\d{2})(?P<yy>\d{2}|\d{4})?(?P<hh>\d{2})(?P<mi>\d{2})(?P<q>\d{1,2})?$")

def parse_eventkey(token):
    m = EVK_RE.match(token)
    if not m: raise ValueError("EventKey inválido.")
    com = normalize_com(m.group("com"))
    dd = int(m.group("dd")); mm = int(m.group("mm"))
    yy = m.group("yy")
    hh = int(m.group("hh")); mi = int(m.group("mi"))
    y = infer_year(dd, mm, yy)
    dtm = datetime(y, mm, dd, hh, mi)
    q = m.group("q")
    qty = int(q) if q else None
    return com, dtm, qty

def norm_q(qstr: str) -> int:
    q = int(qstr.lstrip('0') or '0')
    if q <= 0:
        raise ValueError("Quantidade Q deve ser ≥ 1.")
    return q

def compose_functions(q):
    q = int(q)
    if q in PACKS: return list(PACKS[q])
    keys = sorted(PACKS.keys())
    lower = max([k for k in keys if k <= q], default=keys[0])
    funcs = list(PACKS[lower])
    # ordem para preencher funções extras se Q > maior pack conhecido
    extra_order = ["CER1","CER2","CRU","MIC","NAV","CAM","TUR","LIB"]
    i = 0
    while len(funcs) < q:
        funcs.append(extra_order[i % len(extra_order)])
        i += 1
    if len(funcs) > q:
        funcs = funcs[:q]
    return funcs

def ensure_series_list(sid):
    if sid not in SERIES_INDEX: SERIES_INDEX[sid] = []

def mk_series_id(prefix, base_token):
    return f"{prefix}-{base_token}"

def is_morning(dtm): return dtm.hour < 12

def fmt_dt(dtm):
    wd = ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"][dtm.weekday()]
    return f"{wd} {dtm.strftime('%d/%m/%Y %H:%M')}"

def fmt_time(dtm): return dtm.strftime("%H:%M")

def default_period():
    start = today_date()
    end = start + timedelta(days=DEFAULT_VIEW_DAYS-1)
    return start, end

# =================== CR/Recorrência ===================
DOW_CANON = {"SEG":0, "TER":1, "QUA":2, "QUI":3, "SEX":4, "SA":5, "DO":6}
DOW_SYNONYMS = {
    "SEGUNDA":"SEG",
    "TERCA":"TER",  "TERÇA":"TER",
    "QUARTA":"QUA",
    "QUINTA":"QUI",
    "SEXTA":"SEX",
    "SAB":"SA", "SABADO":"SA", "SÁBADO":"SA", "SAT":"SA",
    "DOM":"DO", "DOMINGO":"DO", "SUN":"DO",
}

def dow_to_int(dow_token: str):
    t = noacc(dow_token)
    canon = DOW_SYNONYMS.get(t, t)
    if canon not in DOW_CANON:
        raise ValueError("Dia da semana inválido (use: SEG/TER/QUA/QUI/SEX/SABADO/DOMINGO...).")
    return canon, DOW_CANON[canon]

def parse_date_compact(s):
    if len(s) == 6:  # DDMMYY
        dd, mm, yy = int(s[:2]), int(s[2:4]), int(s[4:6])
        yy += 2000 if yy < 70 else 1900
        return date(yy, mm, dd)
    if len(s) == 8:  # DDMMYYYY
        dd, mm, yyyy = int(s[:2]), int(s[2:4]), int(s[4:8])
        return date(yyyy, mm, dd)
    raise ValueError("Data compacta inválida (use DDMMYY ou DDMMYYYY).")

REC_SHORT_RE = re.compile(r"^(?P<com>[A-Za-z]{3})(?P<dow>[A-Za-zÀ-ÿ]{2,12})(?P<hh>\d{2})(?P<mi>\d{2})(?P<q>0?\d{1,2})$")
REC_FULL_RE  = re.compile(r"^(?P<com>[A-Za-z]{3})(?P<dow>[A-Za-zÀ-ÿ]{2,12})(?P<hh>\d{2})(?P<mi>\d{2})(?P<q>0?\d{1,2})(?P<ini>\d{6,8})(?P<fim>\d{6,8})$")

def month_add(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))

def create_recurring(token):
    m = REC_FULL_RE.match(token)
    short = False
    if not m:
        m = REC_SHORT_RE.match(token)
        short = True
    if not m:
        raise ValueError("Formato CR inválido. Ex.: CR SJBSABADO17002  ou  CR STMSA183002011025311225")

    com = normalize_com(m.group("com"))
    dow_canon, dow_int = dow_to_int(m.group("dow"))
    hh = int(m.group("hh")); mi = int(m.group("mi"))
    q  = norm_q(m.group("q"))

    if short:
        today = today_date()
        offset = (dow_int - today.weekday()) % 7
        start = today + timedelta(days=offset)
        end   = month_add(start, DEFAULT_RECURRENCE_MONTHS) - timedelta(days=1)
    else:
        start = parse_date_compact(m.group("ini"))
        end   = parse_date_compact(m.group("fim"))
        if end < start:
            raise ValueError("Período inválido (fim antes do início).")

    sid = f"CR-{com}{dow_canon}{hh:02d}{mi:02d}Q{q}-{start.strftime('%d%m%Y')}..{end.strftime('%d%m%Y')}"
    ensure_series_list(sid)
    cur = start; count = 0
    while cur <= end:
        if cur.weekday() == dow_int:
            dtm = datetime(cur.year, cur.month, cur.day, hh, mi)
            ev = Event(com, dtm, q, series_id=sid, kind="REG")
            upsert_event(ev)
            SERIES_INDEX[sid].append(ev.id)
            count += 1
        cur += timedelta(days=1)
    SERIES_INDEX[sid] = sorted(SERIES_INDEX[sid], key=lambda x: EVENTS[x].dt)
    return sid, count

# =================== Comando SWAP ===================
def swap_roles(event_token_1, role1, event_token_2=None, role2=None):
    role1 = role1.upper()
    if role2: role2 = role2.upper()

    def _get_ev_and_pairs(tok):
        com, dtm, _ = parse_eventkey(tok)
        eid = event_id_from(com, dtm)
        if eid not in EVENTS: raise ValueError("Evento não encontrado.")
        ev = EVENTS[eid]
        pairs = dict(ASSIGNMENTS.get(eid, []))
        return eid, ev, pairs

    if event_token_2 is None:
        # SWAP EKey R1 WITH R2 (mesmo evento)
        raise ValueError("Uso interno incorreto; chame com 2 tokens para WITH.")

    eid1, ev1, p1 = _get_ev_and_pairs(event_token_1)
    eid2, ev2, p2 = _get_ev_and_pairs(event_token_2)

    if role1 not in ev1.funcs: raise ValueError(f"Função {role1} não existe no evento 1.")
    if role2 not in ev2.funcs: raise ValueError(f"Função {role2} não existe no evento 2.")

    a1 = p1.get(role1)
    a2 = p2.get(role2)

    # aplica
    push_history(f"SWAP {eid1}:{role1} <-> {eid2}:{role2}")
    if a2 is None:
        p1.pop(role1, None)
    else:
        p1[role1] = a2
    if a1 is None:
        p2.pop(role2, None)
    else:
        p2[role2] = a1

    # reordena conforme pack
    order1 = {r:i for i,r in enumerate(ev1.funcs)}
    order2 = {r:i for i,r in enumerate(ev2.funcs)}
    ASSIGNMENTS[eid1] = sorted(p1.items(), key=lambda kv: order1[kv[0]])
    ASSIGNMENTS[eid2] = sorted(p2.items(), key=lambda kv: order2[kv[0]])

    def _nm(aid): 
        return f"#{aid} {AC_DATA[aid]['name']}" if aid else "—"
    print(f"🔁 SWAP: {ev1.id}:{role1} ({_nm(a1)})  ⇄  {ev2.id}:{role2} ({_nm(a2)})  → OK")

# =================== CR CANCELAR ===================
def cr_cancelar_unica_data(event_key):
    com, dtm, _ = parse_eventkey(event_key)
    eid = event_id_from(com, dtm)
    if eid not in EVENTS:
        print("∅ Evento não encontrado."); return
    ev = EVENTS[eid]
    if not ev.series_id or not ev.series_id.startswith("CR-"):
        print("∅ Este evento não pertence a uma recorrência CR."); return
    push_history(f"CR CANCELAR {eid}")
    # remove
    EVENTS.pop(eid, None)
    ASSIGNMENTS.pop(eid, None)
    if ev.series_id in SERIES_INDEX:
        arr = SERIES_INDEX[ev.series_id]
        if eid in arr: arr.remove(eid)
        if not arr: del SERIES_INDEX[ev.series_id]
    print(f"🗑️  Cancelada a data única da CR: {eid}.")

# =================== CRUD de Eventos/Séries ===================
def upsert_event(ev: Event):
    EVENTS[ev.id] = ev
    if ev.id in ASSIGNMENTS:
        keep = [(f,a) for (f,a) in ASSIGNMENTS[ev.id] if f in ev.funcs]
        ASSIGNMENTS[ev.id] = keep

def remove_event_by_key(tok):
    com, dtm, _ = parse_eventkey(tok)
    ev_id = event_id_from(com, dtm)
    if ev_id in EVENTS:
        del EVENTS[ev_id]
        ASSIGNMENTS.pop(ev_id, None)
        for sid, arr in list(SERIES_INDEX.items()):
            if ev_id in arr:
                arr.remove(ev_id)
                if not arr: del SERIES_INDEX[sid]
        return True
    return False

def edit_event(tok_old, tok_new):
    com1, dt1, _ = parse_eventkey(tok_old)
    ev_id = event_id_from(com1, dt1)
    if ev_id not in EVENTS:
        raise ValueError("Evento original não encontrado.")
    old = EVENTS[ev_id]
    com2, dt2, q2 = parse_eventkey(tok_new)
    new_ev = Event(com2, dt2, q2 if q2 is not None else old.qty, series_id=old.series_id, kind=old.kind)
    old_id = old.id
    old.update_from(new_ev)
    new_id = old.id
    if old_id != new_id:
        EVENTS.pop(old_id, None)
        EVENTS[new_id] = old
        if old_id in ASSIGNMENTS:
            keep = [(f,a) for (f,a) in ASSIGNMENTS.pop(old_id) if f in old.funcs]
            ASSIGNMENTS[new_id] = keep
        for sid, arr in SERIES_INDEX.items():
            for i, x in enumerate(arr):
                if x == old_id: arr[i] = new_id
    else:
        if new_id in ASSIGNMENTS:
            keep = [(f,a) for (f,a) in ASSIGNMENTS[new_id] if f in old.funcs]
            ASSIGNMENTS[new_id] = keep
    return old.id

def create_series(prefix, base_token, days, kind="SOLENE"):
    com, dtm, qty = parse_eventkey(base_token)
    if qty is None:
        raise ValueError("Séries exigem quantidade no EventKey base (…Q).")
    sid = mk_series_id(prefix, base_token)
    ids = []
    for i in range(days):
        dt_i = dtm + timedelta(days=i)
        ev = Event(com, dt_i, qty, series_id=sid, kind=kind)
        upsert_event(ev)
        ids.append(ev.id)
    SERIES_INDEX[sid] = sorted(ids, key=lambda x: EVENTS[x].dt)
    return sid, ids

# =================== Métricas de janela / verificações ===================
def counts_in_window(ev_dt, window_days, assignments_subset=None):
    """Contagem de atribuições por acólito nos últimos `window_days` até ev_dt (inclusive)."""
    src = ASSIGNMENTS if assignments_subset is None else assignments_subset
    start = ev_dt - timedelta(days=window_days)
    cnt = defaultdict(int)
    for eid, pairs in src.items():
        dt = EVENTS[eid].dt
        if start <= dt <= ev_dt:
            for _, aid in pairs:
                cnt[aid] += 1
    return cnt

def last_assignment_before(aid, ev_dt, assignments_subset=None):
    src = ASSIGNMENTS if assignments_subset is None else assignments_subset
    last = None
    for eid, pairs in src.items():
        for _, a in pairs:
            if a == aid:
                dt = EVENTS[eid].dt
                if dt <= ev_dt and (last is None or dt > last):
                    last = dt
    return last

def role_count_in_window(aid, role, ev_dt, window_days, assignments_subset=None):
    src = ASSIGNMENTS if assignments_subset is None else assignments_subset
    start = ev_dt - timedelta(days=window_days)
    c = 0
    for eid, pairs in src.items():
        dt = EVENTS[eid].dt
        if start <= dt <= ev_dt:
            for r, a in pairs:
                if a == aid and r == role:
                    c += 1
    return c

def has_time_conflict(aid, ev_dt, window_minutes=NO_OVERLAP_MINUTES, assignments_subset=None):
    src = ASSIGNMENTS if assignments_subset is None else assignments_subset
    for eid, pairs in src.items():
        for _, a in pairs:
            if a == aid:
                dt = EVENTS[eid].dt
                if abs((ev_dt - dt).total_seconds()) < window_minutes * 60:
                    return True
    return False

def is_blocked(aid, dtm):
    for blk in BLOCKS.get(aid, []):
        if blk["start"] <= dtm <= blk["end"]:
            return True
    return False

# =================== Núcleo de seleção (local-first com fairness forte) ===================
def candidate_is_eliminated(aid, ev, role, tmp_assignments):
    """Regras duras que eliminam o candidato."""
    a = AC_DATA.get(aid)
    if not a or not a.get("ativo", True):
        return True
    # capacitação por função
    if role not in a.get("skills", set()):
        return True
    if is_blocked(aid, ev.dt):
        return True
    if has_time_conflict(aid, ev.dt, assignments_subset=tmp_assignments):
        return True
    return False

def compute_threshold_and_counts(ev_dt, tmp_assignments):
    counts = counts_in_window(ev_dt, FAIR_WINDOW_DAYS, assignments_subset=tmp_assignments)
    active_ids = [aid for aid, meta in AC_DATA.items() if meta.get("ativo", True)]
    if not active_ids:
        avg = 0.0
    else:
        avg = mean([counts.get(aid, 0) for aid in active_ids])
    thresh = avg + WORKLOAD_TOLERANCE
    return thresh, counts

def score_candidate(aid, ev, role, window_counts, tmp_assignments):
    """Score para desempate entre candidatos válidos."""
    a = AC_DATA[aid]
    s = 0.0
    # 1) Balanceamento de carga: menor contagem na janela = melhor
    cur = window_counts.get(aid, 0)
    s -= cur * W_LOAD_BAL
    # 2) Recência geral
    last = last_assignment_before(aid, ev.dt, assignments_subset=tmp_assignments)
    if last is not None:
        gap_days = max(0.0, (ev.dt - last).total_seconds() / 86400.0)
        s += gap_days * W_RECENCY
    else:
        s += 7.5 * W_RECENCY  # pequeno impulso para quem nunca serviu na janela
    # 3) Rotatividade de função: penaliza repetição recente da mesma função
    same_role_recent = role_count_in_window(aid, role, ev.dt, ROLE_ROT_WINDOW_DAYS, assignments_subset=tmp_assignments)
    s -= same_role_recent * W_ROLE_ROT
    # 4) Preferência manhã/noite
    if (a["manha"] and is_morning(ev.dt)) or ((not a["manha"]) and (not is_morning(ev.dt))):
        s += W_MORNING
    # 5) Evento solene: pequeno bônus
    if ev.kind == "SOLENE":
        s += W_SOLENE
    return s

def pick_best(ev, role, tmp_assignments, chosen_ids):
    """Escolhe o melhor candidato respeitando as regras local-first e limites de carga."""
    # 1) Candidatos elegíveis (sem eliminações duras e não repetidos no mesmo evento)
    eligible = []
    for aid in AC_DATA.keys():
        if aid in chosen_ids: 
            continue
        if candidate_is_eliminated(aid, ev, role, tmp_assignments):
            continue
        eligible.append(aid)
    if not eligible:
        return None

    # 2) Threshold e contagens na janela
    thresh, win_counts = compute_threshold_and_counts(ev.dt, tmp_assignments)

    def proj_ok(aid):
        return (win_counts.get(aid, 0) + 1) <= thresh

    # 3) Particiona por comunidade (local / outros)
    locals_ok = [aid for aid in eligible if AC_DATA[aid]["home"] == ev.com and proj_ok(aid)]
    others_ok = [aid for aid in eligible if AC_DATA[aid]["home"] != ev.com and proj_ok(aid)]

    # 4) Se houver locais válidos, escolhe entre eles pelo score
    if locals_ok:
        ranked = sorted(locals_ok, key=lambda x: (-score_candidate(x, ev, role, win_counts, tmp_assignments), AC_DATA[x]["name"], x))
        return ranked[0]

    # 5) Senão, se houver não-locais válidos, escolhe entre eles
    if others_ok:
        ranked = sorted(others_ok, key=lambda x: (-score_candidate(x, ev, role, win_counts, tmp_assignments), AC_DATA[x]["name"], x))
        return ranked[0]

    # 6) Nenhum válido: escolhe menor excesso (primeiro locais; senão globais)
    def overflow(aid):
        return (win_counts.get(aid, 0) + 1) - thresh

    local_all = [aid for aid in eligible if AC_DATA[aid]["home"] == ev.com]
    if local_all:
        best_local = min(local_all, key=lambda a: (overflow(a), -score_candidate(a, ev, role, win_counts, tmp_assignments), AC_DATA[a]["name"], a))
        return best_local

    # fallback global
    best_global = min(eligible, key=lambda a: (overflow(a), -score_candidate(a, ev, role, win_counts, tmp_assignments), AC_DATA[a]["name"], a))
    return best_global

# =================== Escalonadores ===================
def assign_incremental():
    """Atribui apenas para eventos ainda não atribuídos, respeitando ordenação temporal e solenes primeiro."""
    ordered = sorted(EVENTS.values(), key=lambda e: (0 if e.kind=="SOLENE" else 1, e.dt))
    tmp_assignments = {eid: list(pairs) for eid, pairs in ASSIGNMENTS.items()}
    for ev in ordered:
        existing = dict(tmp_assignments.get(ev.id, []))
        result_pairs = tmp_assignments.get(ev.id, []).copy()
        chosen_ids = set(existing.values())
        for role in ev.funcs:
            if role in existing:
                continue
            best = pick_best(ev, role, tmp_assignments, chosen_ids)
            if best is None:
                continue
            result_pairs.append((role, best))
            chosen_ids.add(best)
            # ordena conforme pack
            order = {r:i for i,r in enumerate(ev.funcs)}
            result_pairs.sort(key=lambda p: order.get(p[0], 999))
            tmp_assignments[ev.id] = list(result_pairs)
    # confirma
    for eid, pairs in tmp_assignments.items():
        ASSIGNMENTS[eid] = list(pairs)

def recalc_global(start_date=None, end_date=None):
    """Recalcula atribuições do período, preservando o que está fora do intervalo."""
    if start_date is None or end_date is None:
        in_scope_ids = list(EVENTS.keys())
    else:
        in_scope_ids = [eid for eid, ev in EVENTS.items() if start_date <= ev.dt.date() <= end_date]

    fixed_assign = {}
    for eid, pairs in ASSIGNMENTS.items():
        if eid not in in_scope_ids:
            fixed_assign[eid] = list(pairs)

    # zera dentro do escopo
    for eid in in_scope_ids:
        ASSIGNMENTS.pop(eid, None)

    evs_scope = sorted([EVENTS[eid] for eid in in_scope_ids],
                       key=lambda e: (0 if e.kind=="SOLENE" else 1, e.dt, e.com))

    tmp = {**fixed_assign}
    for ev in evs_scope:
        chosen = set()
        result_pairs = []
        for role in ev.funcs:
            best = pick_best(ev, role, tmp, chosen)
            if best is None:
                continue
            result_pairs.append((role, best))
            chosen.add(best)
        # ordena conforme pack
        order = {r:i for i,r in enumerate(ev.funcs)}
        result_pairs.sort(key=lambda p: order.get(p[0], 999))
        ASSIGNMENTS[ev.id] = list(result_pairs)
        tmp[ev.id] = list(result_pairs)

# =================== MINHA_ESCALA ===================
def minha_escala(aid, start_date=None, end_date=None):
    if aid not in AC_DATA: 
        print("∅ Acólito não encontrado."); return
    if not (start_date and end_date):
        start_date, end_date = default_period()
    assign_incremental()
    rows = []
    for eid, pairs in ASSIGNMENTS.items():
        ev = EVENTS.get(eid)
        if not ev: continue
        if not (start_date <= ev.dt.date() <= end_date): continue
        for role, a in pairs:
            if a == aid:
                rows.append((ev.dt, ev.com, role, ev))
    rows.sort(key=lambda t: (t[0], t[1]))
    print_divider(); 
    print(f"Escala de #{aid} {AC_DATA[aid]['name']}  ({start_date.strftime('%d/%m/%Y')}..{end_date.strftime('%d/%m/%Y')})")
    print_divider(ch='-')
    if not rows:
        print("∅ Sem atribuições no período.")
    else:
        for dtm, com, role, ev in rows:
            print(f"{dtm.strftime('%d/%m/%Y')} {dtm.strftime('%H:%M')}  {com}  → {role}  [{ev.id}]")
    print_divider()

# =================== Remoções em massa ===================
def parse_single_date(tok):
    if re.match(r"^\d{2}\d{2}\d{4}$", tok):
        dd,mm,yyyy = int(tok[:2]), int(tok[2:4]), int(tok[4:])
        return date(yyyy, mm, dd)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", tok):
        yyyy,mm,dd = map(int, tok.split("-"))
        return date(yyyy, mm, dd)
    raise ValueError("Data inválida. Use DDMMYYYY ou YYYY-MM-DD.")

def remove_events_on_day(d):
    push_history(f"R DAY {d.isoformat()}")
    removed = 0
    for eid, ev in list(EVENTS.items()):
        if ev.dt.date() == d:
            EVENTS.pop(eid, None)
            ASSIGNMENTS.pop(eid, None)
            # limpa de séries
            if ev.series_id and ev.series_id in SERIES_INDEX:
                arr = SERIES_INDEX[ev.series_id]
                if eid in arr: arr.remove(eid)
                if not arr: del SERIES_INDEX[ev.series_id]
            removed += 1
    print(f"🗑️  Removidos {removed} evento(s) em {d.strftime('%d/%m/%Y')}.")

# =================== Formatação e Visualizações ===================
def fmt_event_line(ev: Event):
    pack = ",".join(ev.funcs)
    return f"{COMM_NAMES[ev.com]} ({ev.com}) • {fmt_dt(ev.dt)} • Q={ev.qty} • [{pack}] • id={ev.id}"

def fmt_assignment(ev: Event):
    pairs = ASSIGNMENTS.get(ev.id, [])
    out = []
    for role, aid in pairs:
        meta = AC_DATA[aid]
        out.append(f"{role:<8} → {meta['name']} (#{aid}, {meta['home']})")
    return "\n".join(out) if out else "— (sem atribuições)"

def print_divider(w=80, ch='='):
    print(ch * w)

def list_range(start_date_, end_date_):
    evs = [e for e in EVENTS.values() if start_date_ <= e.dt.date() <= end_date_]
    evs.sort(key=lambda e: (e.dt, e.com))
    if not evs:
        print("∅ Sem eventos no período."); return
    for ev in evs: print("•", fmt_event_line(ev))

def list_month(yyyy_mm):
    y, m = map(int, yyyy_mm.split("-"))
    start = date(y, m, 1)
    end = date(y+1,1,1) - timedelta(days=1) if m==12 else date(y, m+1, 1) - timedelta(days=1)
    list_range(start, end)

def list_next_month_from_today():
    # agora lista do hoje até final do mês atual
    today = today_date()
    end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    list_range(today, end)

def parse_range_token(tok):
    if re.match(r"^\d{4}-\d{2}$", tok):
        y, m = tok.split("-"); y=int(y); m=int(m)
        start = date(y, m, 1)
        end = date(y+1,1,1) - timedelta(days=1) if m==12 else date(y, m+1, 1) - timedelta(days=1)
        return start, end
    m = re.match(r"^(\d{2})(\d{2})\.\.(\d{2})(\d{2})$", tok)
    if m:
        dd1, mm1, dd2, mm2 = map(int, m.groups())
        y = today_date().year
        start = date(y, mm1, dd1); end = date(y, mm2, dd2)
        return start, end
    raise ValueError("Intervalo inválido. Use YYYY-MM ou DDMM..DDMM.")

# ---- Tabela da ESCALA (modo=tabela) ----
ROLE_ORDER_BASE = ["LIB","CRU","MIC","TUR","NAV","CER1","CER2","CAM"]

def collect_roles_in_events(events):
    role_set = []
    for ev in events:
        for r in ev.funcs:
            if r not in role_set:
                role_set.append(r)
    role_set.sort(key=lambda r: ROLE_ORDER_BASE.index(r) if r in ROLE_ORDER_BASE else 999)
    return role_set

def build_day_table(day_events, roles, name_w=NAME_MAX_CHARS):
    cols = ["Hora", "Com", *roles]
    widths = [5, 4] + [max(4, min(name_w, 16)) for _ in roles]
    sep = " │ "
    header = sep.join([col.ljust(widths[i]) for i, col in enumerate(cols)])
    line = "─" * len(header)
    print(header); print(line)
    for ev in sorted(day_events, key=lambda e: (e.dt, e.com)):
        row = []
        row.append(fmt_time(ev.dt).ljust(widths[0]))
        row.append(ev.com.ljust(widths[1]))
        assign = dict(ASSIGNMENTS.get(ev.id, []))
        for i, r in enumerate(roles):
            aid = assign.get(r)
            if aid is None:
                cell = "—".ljust(widths[i+2])
            else:
                nm = shorten(AC_DATA[aid]["name"], widths[i+2])
                cell = nm.ljust(widths[i+2])
            row.append(cell)
        print(sep.join(row))

def list_assignments_table(start_date_, end_date_, com_filter=None, roles_filter=None, name_w=NAME_MAX_CHARS):
    assign_incremental()
    evs = [e for e in EVENTS.values() if start_date_ <= e.dt.date() <= end_date_]
    if com_filter:
        evs = [e for e in evs if e.com in com_filter]
    evs.sort(key=lambda e: (e.dt, e.com))
    if not evs:
        print("∅ Sem eventos no período."); return
    by_day = defaultdict(list)
    for e in evs:
        by_day[e.dt.date()].append(e)
    for d in sorted(by_day.keys()):
        day_events = by_day[d]
        roles = collect_roles_in_events(day_events)
        if roles_filter:
            roles = [r for r in roles if r in roles_filter]
        wd = ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"][day_events[0].dt.weekday()]
        print_divider()
        print(f"{wd} {d.strftime('%d/%m/%Y')}")
        print_divider(ch='-')
        build_day_table(day_events, roles, name_w=name_w)
    print_divider()

def list_assignments_lines(start_date_, end_date_, com_filter=None):
    assign_incremental()
    evs = [e for e in EVENTS.values() if start_date_ <= e.dt.date() <= end_date_]
    if com_filter:
        evs = [e for e in evs if e.com in com_filter]
    evs.sort(key=lambda e: (e.dt, e.com))
    if not evs:
        print("∅ Sem eventos no período."); return
    for ev in evs:
        print_divider(); print(fmt_event_line(ev)); print("-"*80); print(fmt_assignment(ev))
    print_divider()

def list_assignments_csv(start_date_, end_date_, com_filter=None, roles_filter=None):
    assign_incremental()
    evs = [e for e in EVENTS.values() if start_date_ <= e.dt.date() <= end_date_]
    if com_filter:
        evs = [e for e in evs if e.com in com_filter]
    evs.sort(key=lambda e: (e.dt, e.com))
    if not evs:
        print("date,weekday,time,com,role,aid,name,home"); return
    print("date,weekday,time,com,role,aid,name,home")
    for ev in evs:
        wd = ["Seg","Ter","Qua","Qui","Sex","Sab","Dom"][ev.dt.weekday()]
        pairs = ASSIGNMENTS.get(ev.id, [])
        if roles_filter:
            pairs = [p for p in pairs if p[0] in roles_filter]
        for role, aid in pairs:
            meta = AC_DATA[aid]
            print(f"{ev.dt.date().isoformat()},{wd},{ev.dt.strftime('%H:%M')},{ev.com},{role},{aid},{meta['name']},{meta['home']}")

# =================== Exportações ===================
def export_csv(path, start_date_, end_date_, com_filter=None, roles_filter=None):
    assign_incremental()
    evs = [e for e in EVENTS.values() if start_date_ <= e.dt.date() <= end_date_]
    if com_filter:
        evs = [e for e in evs if e.com in com_filter]
    evs.sort(key=lambda e: (e.dt, e.com))
    with open(path, "w", encoding="utf-8") as f:
        f.write("date,weekday,time,com,role,aid,name,home\n")
        for ev in evs:
            wd = ["Seg","Ter","Qua","Qui","Sex","Sab","Dom"][ev.dt.weekday()]
            pairs = ASSIGNMENTS.get(ev.id, [])
            if roles_filter:
                pairs = [p for p in pairs if p[0] in roles_filter]
            for role, aid in pairs:
                meta = AC_DATA[aid]
                line = f"{ev.dt.date().isoformat()},{wd},{ev.dt.strftime('%H:%M')},{ev.com},{role},{aid},{meta['name']},{meta['home']}\n"
                f.write(line)
    print(f"💾 CSV exportado: {path}")

def export_ics(path, start_date_, end_date_, com_filter=None):
    evs = [e for e in EVENTS.values() if start_date_ <= e.dt.date() <= end_date_]
    if com_filter:
        evs = [e for e in evs if e.com in com_filter]
    evs.sort(key=lambda e: (e.dt, e.com))
    def dt_ics(dt):
        return dt.strftime("%Y%m%dT%H%M%S")
    lines = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//Escala CLI//PT-BR//")
    for ev in evs:
        desc = []
        for role, aid in ASSIGNMENTS.get(ev.id, []):
            meta = AC_DATA[aid]
            desc.append(f"{role}: {meta['name']} (#{aid}, {meta['home']})")
        desc_text = "\\n".join(desc) if desc else "Sem atribuições"
        uid = f"{ev.id}@escala"
        dtend = ev.dt + timedelta(hours=1, minutes=15)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{dt_ics(datetime.utcnow())}Z",
            f"DTSTART:{dt_ics(ev.dt)}",
            f"DTEND:{dt_ics(dtend)}",
            f"SUMMARY:Missa - {COMM_NAMES[ev.com]} ({ev.com})",
            f"DESCRIPTION:{desc_text}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"💾 ICS exportado: {path}")

# =================== Persistência ===================
def to_json():
    data = {
        "events": {eid: {
            "com": ev.com, "dt": ev.dt.isoformat(), "qty": ev.qty,
            "series_id": ev.series_id, "kind": ev.kind, "meta": ev.meta
        } for eid, ev in EVENTS.items()},
        "series_index": SERIES_INDEX,
        "assignments": {eid: list(pairs) for eid, pairs in ASSIGNMENTS.items()},
        "ac_data": {
            int(aid): {
                **{k:v for k,v in meta.items() if k != "skills"},
                "skills": sorted(list(meta.get("skills", [])))
            } for aid, meta in AC_DATA.items()
        },
        "blocks": {str(aid): [{"start": b["start"].isoformat(), "end": b["end"].isoformat(), "note": b.get("note","")} for b in arr] for aid, arr in BLOCKS.items()},
        "config": {
            "DEFAULT_RECURRENCE_MONTHS": DEFAULT_RECURRENCE_MONTHS,
            "NO_OVERLAP_MINUTES": NO_OVERLAP_MINUTES,
            "NAME_MAX_CHARS": NAME_MAX_CHARS,
            "FAIR_WINDOW_DAYS": FAIR_WINDOW_DAYS,
            "ROLE_ROT_WINDOW_DAYS": ROLE_ROT_WINDOW_DAYS,
            "WORKLOAD_TOLERANCE": WORKLOAD_TOLERANCE,
            "DEFAULT_VIEW_DAYS": DEFAULT_VIEW_DAYS,
        }
    }
    return data

def from_json(data):
    global EVENTS, SERIES_INDEX, ASSIGNMENTS, AC_DATA, BLOCKS
    EVENTS.clear(); SERIES_INDEX.clear(); ASSIGNMENTS.clear(); BLOCKS.clear()
    AC_DATA.clear()
    # events
    for eid, d in data.get("events", {}).items():
        ev = Event(d["com"], datetime.fromisoformat(d["dt"]), d["qty"], d.get("series_id"), d.get("kind","REG"))
        ev.meta = d.get("meta", {})
        EVENTS[eid] = ev
    # series
    for sid, arr in data.get("series_index", {}).items():
        SERIES_INDEX[sid] = list(arr)
    # assignments
    for eid, pairs in data.get("assignments", {}).items():
        ASSIGNMENTS[eid] = [tuple(p) for p in pairs]
    # ac_data
    ac_in = data.get("ac_data", {})
    if ac_in:
        for aid_key, obj in ac_in.items():
            aid = int(aid_key)
            meta = dict(obj)
            skills = set(meta.get("skills", ALL_ROLES))
            meta["skills"] = set(skills)
            # saneamento campos antigos
            meta.pop("tur", None)
            AC_DATA[aid] = meta
    else:
        init_acolitos()
    # blocks
    for aid_str, arr in data.get("blocks", {}).items():
        aid = int(aid_str)
        BLOCKS[aid] = [{"start": datetime.fromisoformat(b["start"]), "end": datetime.fromisoformat(b["end"]), "note": b.get("note","")} for b in arr]
    # config
    cfg = data.get("config", {})
    globals()["DEFAULT_RECURRENCE_MONTHS"] = int(cfg.get("DEFAULT_RECURRENCE_MONTHS", DEFAULT_RECURRENCE_MONTHS))
    globals()["NO_OVERLAP_MINUTES"]      = int(cfg.get("NO_OVERLAP_MINUTES", NO_OVERLAP_MINUTES))
    globals()["NAME_MAX_CHARS"]          = int(cfg.get("NAME_MAX_CHARS", NAME_MAX_CHARS))
    globals()["FAIR_WINDOW_DAYS"]        = int(cfg.get("FAIR_WINDOW_DAYS", FAIR_WINDOW_DAYS))
    globals()["ROLE_ROT_WINDOW_DAYS"]    = int(cfg.get("ROLE_ROT_WINDOW_DAYS", ROLE_ROT_WINDOW_DAYS))
    globals()["WORKLOAD_TOLERANCE"]      = int(cfg.get("WORKLOAD_TOLERANCE", WORKLOAD_TOLERANCE))
    globals()["DEFAULT_VIEW_DAYS"]       = int(cfg.get("DEFAULT_VIEW_DAYS", DEFAULT_VIEW_DAYS))

# =================== Acolitos: gestão e bloqueios ===================
def a_list():
    print_divider()
    print("ID  Nome".ljust(24), "Home Manhã Ativo Funções")
    print_divider(ch='-')
    for aid in sorted(AC_DATA.keys()):
        a = AC_DATA[aid]
        skills = a.get("skills", set())
        skills_tag = "ALL" if set(skills) == set(ALL_ROLES) else f"{len(skills)}"
        print(f"{aid:<3} {shorten(a['name'],20):<20} {a['home']:<4}  {'✓' if a['manha'] else ' ' :<5} {'✓' if a['ativo'] else ' ' :<6} {skills_tag}")
    print_divider()

def a_show(aid):
    a = AC_DATA.get(aid)
    if not a:
        print("∅ Acólito não encontrado."); return
    print_divider()
    all_tag = "ALL" if set(a.get("skills", set())) == set(ALL_ROLES) else ""
    print(f"#{aid} {a['name']} | Home={a['home']} | Manhã={'sim' if a['manha'] else 'não'} | Ativo={'sim' if a['ativo'] else 'não'}")
    print(f"Funções: {all_tag or ','.join(sorted(a.get('skills', set()), key=lambda r: (ROLE_ORDER_BASE.index(r) if r in ROLE_ORDER_BASE else 999, r)))}")
    blks = BLOCKS.get(aid, [])
    if not blks:
        print("Bloqueios: (nenhum)")
    else:
        print("Bloqueios:")
        for i, b in enumerate(sorted(blks, key=lambda x: x["start"])):
            print(f"  [{i}] {b['start'].strftime('%d/%m/%Y %H:%M')} .. {b['end'].strftime('%d/%m/%Y %H:%M')}  {b.get('note','')}")
    print_divider()

def a_set(aid, kvs):
    a = AC_DATA.get(aid)
    if not a:
        print("∅ Acólito não encontrado."); return
    for k,v in kvs.items():
        kk = k.lower()
        if     kk == "name":  a["name"] = v
        elif   kk == "home":  a["home"] = normalize_com(v)
        elif   kk == "skills": a["skills"] = parse_roles_arg(v)
        elif   kk == "manha": a["manha"] = (str(v).lower() in ("1","true","sim","y","yes"))
        elif   kk == "ativo": a["ativo"] = (str(v).lower() in ("1","true","sim","y","yes"))
        else:
            print(f"Aviso: chave '{k}' ignorada.")
    print("✏️  Atualizado.")
    a_show(aid)

def parse_ddmm_range_token(tok):
    # DDMM..DDMM (ano corrente)
    m = re.match(r"^(\d{2})(\d{2})\.\.(\d{2})(\d{2})$", tok)
    if not m: return None
    dd1, mm1, dd2, mm2 = map(int, m.groups())
    y = today_date().year
    return datetime(y, mm1, dd1, 0, 0), datetime(y, mm2, dd2, 23, 59)

def a_bloq(aid, date_tok, time_tok=None, note=None):
    # date_tok: DDMM..DDMM OU YYYY-MM
    st, en = None, None
    r = parse_ddmm_range_token(date_tok)
    if r:
        st, en = r
    else:
        m = re.match(r"^(\d{4})-(\d{2})$", date_tok)
        if m:
            y, mm = int(m.group(1)), int(m.group(2))
            st = datetime(y, mm, 1, 0, 0)
            last = calendar.monthrange(y, mm)[1]
            en = datetime(y, mm, last, 23, 59)
        else:
            raise ValueError("Formato de data inválido. Use DDMM..DDMM ou YYYY-MM.")
    if time_tok:
        m2 = re.match(r"^(\d{4})\.\.(\d{4})$", time_tok)
        if not m2: raise ValueError("Horário inválido. Use HHMM..HHMM.")
        hh1, mi1, hh2, mi2 = int(m2.group(1)[:2]), int(m2.group(1)[2:]), int(m2.group(2)[:2]), int(m2.group(2)[2:])
        st = st.replace(hour=hh1, minute=mi1)
        en = en.replace(hour=hh2, minute=mi2)
    BLOCKS[aid].append({"start": st, "end": en, "note": note or ""})
    print(f"⛔ Bloqueio adicionado para #{aid} de {st.strftime('%d/%m/%Y %H:%M')} a {en.strftime('%d/%m/%Y %H:%M')}.")

def a_unbloq(aid, idx_tok):
    if idx_tok.lower() == "all":
        BLOCKS[aid] = []
        print("✅ Todos os bloqueios removidos.")
        return
    try:
        idx = int(idx_tok)
    except:
        print("Índice inválido.")
        return
    arr = BLOCKS.get(aid, [])
    if 0 <= idx < len(arr):
        blk = arr.pop(idx)
        print(f"✅ Removido: {blk['start']}..{blk['end']}")
    else:
        print("Índice fora do intervalo.")

def a_add(kvs):
    required = {"name","home"}
    keys = {k.lower() for k in kvs.keys()}
    if not required.issubset(keys):
        print("Uso: A ADD name=<nome> home=<COM> [skills=ALL|R1,R2] [manha=0/1] [ativo=1/0]"); return
    try:
        name = kvs["name"]
        home = normalize_com(kvs["home"])
        skills = set(ALL_ROLES)
        if "skills" in kvs:
            skills = parse_roles_arg(kvs["skills"])
        manha = (str(kvs.get("manha","0")).lower() in ("1","true","sim","y","yes"))
        ativo = (str(kvs.get("ativo","1")).lower() in ("1","true","sim","y","yes"))
        new_id = max(AC_DATA.keys() or [0]) + 1
        AC_DATA[new_id] = {"name": name, "home": home, "skills": skills, "manha": manha, "ativo": ativo}
        print(f"➕ Acólito #{new_id} adicionado.")
        a_show(new_id)
    except Exception as e:
        print("Erro ao adicionar:", e)

def a_del(aid):
    if aid not in AC_DATA:
        print("∅ Acólito não encontrado."); return
    # remove de bloqueios e assignments
    BLOCKS.pop(aid, None)
    for eid, pairs in list(ASSIGNMENTS.items()):
        ASSIGNMENTS[eid] = [(r,a) for (r,a) in pairs if a != aid]
    del AC_DATA[aid]
    print(f"🗑️  Acólito #{aid} removido.")

def a_skill_list(aid):
    a = AC_DATA.get(aid)
    if not a: print("∅ Acólito não encontrado."); return
    a_show(aid)

def a_skill_set(aid, roles):
    a = AC_DATA.get(aid)
    if not a: print("∅ Acólito não encontrado."); return
    a["skills"] = set(roles)
    print("✏️  Skills definidas."); a_show(aid)

def a_skill_add(aid, roles):
    a = AC_DATA.get(aid)
    if not a: print("∅ Acólito não encontrado."); return
    a.setdefault("skills", set()).update(roles)
    print("➕ Skills adicionadas."); a_show(aid)

def a_skill_del(aid, roles):
    a = AC_DATA.get(aid)
    if not a: print("∅ Acólito não encontrado."); return
    a.setdefault("skills", set()).difference_update(roles)
    print("➖ Skills removidas."); a_show(aid)

def a_skill_clear(aid):
    a = AC_DATA.get(aid)
    if not a: print("∅ Acólito não encontrado."); return
    a["skills"] = set()
    print("🧹 Skills limpas."); a_show(aid)

# =================== Ferramentas de controle manual ===================
def force_assign(event_token, role, aid):
    com, dtm, _ = parse_eventkey(event_token)
    eid = event_id_from(com, dtm)
    if eid not in EVENTS:
        print("∅ Evento não encontrado."); return
    ev = EVENTS[eid]
    if role not in ev.funcs:
        print(f"∅ Função '{role}' não existe neste evento (pack={ev.funcs})."); return
    pairs = dict(ASSIGNMENTS.get(eid, []))
    pairs[role] = aid
    ordered = []
    order = {r:i for i,r in enumerate(ev.funcs)}
    for r in ev.funcs:
        if r in pairs:
            ordered.append((r, pairs[r]))
    ASSIGNMENTS[eid] = ordered
    print("✅ Atribuição aplicada.")

def unassign(event_token, role):
    com, dtm, _ = parse_eventkey(event_token)
    eid = event_id_from(com, dtm)
    if eid not in EVENTS:
        print("∅ Evento não encontrado."); return
    ev = EVENTS[eid]
    pairs = [(r,a) for (r,a) in ASSIGNMENTS.get(eid, []) if r != role]
    ASSIGNMENTS[eid] = pairs
    print("✅ Função limpa.")

def suggest(event_token, role, topn=5):
    com, dtm, _ = parse_eventkey(event_token)
    eid = event_id_from(com, dtm)
    if eid not in EVENTS:
        print("∅ Evento não encontrado."); return
    ev = EVENTS[eid]
    if role not in ev.funcs:
        print(f"∅ Função '{role}' não existe neste evento."); return
    tmp = dict(ASSIGNMENTS)
    chosen = set(a for _, a in tmp.get(eid, []))
    thresh, win_counts = compute_threshold_and_counts(ev.dt, tmp)
    cands = []
    for aid in AC_DATA.keys():
        if aid in chosen: 
            continue
        if candidate_is_eliminated(aid, ev, role, tmp):
            continue
        is_local = (AC_DATA[aid]["home"] == ev.com)
        valid = (win_counts.get(aid, 0) + 1) <= thresh
        sc = score_candidate(aid, ev, role, win_counts, tmp)
        cands.append((is_local, valid, sc, aid))
    # ordena: locais válidos > globais válidos > locais inválidos (menor overflow) > globais inválidos
    def overflow(aid):
        return (win_counts.get(aid, 0) + 1) - thresh
    cands.sort(key=lambda t: (
        -(1 if t[0] and t[1] else 0),
        -(1 if (not t[0]) and t[1] else 0),
        overflow(t[3]),
        -t[2],
        AC_DATA[t[3]]["name"],
        t[3]
    ))
    print_divider()
    print(f"Sugestões para {role} em {fmt_event_line(ev)}")
    print_divider(ch='-')
    shown = 0
    for is_local, valid, sc, aid in cands:
        if shown >= topn: break
        a = AC_DATA[aid]
        tag = "LOCAL" if is_local else "OUTRA"
        ok = "OK" if valid else f"↑{(counts_in_window(ev.dt, FAIR_WINDOW_DAYS).get(aid,0)+1 - compute_threshold_and_counts(ev.dt, tmp)[0]):.1f}"
        qual = "✓" if role in AC_DATA[aid].get("skills", set()) else "✗"  # redundante (já filtrado), mas informativo
        print(f"{shown+1:>2}. #{aid:<2} {a['name']}  [{tag} {ok} qual={qual}]  (home={a['home']}, manhã={'✓' if a['manha'] else ' '})  score={sc:.2f}")
        shown += 1
    if shown == 0:
        print("∅ Sem candidatos sugeridos.")
    print_divider()

# =================== Diagnóstico e Estatísticas ===================
def checks(start_date=None, end_date=None):
    if not (start_date and end_date):
        start_date, end_date = default_period()
    evs = [e for e in EVENTS.values() if start_date <= e.dt.date() <= end_date]
    evs.sort(key=lambda e: e.dt)
    problems = []
    for ev in evs:
        pairs = ASSIGNMENTS.get(ev.id, [])
        roles_present = {r for r,_ in pairs}
        # Funções faltantes
        for r in ev.funcs:
            if r not in roles_present:
                problems.append(("FALTA", ev, f"Sem {r}"))
        # QUALIFICAÇÃO POR FUNÇÃO
        for r, aid in pairs:
            if r not in AC_DATA[aid].get("skills", set()):
                problems.append(("QUAL", ev, f"{r} sem qualificação: #{aid} {AC_DATA[aid]['name']}"))
            # choques / bloqueios já como antes...
            for eid2, pairs2 in ASSIGNMENTS.items():
                if eid2 == ev.id: continue
                if any(a2==aid for _,a2 in pairs2):
                    if abs((EVENTS[eid2].dt - ev.dt).total_seconds()) < NO_OVERLAP_MINUTES*60:
                        problems.append(("CHOQUE", ev, f"#{aid} {AC_DATA[aid]['name']} conflita com {EVENTS[eid2].id}"))
            if is_blocked(aid, ev.dt):
                problems.append(("BLOQ", ev, f"#{aid} {AC_DATA[aid]['name']} em bloqueio"))
    if not problems:
        print("✅ Sem problemas encontrados.")
        return
    problems.sort(key=lambda x: (x[0], x[1].dt))
    print_divider()
    for tag, ev, msg in problems:
        print(f"[{tag}] {fmt_dt(ev.dt)} {ev.com}  → {msg}")
    print_divider()

def gini(values):
    n = len(values)
    if n == 0: return 0.0
    sorted_vals = sorted(values)
    cum = 0
    for i, v in enumerate(sorted_vals, start=1):
        cum += i * v
    total = sum(sorted_vals)
    if total == 0: return 0.0
    return (2 * cum) / (n * total) - (n + 1) / n

def stats(start_date=None, end_date=None):
    if not (start_date and end_date):
        start_date, end_date = default_period()
    assign_incremental()
    relevant_ids = [eid for eid, ev in EVENTS.items() if start_date <= ev.dt.date() <= end_date]
    counts = defaultdict(int)
    for eid in relevant_ids:
        for _, a in ASSIGNMENTS.get(eid, []):
            counts[a] += 1
    vals = [counts.get(aid,0) for aid in AC_DATA.keys()]
    print_divider()
    print(f"Contagem por acólito ({start_date.strftime('%d/%m/%Y')}..{end_date.strftime('%d/%m/%Y')}):")
    print_divider(ch='-')
    for aid in sorted(AC_DATA.keys()):
        print(f"#{aid:<2} {shorten(AC_DATA[aid]['name'],22):<22} → {counts.get(aid,0)}")
    print_divider(ch='-')
    g = gini(vals)
    sd = pstdev(vals) if len(vals) > 1 else 0.0
    print(f"Gini={g:.3f}  |  Desvio-padrão={sd:.2f}  |  Total atribuições={sum(vals)}")
    print_divider()

# =================== Extras de Núcleo ===================
def free_slots(start_date=None, end_date=None):
    """Lista apenas vagas não preenchidas no período."""
    if not (start_date and end_date):
        start_date, end_date = default_period()
    assign_incremental()
    evs = [e for e in EVENTS.values() if start_date <= e.dt.date() <= end_date]
    evs.sort(key=lambda e: (e.dt, e.com))
    count = 0
    for ev in evs:
        assigned = {r for r,_ in ASSIGNMENTS.get(ev.id, [])}
        missing = [r for r in ev.funcs if r not in assigned]
        if missing:
            count += len(missing)
            print(f"• {fmt_event_line(ev)}")
            for r in missing:
                print(f"   - VAGA: {r}")
    if count == 0:
        print("✅ Sem vagas em aberto no período.")

def prune_past(keep_days=0):
    """Remove eventos anteriores a (hoje - keep_days)."""
    cutoff = today_date() - timedelta(days=int(keep_days))
    removed = 0
    for eid, ev in list(EVENTS.items()):
        if ev.dt.date() < cutoff:
            EVENTS.pop(eid, None)
            ASSIGNMENTS.pop(eid, None)
            removed += 1
    # limpa séries vazias
    for sid, arr in list(SERIES_INDEX.items()):
        SERIES_INDEX[sid] = [eid for eid in arr if eid in EVENTS]
        if not SERIES_INDEX[sid]:
            del SERIES_INDEX[sid]
    print(f"🧹 PRUNE: {removed} evento(s) removido(s).")

def clear_assignments_range(start_date, end_date):
    cleared = 0
    for eid, ev in list(EVENTS.items()):
        if start_date <= ev.dt.date() <= end_date:
            if eid in ASSIGNMENTS:
                cleared += 1
                ASSIGNMENTS.pop(eid, None)
    print(f"🧽 Atribuições limpas em {cleared} evento(s).")

# =================== CONFIG ===================
def config_show():
    print_divider()
    print("Configurações atuais:")
    print(f"DEFAULT_RECURRENCE_MONTHS = {DEFAULT_RECURRENCE_MONTHS}")
    print(f"NO_OVERLAP_MINUTES        = {NO_OVERLAP_MINUTES}")
    print(f"NAME_MAX_CHARS            = {NAME_MAX_CHARS}")
    print(f"FAIR_WINDOW_DAYS          = {FAIR_WINDOW_DAYS}")
    print(f"ROLE_ROT_WINDOW_DAYS      = {ROLE_ROT_WINDOW_DAYS}")
    print(f"WORKLOAD_TOLERANCE        = {WORKLOAD_TOLERANCE}")
    print(f"DEFAULT_VIEW_DAYS         = {DEFAULT_VIEW_DAYS}")
    print_divider()

def config_set(kvs):
    global DEFAULT_RECURRENCE_MONTHS, NO_OVERLAP_MINUTES, NAME_MAX_CHARS
    global FAIR_WINDOW_DAYS, ROLE_ROT_WINDOW_DAYS, WORKLOAD_TOLERANCE, DEFAULT_VIEW_DAYS
    for k,v in kvs.items():
        kk = k.lower()
        if kk in ("rec_months","default_recurrence_months"):
            DEFAULT_RECURRENCE_MONTHS = int(v)
        elif kk in ("overlap","no_overlap_minutes"):
            NO_OVERLAP_MINUTES = int(v)
        elif kk in ("name_width","name_max_chars"):
            NAME_MAX_CHARS = int(v)
        elif kk in ("fair_days","fair_window_days"):
            FAIR_WINDOW_DAYS = int(v)
        elif kk in ("role_rot_days","role_rotation_days","role_rot_window_days"):
            ROLE_ROT_WINDOW_DAYS = int(v)
        elif kk in ("workload_tol","workload_tolerance"):
            WORKLOAD_TOLERANCE = int(v)
        elif kk in ("default_view_days","view_days"):
            DEFAULT_VIEW_DAYS = int(v)
        else:
            print(f"Aviso: chave '{k}' desconhecida.")
    config_show()

# =================== HELP ===================
def help_text():
    return (
"""Escala CLI – Ajuda Rápida

CONVENÇÕES
  • Período: YYYY-MM ou DDMM..DDMM (ano atual).
  • EventKey: <COM><DD><MM>[AA|AAAA]<HH><MM>[Q]
    Ex.: MAT0101202519003
  • DOW (dia semana): SEG, TER, QUA, QUI, SEX, SABADO|SA, DOMINGO|DO
  • Funções (roles): LIB, CRU, MIC, TUR, NAV, CER1, CER2, CAM
  • COM: MAT, STM, SJT, SJB, DES, NSL

GERAL
  HELP                         → mostra esta ajuda
  NOW                          → data/hora atuais
  CLEAR | CLS                  → limpa o terminal
  UNDO                         → desfaz o último comando
  EXIT | QUIT                  → sair

EVENTOS
  C <EventKey>                 → cria evento (Q opcional, padrão=2)
  E <EventKeyAntigo> <Novo>    → edita evento (data/hora/COM/Q)
  R <EventKey>                 → remove evento
  R ALL                        → remove TODOS os eventos e séries
  R DAY <DDMMYYYY|YYYY-MM-DD>  → remove todos os eventos desse dia
  SHOW <EventKey>              → mostra detalhes + escala do evento
  L [YYYY-MM|DDMM..DDMM]       → lista eventos (padrão: hoje..fim do mês)

RECORRÊNCIA (CR) E SÉRIES SOLENES
  CR <COM><DOW><HHMM><Q>                     → cria recorrente (por DEFAULT_RECURRENCE_MONTHS)
  CR <COM><DOW><HHMM><Q><INI><FIM>           → cria recorrente no período (INI/FIM = DDMMYY|DDMMYYYY)
  CR CANCELAR <EventKey>                      → cancela uma única data de uma CR
  DR <SERIES_ID|CRcurto>                      → apaga série(s) (use token CR curto para apagar todas do padrão)
  ER <CRcurto> <NOVO_HHMM|Q=nn>               → edita hora ou Q de recorrência(s)
  T  <EventKeyBaseQ>                          → cria Tríduo (3 dias) [SOLENE]
  W7 <EventKeyBaseQ>                          → cria Semana Festiva (7 dias) [SOLENE]
  N9 <EventKeyBaseQ>                          → cria Novena (9 dias) [SOLENE]
  S<L> <EventKeyBaseQ>                        → cria série de L dias [SOLENE]
  ES <SERIES_ID> <NovoBaseQ>                  → rebaseia série para novo horário/quantidade

ESCALA / ATRIBUIÇÕES
  ESCALA [período] [modo=tabela|linhas|csv] [com=A,B] [roles=R1,R2] [namew=N]
  RECALCULAR | RECALC | RE [período]         → recalcula escala do período
  ASSIGN <EventKey> <ROLE> <AID>             → força atribuição
  REPLACE <EventKey> <ROLE> <AID>            → substitui acólito naquela função
  UNASSIGN <EventKey> <ROLE>                 → limpa função
  SWAP <EKey> <R1> WITH <R2>                 → troca funções no mesmo evento
  SWAP <EKey1> <R1> WITH <EKey2> <R2>        → troca entre eventos distintos
  SUG <EventKey> <ROLE> [N=5]                → sugere candidatos
  FREE [período]                              → lista vagas não preenchidas
  CHK [período]                               → checagens (faltas, choques, bloqueios, QUAL)
  STATS [período]                             → estatísticas de carga
  MINHA_ESCALA <AID> [período]               → agenda individual

ACÓLITOS
  A LIST
  A SHOW <id>
  A ADD name=<...> home=<COM> [skills=ALL|R1,R2] [manha=0/1] [ativo=1/0]
  A SET <id> chave=valor ...                  (chaves: name, home, skills, manha, ativo)
  A DEL <id>

  A BLOQ <id> <DDMM..DDMM|YYYY-MM> [HHMM..HHMM] [nota=...]
  A UNBLOQ <id> <idx|all>

  A QUAL LIST <id>
  A QUAL SET <id> <ALL|R1,R2,...>
  A QUAL ADD <id> <R1,R2,...>
  A QUAL DEL <id> <R1,R2,...>
  A QUAL CLEAR <id>

ARQUIVOS
  SAVE <arquivo.json>
  LOAD <arquivo.json>
  EXPORT CSV <arquivo.csv> <período> [com=...] [roles=...]
  EXPORT ICS <arquivo.ics> <período> [com=...]

NOTAS DO ALGORITMO
  • Preferência local é filtro: tenta locais válidos antes de globais.
  • Fairness: candidato é válido se, ao receber +1, não exceder média+tol.
  • Rotatividade: penaliza repetir a mesma função na janela.
  • Regras duras: inativo, bloqueios, choque de horário, e FALTA DE QUALIFICAÇÃO eliminam o candidato.
""").strip()

# =================== CLI ===================
def repl():
    init_acolitos()
    print("Escala CLI v3 – digite HELP para ajuda. CTRL+C para sair.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSaindo."); break
        if not line: continue
        up = line.upper()
        if up in ("EXIT","QUIT"):
            print("Tchau!"); break
        try:
            toks = line.split()
            cmd = toks[0].upper()

            # Auxiliares
            if cmd in ("CLEAR","CLS"):
                os.system('cls' if os.name == 'nt' else 'clear'); continue
            if cmd == "NOW":
                print(now_dt().strftime("%Y-%m-%d %H:%M:%S")); continue

            # Ajuda
            if cmd == "HELP":
                print(help_text()); continue

            # UNDO
            if cmd == "UNDO":
                undo_last(); continue

            # ----------------- Comandos de Eventos -----------------
            if cmd == "C" and len(toks)==2:
                push_history("C")
                com, dtm, qty = parse_eventkey(toks[1])
                if qty is None: qty = 2
                ev = Event(com, dtm, qty, kind="REG")
                upsert_event(ev); assign_incremental()
                print("✅ Criado:", fmt_event_line(ev)); continue

            if cmd == "E" and len(toks)==3:
                push_history("E")
                new_id = edit_event(toks[1], toks[2]); assign_incremental()
                print("✏️  Editado:", fmt_event_line(EVENTS[new_id])); continue

            if cmd == "R" and len(toks)==2:
                if toks[1].upper() in ("ALL","TODOS","*"):
                    push_history("R ALL")
                    EVENTS.clear(); ASSIGNMENTS.clear(); SERIES_INDEX.clear()
                    print("🗑️  Todos os eventos foram removidos."); continue
                ok = remove_event_by_key(toks[1])
                if ok: push_history(f"R {toks[1]}")
                print("🗑️  Removido." if ok else "∅ Evento não encontrado."); continue

            if cmd == "R" and len(toks)==3 and toks[1].upper()=="DAY":
                try:
                    d = parse_single_date(toks[2]); remove_events_on_day(d); continue
                except Exception as e:
                    print("Erro:", e); continue

            if cmd == "T" and len(toks)==2:
                push_history("T")
                sid, ids = create_series("T", toks[1], 3, kind="SOLENE"); assign_incremental()
                print(f"✅ Tríduo criado ({sid}) com {len(ids)} celebrações."); continue

            if cmd == "W7" and len(toks)==2:
                push_history("W7")
                sid, ids = create_series("W7", toks[1], 7, kind="SOLENE"); assign_incremental()
                print(f"✅ Semana Festiva criada ({sid}) com {len(ids)} celebrações."); continue

            if cmd == "N9" and len(toks)==2:
                push_history("N9")
                sid, ids = create_series("N9", toks[1], 9, kind="SOLENE"); assign_incremental()
                print(f"✅ Novena criada ({sid}) com {len(ids)} celebrações."); continue

            if cmd.startswith("S") and cmd not in ("SHOW", "SAVE", "SUG", "STATS") and len(toks)==2:
                try: L = int(cmd[1:])
                except: raise ValueError("Use S<L> com L numérico, ex.: S8 ...")
                push_history(f"S{L}")
                sid, ids = create_series(cmd, toks[1], L, kind="SOLENE"); assign_incremental()
                print(f"✅ Série {cmd} criada ({sid}) com {len(ids)} celebrações."); continue

            if cmd == "ES":
                if len(toks) < 3: raise ValueError("Uso: ES <SERIES_ID> <EventKey_BASE_NOVO> [scope=all]")
                push_history("ES")
                sid = toks[1]; base_new = toks[2]
                if sid not in SERIES_INDEX: raise ValueError("Série não encontrada.")
                comN, dtN, qN = parse_eventkey(base_new)
                if qN is None: raise ValueError("Forneça Q no EventKey novo para série.")
                changed = 0
                for eid in sorted(SERIES_INDEX[sid], key=lambda x: EVENTS[x].dt):
                    ev = EVENTS[eid]
                    new_dt = datetime(ev.dt.year, ev.dt.month, ev.dt.day, dtN.hour, dtN.minute)
                    tok_old = f"{ev.com}{ev.dt.strftime('%d%m%Y%H%M')}"
                    tok_new = f"{comN}{new_dt.strftime('%d%m%Y%H%M')}{qN}"
                    edit_event(tok_old, tok_new)
                    changed += 1
                assign_incremental()
                print(f"✏️  Série {sid} atualizada ({changed} celebrações)."); continue

            if cmd == "CR" and len(toks)==3 and toks[1].upper()=="CANCELAR":
                cr_cancelar_unica_data(toks[2]); continue

            if cmd == "CR" and len(toks)==2:
                push_history("CR")
                sid, count = create_recurring(toks[1]); assign_incremental()
                print(f"✅ Recorrente criada ({sid}) gerou {count} celebrações."); continue

            if cmd == "DR" and len(toks)==2:
                push_history("DR")
                sid = toks[1]
                if sid in SERIES_INDEX:
                    for eid in SERIES_INDEX[sid]:
                        EVENTS.pop(eid, None); ASSIGNMENTS.pop(eid, None)
                    del SERIES_INDEX[sid]
                    print("🗑️  Série removida."); continue
                try:
                    m = REC_SHORT_RE.match(sid)
                    if not m: raise ValueError()
                    com = normalize_com(m.group("com"))
                    dow_canon, _ = dow_to_int(m.group("dow"))
                    hh = int(m.group("hh")); mi = int(m.group("mi"))
                    q  = norm_q(m.group("q"))
                    killed = 0
                    for k in list(SERIES_INDEX.keys()):
                        if k.startswith(f"CR-{com}{dow_canon}{hh:02d}{mi:02d}Q{q}-"):
                            for eid in SERIES_INDEX[k]:
                                EVENTS.pop(eid, None); ASSIGNMENTS.pop(eid, None)
                            del SERIES_INDEX[k]
                            killed += 1
                    print("🗑️  Série(s) removida(s)." if killed else "∅ Série não encontrada.")
                    continue
                except:
                    print("∅ Série não encontrada."); continue

            if cmd == "ER" and len(toks)==3:
                push_history("ER")
                src = toks[1]; change = toks[2]
                m = REC_SHORT_RE.match(src)
                if not m: raise ValueError("Uso: ER <COM><DOW><HHMM><Q> <NOVO_HHMM|Q=nn>")
                com = normalize_com(m.group("com"))
                dow_canon, _ = dow_to_int(m.group("dow"))
                hh = int(m.group("hh")); mi = int(m.group("mi")); q = norm_q(m.group("q"))
                targets = [k for k in SERIES_INDEX.keys() if k.startswith(f"CR-{com}{dow_canon}{hh:02d}{mi:02d}Q{q}-")]
                if not targets: print("∅ Série não encontrada."); continue
                new_hh, new_mi, new_q = hh, mi, q
                if change.isdigit() and len(change) == 4:
                    new_hh, new_mi = int(change[:2]), int(change[2:])
                elif change.upper().startswith("Q="):
                    new_q = norm_q(change.split("=")[1])
                changed = 0
                for sid in list(targets):
                    period = sid.split("Q")[1].split("-", 1)[1]  # ex.: 01012025..31032025
                    start_s, end_s = period.split("..")
                    for eid in SERIES_INDEX[sid]:
                        EVENTS.pop(eid, None); ASSIGNMENTS.pop(eid, None)
                    del SERIES_INDEX[sid]
                    token_full = f"{com}{dow_canon}{new_hh:02d}{new_mi:02d}{new_q}{start_s}{end_s}"
                    new_sid, _ = create_recurring(token_full)
                    changed += 1
                assign_incremental()
                print(f"✏️  Recorrente(s) atualizada(s): {changed}."); continue

            if cmd == "L":
                if len(toks)==1:
                    list_next_month_from_today(); continue
                try: start, end = parse_range_token(toks[1]); list_range(start, end); continue
                except Exception as e: print("Erro:", e); continue

            if cmd == "ESCALA":
                assign_incremental()
                # parâmetros opcionais: modo= (tabela|linhas|csv), com=MAT,STM, roles=LIB,CRU, namew=18
                start, end = None, None
                idx = 1
                if len(toks) >= 2 and not toks[1].lower().startswith(("modo=","com=","roles=","namew=")):
                    try:
                        start, end = parse_range_token(toks[1]); idx = 2
                    except Exception:
                        pass
                if start is None or end is None:
                    start, end = default_period()

                modo = "tabela"
                com_filter = None
                roles_filter = None
                namew = NAME_MAX_CHARS
                for t in toks[idx:]:
                    if t.lower().startswith("modo="):
                        modo = t.split("=",1)[1].lower()
                    elif t.lower().startswith("com="):
                        com_filter = [normalize_com(c.strip()) for c in t.split("=",1)[1].split(",") if c.strip()]
                    elif t.lower().startswith("roles="):
                        roles_filter = [r.strip().upper() for r in t.split("=",1)[1].split(",") if r.strip()]
                    elif t.lower().startswith("namew="):
                        try: namew = int(t.split("=",1)[1])
                        except: pass

                if modo == "linhas":
                    list_assignments_lines(start, end, com_filter)
                elif modo == "csv":
                    list_assignments_csv(start, end, com_filter, roles_filter)
                else:
                    list_assignments_table(start, end, com_filter, roles_filter, namew)
                continue

            if cmd in ("RECALCULAR","RECALC","RE"):
                push_history("RECALC")
                if len(toks) == 1:
                    start, end = default_period()
                    recalc_global(start, end)
                    print(f"🔁 Escala recalculada para {start.strftime('%d/%m/%Y')}..{end.strftime('%d/%m/%Y')}."); continue
                try:
                    start, end = parse_range_token(toks[1])
                    recalc_global(start, end)
                    print(f"🔁 Escala recalculada para {start.strftime('%d/%m/%Y')}..{end.strftime('%d/%m/%Y')}.")
                    continue
                except Exception as e:
                    print("Erro:", e); continue

            if cmd == "SHOW" and len(toks)==2:
                com, dtm, _ = parse_eventkey(toks[1])
                ev_id = event_id_from(com, dtm)
                if ev_id in EVENTS:
                    ev = EVENTS[ev_id]
                    print(fmt_event_line(ev)); print(fmt_assignment(ev))
                else: print("∅ Evento não encontrado."); continue

            # ----------------- Gestão Acolitos -----------------
            if cmd in ("A","AC"):
                if len(toks) == 1 or toks[1].upper() == "LIST":
                    a_list(); continue
                sub = toks[1].upper()
                if sub == "SHOW" and len(toks)>=3:
                    a_show(int(toks[2])); continue
                if sub == "ADD":
                    push_history("A ADD")
                    kvs = {}
                    for kv in toks[2:]:
                        if "=" in kv:
                            k,v = kv.split("=",1)
                            kvs[k]=v
                    a_add(kvs); continue
                if sub == "DEL" and len(toks)>=3:
                    push_history("A DEL")
                    a_del(int(toks[2])); continue
                if sub == "SET" and len(toks)>=4:
                    push_history("A SET")
                    aid = int(toks[2])
                    kvs = {}
                    for kv in toks[3:]:
                        if "=" in kv:
                            k,v = kv.split("=",1)
                            kvs[k]=v
                    a_set(aid, kvs); continue
                if sub == "BLOQ" and len(toks)>=4:
                    push_history("A BLOQ")
                    aid = int(toks[2])
                    date_tok = toks[3]
                    time_tok = None
                    note = None
                    for x in toks[4:]:
                        if ".." in x and len(x)==9 and x.replace(".","").isdigit(): time_tok = x
                        elif x.lower().startswith("nota="): note = x.split("=",1)[1]
                    a_bloq(aid, date_tok, time_tok, note); continue
                if sub == "UNBLOQ" and len(toks)>=4:
                    push_history("A UNBLOQ")
                    aid = int(toks[2]); idx_tok = toks[3]
                    a_unbloq(aid, idx_tok); continue
                if sub == "QUAL":
                    if len(toks) < 3:
                        print("Uso: A QUAL LIST <id> | A QUAL SET <id> <ALL|roles> | A QUAL ADD <id> <roles> | A QUAL DEL <id> <roles> | A QUAL CLEAR <id>")
                        continue
                    action = toks[2].upper()
                    if action == "LIST" and len(toks)>=4:
                        a_skill_list(int(toks[3])); continue
                    if action == "SET" and len(toks)>=5:
                        aid = int(toks[3]); roles = parse_roles_arg(" ".join(toks[4:]))
                        a_skill_set(aid, roles); continue
                    if action == "ADD" and len(toks)>=5:
                        aid = int(toks[3]); roles = parse_roles_arg(" ".join(toks[4:]))
                        a_skill_add(aid, roles); continue
                    if action == "DEL" and len(toks)>=5:
                        aid = int(toks[3]); roles = parse_roles_arg(" ".join(toks[4:]))
                        a_skill_del(aid, roles); continue
                    if action == "CLEAR" and len(toks)>=4:
                        a_skill_clear(int(toks[3])); continue
                    print("Uso: A QUAL LIST <id> | A QUAL SET <id> <ALL|roles> | A QUAL ADD <id> <roles> | A QUAL DEL <id> <roles> | A QUAL CLEAR <id>")
                    continue
                print("Uso: A LIST | A SHOW <id> | A ADD name=<...> home=<COM> [skills=ALL|R1,R2] [manha=0/1] [ativo=1/0] | A SET <id> k=v ... | A BLOQ <id> <DDMM..DDMM|YYYY-MM> [HHMM..HHMM] [nota=...] | A UNBLOQ <id> <idx|all> | A DEL <id>")
                continue

            # ----------------- Save/Load/Export -----------------
            if cmd == "SAVE" and len(toks)==2:
                path = toks[1]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(to_json(), f, ensure_ascii=False, indent=2)
                print(f"💾 Salvo em {path}")
                continue

            if cmd == "LOAD" and len(toks)==2:
                path = toks[1]
                if not os.path.exists(path):
                    print("∅ Arquivo não encontrado."); continue
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                from_json(data)
                print(f"📂 Carregado de {path}")
                continue

            if cmd == "EXPORT" and len(toks)>=4:
                kind = toks[1].upper()
                path = toks[2]
                start, end = parse_range_token(toks[3])
                com_filter = None; roles_filter=None
                for t in toks[4:]:
                    if t.lower().startswith("com="):
                        com_filter = [normalize_com(c.strip()) for c in t.split("=",1)[1].split(",") if c.strip()]
                    if t.lower().startswith("roles="):
                        roles_filter = [r.strip().upper() for r in t.split("=",1)[1].split(",") if r.strip()]
                if kind == "CSV":
                    export_csv(path, start, end, com_filter, roles_filter)
                elif kind == "ICS":
                    export_ics(path, start, end, com_filter)
                else:
                    print("Tipos suportados: EXPORT CSV|ICS <arquivo> <período> [com=...] [roles=...]")
                continue

            # ----------------- Controle, Diagnóstico e Extras -----------------
            if cmd == "ASSIGN" and len(toks)==4:
                push_history("ASSIGN")
                force_assign(toks[1], toks[2].upper(), int(toks[3])); continue

            if cmd == "REPLACE" and len(toks)==4:
                push_history(f"REPLACE {toks[1]} {toks[2]}")
                force_assign(toks[1], toks[2].upper(), int(toks[3])); continue

            if cmd == "UNASSIGN" and len(toks)==3:
                push_history("UNASSIGN")
                unassign(toks[1], toks[2].upper()); continue

            if cmd == "RESETASSIGN" and len(toks)==2:
                push_history("RESETASSIGN")
                start,end = parse_range_token(toks[1]); clear_assignments_range(start, end); continue

            if cmd == "SWAP":
                # Formatos:
                # 1) SWAP <EKey> <R1> WITH <R2>
                # 2) SWAP <EKey1> <R1> WITH <EKey2> <R2>
                if len(toks) in (5,6) and toks[3].upper()=="WITH":
                    if len(toks)==5:
                        ekey = toks[1]; r1 = toks[2]; r2 = toks[4]
                        # reusa swap passando o mesmo evento nos dois lados
                        swap_roles(ekey, r1, ekey, r2); continue
                    else:
                        e1, r1, e2, r2 = toks[1], toks[2], toks[4], toks[5]
                        swap_roles(e1, r1, e2, r2); continue
                print("Uso: SWAP <EKey> <R1> WITH <R2>  |  SWAP <EKey1> <R1> WITH <EKey2> <R2>")
                continue

            if cmd == "MINHA_ESCALA":
                if len(toks) < 2: 
                    print("Uso: MINHA_ESCALA <AID> [YYYY-MM|DDMM..DDMM]"); continue
                aid = int(toks[1])
                if len(toks) >= 3:
                    try: start, end = parse_range_token(toks[2])
                    except Exception as e: print("Erro:", e); continue
                    minha_escala(aid, start, end); continue
                minha_escala(aid); continue

            if cmd == "SUG":
                if len(toks) < 3: print("Uso: SUG <EventKey> <ROLE> [N]"); continue
                topn = int(toks[3]) if len(toks)>=4 and toks[3].isdigit() else 5
                suggest(toks[1], toks[2].upper(), topn); continue

            if cmd == "FREE":
                if len(toks)==1:
                    free_slots()
                else:
                    try:
                        start, end = parse_range_token(toks[1]); free_slots(start, end)
                    except Exception as e:
                        print("Erro:", e)
                continue

            if cmd == "CHK":
                if len(toks)==1:
                    checks()
                else:
                    try:
                        start, end = parse_range_token(toks[1]); checks(start, end)
                    except Exception as e:
                        print("Erro:", e)
                continue

            if cmd == "STATS":
                if len(toks)==1:
                    stats()
                else:
                    try:
                        start, end = parse_range_token(toks[1]); stats(start, end)
                    except Exception as e:
                        print("Erro:", e)
                continue

            if cmd == "PRUNE":
                keep = 0
                if len(toks)>=2 and toks[1].isdigit():
                    keep = int(toks[1])
                prune_past(keep_days=keep); continue

            if cmd == "CONFIG":
                if len(toks)==1 or toks[1].upper()=="SHOW":
                    config_show(); continue
                if toks[1].upper()=="SET":
                    kvs={}
                    for kv in toks[2:]:
                        if "=" in kv:
                            k,v = kv.split("=",1)
                            kvs[k]=v
                    config_set(kvs); continue

            print("Comando não reconhecido. Digite HELP.")
        except Exception as e:
            print("Erro:", e)

# =================== Main ===================
if __name__ == "__main__":
    repl()
