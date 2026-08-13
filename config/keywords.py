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
                # 삼성 strong 승격 (6/25) — 메모리/파운드리 핵심 주체. DX부문(폰/가전)은 negative로 상쇄.
                "삼성전자", "삼전", "삼성", "Samsung",
                # 메모리/파운드리/장비/소재 추가 (6/25)
                "난야", "Nanya", "윈본드", "Winbond",
                "솔리다임", "Solidigm", "웨스턴디지털", "Western Digital", "샌디스크", "SanDisk",
                "글로벌파운드리", "GlobalFoundries", "UMC", "SMIC", "라피더스", "Rapidus",
                "KLA", "어드밴테스트", "Advantest", "신에츠", "Shin-Etsu", "섬코", "SUMCO",
            },
            "medium": {  # +2
                "인텔 파운드리", "삼성파운드리", "한미반도체",
                # 국내외 소부장·장비·소재 (6/25)
                "동진쎄미켐", "솔브레인", "원익IPS", "주성엔지니어링", "피에스케이",
                "이오테크닉스", "HPSP", "SK실트론", "케이씨텍", "네패스", "하나마이크론",
                "넥스틴", "파크시스템스", "에스앤에스텍", "JSR", "도쿄오카",
                "퓨리오사", "FuriosaAI", "Furiosa",  # 국내 AI반도체 팹리스 (P3, 8/13)
            },
            "weak": {  # +1
                "인텔", "Intel", "AMD", "퀄컴", "Qualcomm", "브로드컴", "Broadcom",
                "미디어텍", "MediaTek", "마벨", "Marvell", "Arm",
                "시높시스", "Synopsys", "케이던스", "Cadence",
            },
        },
        # ── 제품 ───────────────────────────────────────────────
        "product": {
            "cap": 5,
            "strong": {  # +3
                "HBM", "HBM4", "HBM3E", "HBM4E", "high bandwidth memory",
                "DRAM", "D램", "디램",  # 국문 'D램'/'디램' 보강 (기존엔 영문 DRAM만 있었음)
                "NAND", "낸드",
                "AI 반도체", "AI반도체", "AI chip", "AI accelerator", "시스템반도체",
                "DDR5", "LPDDR", "GDDR",  # ※ DRAM 세대(1a~1d)는 tech critical로 이동(채널 스케일링)
            },
            "medium": {  # +2
                "메모리", "고대역폭", "DDR6",  # DDR6만 신규 (LPDDR/GDDR가 6/7세대 접미사 이미 잡음)
                "ASIC",  # 맞춤형 반도체 (P3, 8/13)
            },
            "weak": set(),
        },
        # ── 기술·공정 ──────────────────────────────────────────
        "tech": {
            "cap": 10,
            "critical": {  # +5 — 차세대 DRAM/NAND/HBM 공정 + 노드. 로직 트랜지스터는 strong.
                # 메모리 노광 (EUV DRAM 등)
                "EUV", "high-NA",
                # 노드(채널 길이) — ALIASES '노드'로 묶어 여러 개 나와도 1회 카운트
                "3나노", "3nm", "2나노", "2nm", "1.4나노", "1.4nm",
                "1나노", "1nm", "0.7나노", "0.7nm", "sub-2nm", "옹스트롬", "angstrom",
                # DRAM 세대 — filter._kw_pattern이 뒤 컨텍스트(나노/nm/D램)를 요구해 '1 billion' 등 오매칭 차단
                "1a", "1b", "1c", "1d",
                # DRAM 구조·미세화
                "4F2", "수직D램", "수직 D램", "3D DRAM", "3D D램",
                "BCAT", "VCAT", "VCT", "새들핀", "saddle-fin", "saddle fin",
                "매립게이트", "buried word line", "buried gate", "RCAT",
                "IGZO", "캐패시터리스", "capacitorless",
                # DRAM 커패시터 미세화 — 셀 커패시턴스 타깃 (8/13)
                "25fF", "10fF", "5fF", "4fF",
                # NAND 적층 단수 (촘촘)
                "128단", "176단", "200단", "232단", "236단", "238단", "280단",
                "300단", "321단", "400단", "430단", "1000단",
                "더블스택", "트리플스택", "셀온페리", "채널홀",
                # HBM 적층 단수
                "8단", "12단", "16단", "20단", "24단",
                "8-Hi", "12-Hi", "16-Hi", "20-Hi", "24-Hi",
                # 차세대 메모리
                "CXL", "PIM", "프로세싱인메모리",
                "MRAM", "PCRAM", "ReRAM", "FeRAM", "강유전체", "뉴로모픽",
                "STT-MRAM", "SOT-MRAM", "FeFET", "셀렉터", "selector",  # (8/13)
                # 차세대 소재
                "2D 반도체", "2D반도체",
            },
            "strong": {  # +3 — 로직 트랜지스터 + 노광/식각/패터닝 + HBM 적층 기법 (노드는 critical로 이동)
                # 로직 트랜지스터 구조
                "GAA", "게이트올어라운드", "gate-all-around",
                "nanosheet", "나노시트", "CFET",
                "forksheet", "포크시트",
                "RibbonFET", "리본펫", "PowerVia", "파워비아",
                "backside power", "BSPDN", "후면전력공급", "후면전력",
                # 게이트
                "HKMG", "high-k metal gate", "하이k메탈게이트",
                # 노광·패터닝 (메모리/로직 공통 핵심)
                "노광", "lithography", "펠리클", "pellicle",
                "다중패터닝", "멀티패터닝", "multi-patterning", "SADP", "SAQP",
                # 식각 (고종횡비 채널 식각 — 메모리 핵심)
                "식각", "etching", "고종횡비", "high aspect ratio",
                # HBM 적층 공정
                "MR-MUF", "매스리플로우",
                "하이브리드본딩", "하이브리드 본딩", "hybrid bonding",
                # 박막공정 (증착 계열 — 사용자 우선순위: 공정/양산 특히 박막. 8/13 medium→strong 승격)
                "박막", "박막공정", "thin film", "thin-film",
                "증착", "deposition", "ALD", "원자층증착", "CVD", "PVD", "PECVD",
                "선택적증착", "selective deposition",
                # 차세대 박막·소재 (8/13)
                "AS-ALD", "AS ALD", "바텀업", "bottom-up", "컴포멀리티", "conformality",
                "몰리브덴", "molybdenum", "Ru", "루테늄", "ruthenium", "TiN",
                "ONO", "ZAZ", "MIM",
                # 증착·식각·본딩 차세대 (8/13 추가)
                "스퍼터링", "sputtering", "PEALD", "MOCVD", "LPCVD", "HDP-CVD", "FCVD", "flowable CVD",
                "갭필", "gap-fill", "gapfill",
                "크라이오식각", "cryo etch", "극저온식각", "선택비", "selectivity", "bowing", "보우잉",
                "CTF", "charge trap", "차지트랩", "스트링스택", "스트링 스택", "string stacking",
                "Cu-Cu", "구리직접접합", "다이렉트본딩", "direct bonding", "W2W", "D2W",
                "칩온웨이퍼", "chip-on-wafer",
            },
            "medium": {  # +2
                # 패터닝 잔여
                "침지노광", "immersion", "OPC", "포토마스크", "photomask", "레티클", "reticle",
                # 식각 잔여
                "ALE", "원자층식각", "RIE", "건식식각", "dry etch", "플라즈마식각", "plasma etch",
                # 박막 소재 (증착 공정어는 strong으로 이동 — 8/13)
                "SiGe", "실리콘게르마늄",
                # 단위공정 (이온주입·에피·CMP·평탄화)
                "슬러리", "slurry", "평탄화", "planarization", "CMP", "화학기계연마",
                "이온주입", "ion implant", "implantation", "에피택시", "epitaxy", "epitaxial",
                # 트랜지스터/도핑/열처리
                "FinFET", "핀펫", "게이트스택", "gate stack", "일함수", "work function",
                "도핑", "doping", "도펀트", "어닐", "annealing", "RTA", "급속열처리", "접합",
                # 계측·검사
                "metrology", "계측", "overlay", "오버레이", "OCD", "CD-SEM",
                "e-beam", "전자빔", "검사장비", "defect inspection", "결함검사", "yield", "수율",
                # 소재
                "포토레지스트", "photoresist", "high-k", "하이k", "low-k",
                "precursor", "전구체", "MoS2",
                "GaN", "SiC", "compound semiconductor", "화합물반도체", "소부장",
                # 공정 구분
                "FEOL", "MOL", "BEOL", "DTCO",
                # 메모리 구조 잔여
                "10나노급", "peripheral", "QLC", "TLC",
                "웨이퍼본딩", "wafer-on-wafer", "백그라인딩",
                "베이스다이", "베이스 다이", "코어다이", "코어 다이", "버퍼다이", "버퍼 다이",
                # 첨단 패키징 브랜드 (구체어만 medium; 일반어 '패키징'은 domain)
                "칩렛", "chiplet", "chiplets", "TSV",
                "CoWoS", "SoIC", "Foveros", "EMIB",
                "팬아웃", "fan-out", "FOWLP", "FOPLP", "재배선", "RDL",
                "유리기판", "glass substrate", "글래스기판", "글래스 기판", "패널레벨", "panel-level",
                "언더필", "underfill", "워피지", "warpage", "와피지", "웨이퍼보우", "웨이퍼 보우", "wafer bow",
                # 공정 품질·소재·결함 보강 (8/13). 심(한글)은 관심/중심 등 과발화로 제외 — seam/void 영문만
                "습식식각", "wet etch", "신뢰성", "reliability", "번인", "burn-in",
                "특수가스", "specialty gas", "마스크블랭크", "mask blank", "블랭크마스크",
                "몰딩", "molding", "몰드", "EMC", "seam", "void",
                "interposer", "microbump", "2.5D", "3D IC", "UCIe",
                "co-packaged optics", "CPO", "silicon photonics", "실리콘포토닉스",
                "base die",
            },
            "weak": set(),  # 범용 배경어는 domain으로 이동 — 배수 안 받게
        },
        # ── 사건·액션 ──────────────────────────────────────────
        "event": {
            "cap": 5,
            "strong": {  # +3 — 양산·램프업 (사용자 우선순위: 공정/양산. 8/13 medium→strong)
                "양산", "volume production", "mass production", "램프업", "ramp-up",
            },
            "medium": {  # +2
                "수주", "증설", "투자", "인수",
                "점유율", "시장점유율", "market share",  # 시장 지표 (6/25 추가)
                "수출규제", "export control", "보조금", "subsidy",
                "칩스법", "CHIPS Act", "가동률",
                # 생산 조정·양산 지표 (8/13)
                "감산", "production cut", "웨이퍼투입", "웨이퍼 투입", "wafer starts", "웨이퍼인풋",
                # 영문 보강 (구 단위로만 — 일반어 order/investment 단독은 제외)
                "capex", "capacity expansion",
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
                "AI서버", "AI 서버", "AI server",  # 배경어 (P3, 8/13)
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
    "critical": 5,   # 차세대 공정/소자/메모리 (strong 위 신설, 6/25)
    "strong": 3,
    "medium": 2,
    "weak": 1,
    "neg_strong": -3,
    "neg_weak": -2,
}


# 버킷별 가중치 — filter.py 가 버킷 capped 점수에 곱해 합산 (6/25).
# tech를 비즈니스 버킷(product/entity/event)보다 무겁게 둬서, 같은 cap이라도
# 기술 기사가 메모리 시장 뉴스를 점수로 넘어서게 한다. (cap은 그대로, '배수'로 해결)
BUCKET_WEIGHTS = {
    "entity": 1.0,
    "product": 1.0,
    "tech": 1.3,
    "event": 1.0,
    "domain": 1.0,
}


# 버킷별 상한 (KEYWORDS 각 버킷의 "cap" 키가 우선. 누락 시 폴백/참고용)
BUCKET_CAPS = {
    "entity": 5,
    "product": 5,
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
    "하이브리드본딩": {"하이브리드본딩", "하이브리드 본딩", "hybrid bonding"},
    "PIM": {"PIM", "프로세싱인메모리"},
    "베이스다이": {"베이스다이", "베이스 다이", "base die"},
    "코어다이": {"코어다이", "코어 다이"},
    "버퍼다이": {"버퍼다이", "버퍼 다이"},
    "수직D램": {"수직D램", "수직 D램", "3D DRAM", "3D D램"},
    "2D반도체": {"2D 반도체", "2D반도체"},
    # 사건어 영문 (구 단위) — 같은 사건 1회.
    "양산": {"양산", "mass production", "volume production"},
    "램프업": {"램프업", "ramp-up"},
    "수율": {"수율", "yield"},
    "증설": {"증설", "capacity expansion"},
    # ── 전공정 보강 (6/25) — 국문/영문 표면형 1회 접기 ──
    "GAA": {"GAA", "게이트올어라운드", "gate-all-around"},
    "nanosheet": {"nanosheet", "나노시트"},
    "backside_power": {"backside power", "BSPDN", "후면전력공급", "후면전력"},
    "HKMG": {"HKMG", "high-k metal gate", "하이k메탈게이트"},
    "RibbonFET": {"RibbonFET", "리본펫"},
    "PowerVia": {"PowerVia", "파워비아"},
    "forksheet": {"forksheet", "포크시트"},
    "FinFET": {"FinFET", "핀펫"},
    "이온주입": {"이온주입", "ion implant", "implantation"},
    "에피택시": {"에피택시", "epitaxy", "epitaxial"},
    "CMP": {"CMP", "화학기계연마"},
    "다중패터닝": {"다중패터닝", "멀티패터닝", "multi-patterning", "SADP", "SAQP"},
    "펠리클": {"펠리클", "pellicle"},
    "포토마스크": {"포토마스크", "photomask", "레티클", "reticle"},
    "ALE": {"ALE", "원자층식각"},
    "건식식각": {"건식식각", "dry etch"},
    "플라즈마식각": {"플라즈마식각", "plasma etch"},
    "고종횡비": {"고종횡비", "high aspect ratio"},
    "ALD": {"ALD", "원자층증착"},
    "선택적증착": {"선택적증착", "selective deposition"},
    "증착": {"증착", "deposition"},
    "박막": {"박막", "박막공정", "thin film", "thin-film"},
    "AS-ALD": {"AS-ALD", "AS ALD"},
    "바텀업": {"바텀업", "bottom-up", "bottom up"},
    "컴포멀리티": {"컴포멀리티", "conformality"},
    "몰리브덴": {"몰리브덴", "molybdenum"},
    "Ru": {"Ru", "루테늄", "ruthenium"},
    "웨이퍼보우": {"웨이퍼보우", "웨이퍼 보우", "wafer bow"},
    "셀커패시턴스": {"25fF", "10fF", "5fF", "4fF"},
    "퓨리오사": {"퓨리오사", "FuriosaAI", "Furiosa"},
    "AI서버": {"AI서버", "AI 서버", "AI server"},
    "스퍼터링": {"스퍼터링", "sputtering"},
    "갭필": {"갭필", "gap-fill", "gapfill", "gap fill"},
    "FCVD": {"FCVD", "flowable CVD"},
    "크라이오식각": {"크라이오식각", "크라이오 식각", "cryo etch", "극저온식각"},
    "선택비": {"선택비", "selectivity"},
    "bowing": {"bowing", "보우잉"},
    "CTF": {"CTF", "charge trap", "차지트랩"},
    "스트링스택": {"스트링스택", "스트링 스택", "string stacking"},
    "Cu-Cu": {"Cu-Cu", "구리직접접합", "다이렉트본딩", "direct bonding"},
    "칩온웨이퍼": {"칩온웨이퍼", "chip-on-wafer"},
    "셀렉터": {"셀렉터", "selector"},
    "습식식각": {"습식식각", "wet etch"},
    "신뢰성": {"신뢰성", "reliability"},
    "번인": {"번인", "burn-in"},
    "특수가스": {"특수가스", "specialty gas"},
    "마스크블랭크": {"마스크블랭크", "mask blank", "블랭크마스크"},
    "몰딩": {"몰딩", "molding", "몰드"},
    "감산": {"감산", "production cut"},
    "웨이퍼투입": {"웨이퍼투입", "웨이퍼 투입", "wafer starts", "웨이퍼인풋", "wafer input"},
    "SiGe": {"SiGe", "실리콘게르마늄"},
    "슬러리": {"슬러리", "slurry"},
    "평탄화": {"평탄화", "planarization"},
    "게이트스택": {"게이트스택", "gate stack"},
    "일함수": {"일함수", "work function"},
    "도핑": {"도핑", "doping", "도펀트"},
    "어닐": {"어닐", "annealing", "RTA", "급속열처리"},
    "metrology": {"metrology", "계측"},
    "overlay": {"overlay", "오버레이"},
    "e-beam": {"e-beam", "전자빔"},
    "결함검사": {"결함검사", "defect inspection"},
    "high-k": {"high-k", "하이k"},
    "전구체": {"전구체", "precursor"},
    "화합물반도체": {"화합물반도체", "compound semiconductor"},
    "웨이퍼본딩": {"웨이퍼본딩", "wafer-on-wafer"},
    # ── 첨단 패키징 (후공정) 표면형 ──
    "팬아웃": {"팬아웃", "fan-out", "FOWLP", "FOPLP"},
    "RDL": {"재배선", "RDL"},
    "유리기판": {"유리기판", "glass substrate", "글래스기판", "글래스 기판"},
    "패널레벨": {"패널레벨", "panel-level"},
    "언더필": {"언더필", "underfill"},
    "워피지": {"워피지", "warpage", "와피지"},
    "CPO": {"co-packaged optics", "CPO"},
    "실리콘포토닉스": {"실리콘포토닉스", "silicon photonics"},
    # ── 노드: 전체를 한 세트로 1회 카운트 (2나노·3나노 같이 나와도 +1) ──
    "노드": {"3나노", "3nm", "2나노", "2nm", "1.4나노", "1.4nm",
            "1나노", "1nm", "0.7나노", "0.7nm", "sub-2nm", "옹스트롬", "angstrom"},
    # ── DRAM 세대: 1a~1d 한 세트로 1회 ──
    "DRAM세대": {"1a", "1b", "1c", "1d"},
    # ── DRAM 셀 구조 ──
    "새들핀": {"새들핀", "saddle-fin", "saddle fin"},
    "매립게이트": {"매립게이트", "buried word line", "buried gate"},
    "캐패시터리스": {"캐패시터리스", "capacitorless"},
    # ── 단수: NAND/HBM 적층 단수 전체를 한 세트로 1회 (128단·232단 같이 나와도 +1) ──
    "단수": {"128단", "176단", "200단", "232단", "236단", "238단", "280단",
            "300단", "321단", "400단", "430단", "1000단",
            "8단", "12단", "16단", "20단", "24단",
            "8-Hi", "12-Hi", "16-Hi", "20-Hi", "24-Hi"},
    # ── 기업 (국문/영문 1회) ──
    "난야": {"난야", "Nanya"}, "윈본드": {"윈본드", "Winbond"},
    "솔리다임": {"솔리다임", "Solidigm"},
    "웨스턴디지털": {"웨스턴디지털", "Western Digital"}, "샌디스크": {"샌디스크", "SanDisk"},
    "글로벌파운드리": {"글로벌파운드리", "GlobalFoundries"}, "라피더스": {"라피더스", "Rapidus"},
    "어드밴테스트": {"어드밴테스트", "Advantest"}, "신에츠": {"신에츠", "Shin-Etsu"},
    "섬코": {"섬코", "SUMCO"},
    "미디어텍": {"미디어텍", "MediaTek"}, "마벨": {"마벨", "Marvell"},
    "시높시스": {"시높시스", "Synopsys"}, "케이던스": {"케이던스", "Cadence"},
    "시장점유율": {"점유율", "시장점유율", "market share"},
}
