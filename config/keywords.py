"""
분야별 키워드 가중치.
등장 여부만 카운트 (중복 카운트 X).
"""

KEYWORDS = {
    "반도체": {
        "strong": {  # +3점
            "HBM", "DRAM", "NAND", "낸드",
            "파운드리", "EUV", "TSMC",
            "하이닉스", "하닉", "마이크론", "ASML",  # '하이닉스/하닉'=SK하이닉스/SK 하이닉스/하이닉스/하닉 커버
            "엔비디아", "AI 반도체", "AI반도체", "시스템반도체",
            "1c", "1b", "DDR5", "LPDDR", "GDDR",  # 메모리 강화
            # 영문 보강 (해외 매체용). ASCII 경계+대소문자 무시 매칭이라 안전.
            "HBM4", "HBM3E", "HBM4E",
            "hynix", "Micron", "Nvidia", "foundry",
            "AI chip", "AI accelerator",
            # 장비/메모리 제조사 (반도체 전업 → strong). 별칭은 ALIASES로 1회 카운트.
            "어플라이드", "램리서치", "도쿄일렉트론", "키옥시아",
            "Applied Materials", "AMAT", "Lam Research", "Tokyo Electron", "Kioxia",
        },
        "medium": {  # +2점
            "메모리", "웨이퍼", "팹", "공정",
            "노광", "식각", "증착", "패키징",
            "포토레지스트", "소부장",
            "인텔 파운드리",
            "삼성전자", "삼전", "삼성",  # 삼성 엔티티(weak→medium 올림). 별칭 1회 카운트.
                                        # DX부문(폰/가전) 키워드를 negative로 둬 비반도체 기사 상쇄.
            "2나노", "3나노", "GAA", "CoWoS", "칩렛",
            "첨단공정", "7세대",
            "양산", "검사장비", "후공정", "전공정",
            "한미반도체", "TSV", "본딩",  # 메모리/패키징 강화
            "고대역폭", "적층",
            # 영문 보강 (공정/패키징/계측). 단어경계로 fabric/sketch 등 오매칭 차단.
            "wafer", "fab", "lithography", "etching", "deposition",
            "packaging", "advanced packaging", "photoresist",
            "chiplet", "chiplets", "yield", "hybrid bonding",
            "node", "2nm", "3nm", "backend",
        },
        "weak": {  # +1점
            "반도체", "보조금", "칩스법", "CHIPS Act",
            "수출규제",
            "인텔", "AMD", "퀄컴", "브로드컴",
            # 영문 보강
            "semiconductor", "export control", "subsidy",
        },
        "negative_strong": {  # -3점
            "코인", "종목추천", "테마주", "연예", "스포츠",
        },
        "negative_weak": {  # -2점
            "단순주가", "시황",
            "ETF", "레버리지", "급등", "급락", "상한가",
            # 삼성 DX부문(폰/가전/모바일) — 반도체(DS) 아닌 소비자 기사 상쇄.
            # 삼성 medium(+3)을 한 개로 상쇄(-2 → 순 +1 < 임계4). 반도체 키워드 동반 시만 통과.
            "갤럭시", "비스포크", "폴더블", "가전", "에어컨", "세탁기", "냉장고",
            "스마트폰", "워치", "버즈", "DX부문", "MX사업부", "무선사업부",
            "생활가전", "모바일경험",
        },
    },
}


# 가중치 매핑
WEIGHTS = {
    "strong": 3,
    "medium": 2,
    "weak": 1,
    "negative_strong": -3,
    "negative_weak": -2,
}


# 별칭 그룹: 같은 엔티티는 점수 1회만 가산 (제목/summary 위치별 각 1회).
# 본문(body)은 파이썬 점수에 안 쓰임 — 제목+summary만 채점.
# filter.score_item이 이 맵으로 별칭을 대표값으로 접어 중복 카운트를 막는다.
ALIASES = {
    "하이닉스": {"하이닉스", "하닉", "hynix"},
    "삼성전자": {"삼성전자", "삼전", "삼성"},
    # AI 반도체: 띄움/붙임/영문 동일 엔티티 1회.
    "AI반도체": {"AI 반도체", "AI반도체", "AI chip", "AI accelerator"},
    # HBM 세대: HBM/HBM4/HBM3E/HBM4E를 한 엔티티로 (세대 동시언급 시 1회만).
    "HBM": {"HBM", "HBM4", "HBM3E", "HBM4E"},
    # 장비/메모리 제조사 (국문/영문/티커 1회).
    "어플라이드": {"어플라이드", "Applied Materials", "AMAT"},
    "램리서치": {"램리서치", "Lam Research"},
    "도쿄일렉트론": {"도쿄일렉트론", "Tokyo Electron"},
    "키옥시아": {"키옥시아", "Kioxia"},
}