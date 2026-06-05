import os
import sys
import requests
from datetime import datetime, timedelta, timezone

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]

KST = timezone(timedelta(hours=9))


def get_yesterday_kst():
    now_kst = datetime.now(KST)
    yesterday = now_kst - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def check_briefing_exists(target_date):
    url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    payload = {
        "filter": {
            "and": [
                {"property": "날짜", "date": {"equals": target_date}},
                {"property": "카테고리", "multi_select": {"contains": "데일리 브리핑"}},
            ]
        }
    }
    res = requests.post(url, headers=headers, json=payload, timeout=30)
    res.raise_for_status()
    results = res.json().get("results", [])
    return len(results) > 0


def send_slack_alert(target_date):
    msg = f"⚠️ 뉴스 자동화 실패 감지\n{target_date} 데일리 브리핑이 노션에 없습니다.\nJSON 갱신 또는 루틴 실행을 확인하세요."
    requests.post(SLACK_WEBHOOK_URL, json={"text": msg}, timeout=30)


def main():
    target_date = get_yesterday_kst()
    try:
        exists = check_briefing_exists(target_date)
    except Exception as e:
        send_slack_alert(target_date)
        print(f"체크 중 오류 발생, 알림 전송: {e}")
        sys.exit(1)

    if exists:
        print(f"{target_date} 브리핑 존재 확인. 정상.")
    else:
        send_slack_alert(target_date)
        print(f"{target_date} 브리핑 없음. 알림 전송.")


if __name__ == "__main__":
    main()