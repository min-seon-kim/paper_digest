"""노션 논문 데이터베이스 초기화: 없으면 생성하고 .env에 ID를 기록."""
from __future__ import annotations

import argparse
import re
import sys

from .config import ENV_PATH, load_settings
from .notion_api import NotionClient, database_properties_schema


def write_env(key: str, value: str) -> None:
    content = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", content, flags=re.M):
        content = re.sub(rf"^{key}=.*$", line, content, flags=re.M)
    else:
        content = content.rstrip("\n") + f"\n{line}\n"
    ENV_PATH.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="노션 논문 데이터베이스 생성")
    parser.add_argument("--title", default="📚 arXiv 논문 아카이브")
    parser.add_argument("--force", action="store_true", help="NOTION_DATABASE_ID가 있어도 새로 생성")
    args = parser.parse_args()

    s = load_settings()
    if not s.notion_token:
        sys.exit("NOTION_TOKEN이 필요합니다.")
    notion = NotionClient(s.notion_token)

    if s.notion_database_id and not args.force:
        try:
            ds_id = notion.data_source_id(s.notion_database_id)
        except RuntimeError as exc:
            sys.exit(f"기존 NOTION_DATABASE_ID에 접근 실패: {exc}\n"
                     "통합이 데이터베이스에 연결됐는지 확인하거나 --force로 새로 만드세요.")
        # 기존 DB에 빠진 속성이 있으면 추가 (속성 이름이 같으면 그대로 둠)
        ds = notion._call("GET", f"/data_sources/{ds_id}")
        missing = {k: v for k, v in database_properties_schema().items()
                   if k not in ds.get("properties", {}) and "title" not in v}
        if missing:
            notion._call("PATCH", f"/data_sources/{ds_id}", json={"properties": missing})
            print(f"누락된 속성 추가: {', '.join(missing)}")
        print(f"✅ 기존 데이터베이스 사용: {s.notion_database_id}")
        return

    if not s.notion_parent_page_id:
        sys.exit("NOTION_PARENT_PAGE_ID(데이터베이스를 만들 페이지 ID)가 필요합니다.")
    db = notion.create_database(s.notion_parent_page_id, args.title)
    write_env("NOTION_DATABASE_ID", db["id"])
    print(f"✅ 데이터베이스 생성 완료: {db['url']}")
    print(f"   NOTION_DATABASE_ID={db['id']}  (.env에 기록됨 — GitHub Secrets에도 등록하세요)")


if __name__ == "__main__":
    main()
