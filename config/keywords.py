"""
분야별 키워드 — 의미 버킷 + 버킷별 상한 구조.

구조: KEYWORDS[분야][버킷] = {"cap": 상한, "strong":{...}, "medium":{...}, "weak":{...}}
점수 = 버킷별 Σ(tier가중치 × 위치가중치) 를 cap으로 자른 뒤 버킷 합 + 음수(하한 NEG_FLOOR).
의도: 한 버킷(예: 회사명) 도배로 점수 폭주하는 걸 막고, 여러 차원을 건드린 기사를 우대.
등장 여부만 카운트 (중복 카운트 X, 위치별 1회). 별칭은 ALIASES로 1회 접음.

버킷:
- entity  : 누가 (기업·주체).        cap 낮음 → 회사명 나열로 점수 못 끔
- product : 무엇을 (상품).
- tech    : 어떻게 (기술·공정).      cap 가장 높음 → 기술 기사가 단독 상위 가능
- event   : 무슨 일 (사건·액션).
- domain  : 분야 일반 (배경어).      cap 가장 낮음 → 변별력 없는 배경어 바닥값만
- negative: 감점 (버킷 밖, 상한 미적용·하한만)
"""

KEYWORDS = {
    "반도체": {
        # ── 기업·주체 ──────────────────────────────────────────
        "entity": {
            "cap": 5,
            "strong": {  # +3
                "TSMC",
                "하이닉스", "하닉", "hynix",  # SK하이닉스/SK 하이닉스/하이닉스/하닉 커버
                "마이크론", "Micron", "ASML",
                "엔비디아", "Nvidia",
                # 장비/메모리 제조사 (반도체 전업). 별칭 1회 카운트.
                "어플라이드", "Applied Materials", "AMAT",
                "램리서치", "Lam Research",
                "도쿄일렉트론", "Tokyo Electron",
                "키옥시아", "Kioxia",
            },
            "medium": {  # +2
                "삼성전자", "삼전", "삼성", "Samsung",  # DX부문(폰/가전)은 negative로 상쇄
                "인텔 파운드리", "한미반도체",
            },
            "weak": {  # +1
                "인텔", "Intel", "AMD", "퀄컴", "Qualcomm", "브로드컴", "Broadcom",
            },
        },
        # ── 제품 ───────────────────────────────────────────────
        "product": {
            "cap": 7,
            "strong": {  # +3
                "HBM", "HBM4", "HBM3E", "HBM4E", "high bandwidth memory",
                "DRAM", "D램", "디램",  # 국문 'D램'/'디램' 보강 (기존엔 영문 DRAM만 있었음)
                "NAND", "낸드",
                "AI 반도체", "AI반도체", "AI chip", "AI accelerator", "시스템반도체",
                "1a", "1b", "1c", "1d",  # DRAM 노드 세대
                "DDR5", "LPDDR", "GDDR",
            },
            "medium": {  # +2
                "메모리", "고대역폭", "DDR6",  # DDR6만 신규 (LPDDR/GDDR가 6/7세대 접미사 이미 잡음)
            },
            "weak": set(),
        },
        # ── 기술·공정 ──────────────────────────────────────────
        "tech": {
            "cap": 10,
            "strong": {  # +3
                "EUV",
                # HBM 적층 핵심 공정
                "MR-MUF", "매스리플로우",
                "하이브리드본딩", "하이브리드 본딩", "hybrid bonding",
                # 차세대 메모리 (주류)
                "CXL", "PIM", "프로세싱인메모리",
            },
            "medium": {  # +2
                # 공정 일반 (특정 기술)
                "노광", "식각", "증착", "패키징", "packaging", "advanced packaging",
                "포토레지스트", "photoresist", "소부장",
                "2나노", "3나노", "2nm", "3nm", "GAA", "CoWoS",
                "칩렛", "chiplet", "chiplets",
                "첨단공정", "7세대", "검사장비", "후공정", "전공정", "backend",
                "TSV", "본딩", "적층",
                "lithography", "etching", "deposition", "node", "yield",
                # 메모리 적층 구조/공정 (신규)
                "베이스다이", "베이스 다이", "코어다이", "코어 다이", "버퍼다이", "버퍼 다이",
                "웨이퍼본딩", "백그라인딩",
                # DRAM 미세화 (신규)
                "4F2", "10나노급", "수직 D램", "수직D램",
                # NAND 적층 (신규)
                "200단", "300단", "400단", "더블스택", "트리플스택", "셀온페리", "채널홀",
                "QLC", "TLC",
                # 차세대/뉴메모리 (신규)
                "MRAM", "PCRAM", "ReRAM", "FeRAM", "강유전체", "뉴로모픽",
                # HBM 단수 (신규). ⚠ 뒤가 한글이라 '12단계' 등 오매칭 가능 — bucket_hits 모니터링
                "12단", "16단", "20단",
                # 신소재/차세대 (신규, 변별력 높은 고유어만)
                "2D 반도체", "2D반도체",
                # 영문 보강 (SemiEngineering·TrendForce 발굴, 함정문장 오매칭 검증 완료)
                # 노드 약칭 N2/N3/N5/N7·18A는 'Route N3'/'page 18A'/'train N700' 오매칭으로 제외 (2nm/3nm가 커버)
                "co-packaged optics", "UCIe", "interposer", "microbump", "2.5D", "3D IC",
                "high-NA", "metrology", "defect inspection",
                "backside power", "BSPDN", "nanosheet", "CFET", "sub-2nm",
                "GaN", "SiC", "compound semiconductor", "base die",
            },
            "weak": set(),
        },
        # ── 사건·액션 ──────────────────────────────────────────
        "event": {
            "cap": 5,
            "strong": set(),
            "medium": {  # +2
                "양산", "수주", "증설", "투자", "인수",
                "수출규제", "export control", "보조금", "subsidy",
                "칩스법", "CHIPS Act",
                # 영문 보강 (구 단위로만 — 일반어 order/investment 단독은 제외)
                "volume production", "mass production", "capex", "capacity expansion",
            },
            "weak": set(),
        },
        # ── 분야 일반 (배경어) ─────────────────────────────────
        "domain": {
            "cap": 2,
            "strong": set(),
            "medium": {  # +2
                "파운드리", "foundry",
            },
            "weak": {  # +1
                "반도체", "semiconductor", "팹", "fab", "웨이퍼", "wafer", "공정",
            },
        },
        # ── 감점 (버킷 밖) ─────────────────────────────────────
        "negative": {
            "neg_strong": {  # -3
                "코인", "종목추천", "테마주", "연예", "스포츠",
            },
            "neg_weak": {  # -2
                "단순주가", "시황",
                "ETF", "레버리지", "급등", "급락", "상한가",
                # 삼성 DX부문(폰/가전/모바일) — 반도체(DS) 아닌 소비자 기사 상쇄
                "갤럭시", "비스포크", "폴더블", "가전", "에어컨", "세탁기", "냉장고",
                "스마트폰", "워치", "버즈", "DX부문", "MX사업부", "무선사업부",
                "생활가전", "모바일경험",
            },
        },
    },
}


# 가중치 매핑
WEIGHTS = {
    "strong": 3,
    "medium": 2,
    "weak": 1,
    "neg_strong": -3,
    "neg_weak": -2,
}


# 버킷별 상한 (KEYWORDS 각 버킷의 "cap" 키가 우선. 누락 시 폴백/참고용)
BUCKET_CAPS = {
    "entity": 5,
    "product": 7,
    "tech": 10,
    "event": 5,
    "domain": 2,
}


# 별칭 그룹: 같은 엔티티는 점수 1회만 가산 (제목/summary 위치별 각 1회).
# 본문(body)은 파이썬 점수에 안 쓰임 — 제목+summary만 채점.
# filter.score_item이 이 맵으로 별칭을 대표값으로 접어 중복 카운트를 막는다.
# 같은 버킷 안에서 strong이 medium보다 먼저 순회되므로,
# {본딩(medium), 하이브리드본딩(strong)} 묶음은 "하이브리드본딩" 언급 시 +3,
# 일반 "본딩"만 있으면 +2로 자동 분리된다.
ALIASES = {
    "하이닉스": {"하이닉스", "하닉", "hynix"},  # 'hynix'가 'SK hynix'도 잡음
    "삼성전자": {"삼성전자", "삼전", "삼성", "Samsung"},
    "인텔": {"인텔", "Intel"},
    "퀄컴": {"퀄컴", "Qualcomm"},
    "브로드컴": {"브로드컴", "Broadcom"},
    # AI 반도체: 띄움/붙임/영문 동일 엔티티 1회.
    "AI반도체": {"AI 반도체", "AI반도체", "AI chip", "AI accelerator"},
    # HBM 세대 + 정식명칭(high bandwidth memory)을 한 엔티티로.
    "HBM": {"HBM", "HBM4", "HBM3E", "HBM4E", "high bandwidth memory"},
    # 장비/메모리 제조사 (국문/영문/티커 1회).
    "어플라이드": {"어플라이드", "Applied Materials", "AMAT"},
    "램리서치": {"램리서치", "Lam Research"},
    "도쿄일렉트론": {"도쿄일렉트론", "Tokyo Electron"},
    "키옥시아": {"키옥시아", "Kioxia"},
    # ── 신규 ──
    "DRAM": {"DRAM", "D램", "디램"},
    "하이브리드본딩": {"본딩", "하이브리드본딩", "하이브리드 본딩", "hybrid bonding"},
    "PIM": {"PIM", "프로세싱인메모리"},
    "베이스다이": {"베이스다이", "베이스 다이", "base die"},
    "코어다이": {"코어다이", "코어 다이"},
    "버퍼다이": {"버퍼다이", "버퍼 다이"},
    "수직D램": {"수직D램", "수직 D램"},
    "2D반도체": {"2D 반도체", "2D반도체"},
    # 사건어 영문 (구 단위) — 같은 사건 1회.
    "양산": {"양산", "mass production", "volume production"},
    "증설": {"증설", "capacity expansion"},
}
